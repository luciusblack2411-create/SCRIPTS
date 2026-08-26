from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation.draft_pr_amendment import (
    AmendmentCiStatus,
    AmendmentDecision,
    ImplementationDraftPrAmendmentChange,
    ImplementationDraftPrAmendmentError,
    ImplementationDraftPrAmendmentRequest,
    execute_draft_pr_amendment,
)
from cisco_assessment.devtools.implementation.draft_pr_amendment_control_plane import (
    AMENDMENT_TOKEN_ENV,
    ImplementationDraftPrAmendmentControlPlaneError,
    resolve_amendment_token,
)
from cisco_assessment.devtools.implementation.enums import ImplementationFileChangeKind
from cisco_assessment.devtools.implementation.github_draft_pr_amendment import (
    UrllibGitHubDraftPrAmendmentTransport,
)
from cisco_assessment.devtools.implementation.mutation import ImplementationMutationTreeEntry
from cisco_assessment.devtools.pr_review.enums import ComponentId

OLD = "old-head"
NEW = "new-head"
BASE = "base-sha"
PR_BASE_OLD = "pr-base-old"
BRANCH = "feat/m14-switchport-observation-data-model"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Backend:
    def __init__(
        self,
        *,
        pr_base_sha: str = BASE,
        post_update_pr_base_sha: str | None = None,
    ) -> None:
        self.branches = {"main": BASE, BRANCH: OLD}
        self.pr_base_sha = pr_base_sha
        self.post_update_pr_base_sha = post_update_pr_base_sha
        self.pr: Mapping[str, object] | None = self.payload(
            OLD,
            base_sha=pr_base_sha,
        )
        self.race = False
        self.base_drift = False
        self.dispatched = 0
        self.poll = 0
        self.runs: Callable[[int], Sequence[Mapping[str, object]]] = lambda poll: (
            self.run(7, "completed", "success"),
        ) if poll > 0 else ()
        self.jobs: Sequence[Mapping[str, object]] = (
            {"id": 11, "name": "quality", "status": "completed", "conclusion": "success"},
        )

    def payload(
        self,
        sha: str,
        repository: str = "owner/repo",
        *,
        base_sha: str | None = None,
    ) -> Mapping[str, object]:
        observed_base_sha = (
            self.pr_base_sha if base_sha is None else base_sha
        )
        return {
            "number": 93,
            "state": "open",
            "draft": True,
            "merged": False,
            "base": {
                "ref": "main",
                "sha": observed_base_sha,
                "repo": {"full_name": "owner/repo"},
            },
            "head": {
                "ref": BRANCH,
                "sha": sha,
                "repo": {"full_name": repository},
            },
        }

    def run(self, run_id: int, status: str, conclusion: str | None) -> Mapping[str, object]:
        return {"id": run_id, "event": "workflow_dispatch", "head_branch": BRANCH, "head_sha": NEW, "status": status, "conclusion": conclusion}

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None:
        del repository, pr_number
        return self.pr

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        del repository
        sha = "advanced" if self.base_drift and self.dispatched and branch == "main" else self.branches.get(branch)
        return None if sha is None else {"commit": {"sha": sha}}

    def list_tree(self, repository: str, commit_sha: str) -> Sequence[Mapping[str, object]]:
        del repository, commit_sha
        return ()

    def get_commit_tree_sha(self, repository: str, commit_sha: str) -> str:
        del repository
        assert commit_sha == OLD
        return "old-tree"

    def create_utf8_blob(self, repository: str, content: str) -> str:
        del repository, content
        return "blob"

    def create_tree(self, repository: str, base_tree_sha: str, entries: Sequence[ImplementationMutationTreeEntry]) -> str:
        del repository, entries
        assert base_tree_sha == "old-tree"
        return "new-tree"

    def create_commit(self, repository: str, *, message: str, tree_sha: str, parent_sha: str) -> str:
        del repository, message
        assert (tree_sha, parent_sha) == ("new-tree", OLD)
        return NEW

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        del repository
        return {"sha": commit_sha, "tree": {"sha": "new-tree"}, "parents": [{"sha": OLD}]}

    def update_existing_ref_fast_forward(self, repository: str, branch: str, old_sha: str, new_sha: str) -> None:
        del repository
        assert old_sha == OLD
        if self.race:
            self.branches[branch] = "racer"
        if self.branches[branch] != old_sha:
            raise ImplementationDraftPrAmendmentError("branch moved before PATCH")
        self.branches[branch] = new_sha
        post_base = (
            self.pr_base_sha
            if self.post_update_pr_base_sha is None
            else self.post_update_pr_base_sha
        )
        self.pr = self.payload(
            new_sha,
            base_sha=post_base,
        )

    def dispatch_amendment_ci(self, repository: str, workflow_file: str, branch: str) -> None:
        assert (repository, workflow_file, branch) == ("owner/repo", "ci.yml", BRANCH)
        self.dispatched += 1

    def list_amendment_ci_runs(self, repository: str, workflow_file: str, *, branch: str, head_sha: str) -> Sequence[Mapping[str, object]]:
        del repository, workflow_file, branch, head_sha
        value = self.runs(self.poll)
        self.poll += 1
        return value

    def list_amendment_ci_jobs(self, repository: str, run_id: int) -> Sequence[Mapping[str, object]]:
        del repository, run_id
        return self.jobs


def request() -> ImplementationDraftPrAmendmentRequest:
    return ImplementationDraftPrAmendmentRequest(
        repository="owner/repo",
        objective="production-safe amendment",
        pr_number=93,
        base_branch="main",
        base_sha=BASE,
        work_branch=BRANCH,
        expected_head_sha=OLD,
        commit_message="fix: amend draft",
        authorized_components=(ComponentId.TESTING_FIXTURES,),
        prohibited_components=(ComponentId.PARSER,),
        changes=(ImplementationDraftPrAmendmentChange(kind=ImplementationFileChangeKind.CREATE, path="tests/unit/test_fix.py", proposed_content="def test_fix():\n    assert True\n", component=ComponentId.TESTING_FIXTURES),),
    )


def execute(backend: Backend, clock: Clock | None = None):
    actual_clock = clock or Clock()
    return execute_draft_pr_amendment(request(), backend, timeout_seconds=3, poll_interval_seconds=1, clock=actual_clock, sleeper=actual_clock.sleep)


def test_success_uses_exact_non_agent_branch_and_records_flags() -> None:
    backend = Backend()
    legacy_request = request()
    assert legacy_request.expected_pr_base_sha is None
    result = execute(backend)
    assert result.work_branch == BRANCH
    assert result.pr_base_sha_before == BASE
    assert result.pr_base_sha_after == BASE
    assert (result.old_head_sha, result.new_head_sha) == (OLD, NEW)
    assert result.ci.ci_status is AmendmentCiStatus.PASSED
    assert result.ci.decision is AmendmentDecision.READY_FOR_DRAFT_PR
    assert result.ci.commit_sha == NEW and result.ci.base_fresh_after_ci is True
    assert backend.dispatched == 1
    assert result.ready_for_review is False and result.merge_performed is False
    assert result.human_merge_gate_required is True and result.cisco_execution_allowed is False


@pytest.mark.parametrize(
    "mutatee",
    [
        lambda backend: setattr(backend, "pr", None),
        lambda backend: setattr(backend, "pr", {**backend.payload(OLD), "state": "closed"}),
        lambda backend: setattr(backend, "pr", {**backend.payload(OLD), "draft": False}),
        lambda backend: setattr(backend, "pr", {**backend.payload(OLD), "merged": True}),
        lambda backend: setattr(backend, "pr", backend.payload(OLD, "fork/repo")),
        lambda backend: backend.branches.__setitem__("main", "stale"),
        lambda backend: backend.branches.__setitem__(BRANCH, "stale"),
    ],
)
def test_pr_and_ref_failures_are_rejected(mutatee: Callable[[Backend], None]) -> None:
    backend = Backend()
    mutatee(backend)
    with pytest.raises(ImplementationDraftPrAmendmentError):
        execute(backend)


def test_unauthorized_path_and_ref_race_fail_closed() -> None:
    bad_change = request().changes[0].model_copy(update={"path": "src/cisco_assessment/parsers/x.py", "component": ComponentId.PARSER})
    bad = request().model_copy(update={"changes": (bad_change,)})
    with pytest.raises(ImplementationDraftPrAmendmentError, match="unauthorized"):
        execute_draft_pr_amendment(bad, Backend())
    backend = Backend()
    backend.race = True
    with pytest.raises(ImplementationDraftPrAmendmentError, match="moved"):
        execute(backend)


def test_preexisting_run_is_ignored_and_queued_run_is_polled() -> None:
    backend = Backend()
    backend.runs = lambda poll: (
        (backend.run(6, "completed", "success"),)
        if poll == 0
        else (backend.run(6, "completed", "success"), backend.run(7, "queued", None))
        if poll == 1
        else (backend.run(6, "completed", "success"), backend.run(7, "completed", "success"))
    )
    result = execute(backend)
    assert result.ci.run_id == 7 and backend.dispatched == 1


def test_multiple_fresh_runs_timeout_workflow_job_and_base_failures() -> None:
    backend = Backend()
    backend.runs = lambda poll: () if poll == 0 else (backend.run(7, "queued", None), backend.run(8, "queued", None))
    with pytest.raises(ImplementationDraftPrAmendmentError, match="multiple"):
        execute(backend)

    backend = Backend()
    backend.runs = lambda poll: ()
    with pytest.raises(ImplementationDraftPrAmendmentError, match="timed out"):
        execute(backend)

    backend = Backend()
    backend.runs = lambda poll: () if poll == 0 else (backend.run(7, "completed", "failure"),)
    with pytest.raises(ImplementationDraftPrAmendmentError, match="workflow failed"):
        execute(backend)

    backend = Backend()
    backend.jobs = ({"id": 11, "name": "quality", "status": "completed", "conclusion": "failure"},)
    with pytest.raises(ImplementationDraftPrAmendmentError, match="job failed"):
        execute(backend)

    backend = Backend()
    backend.base_drift = True
    with pytest.raises(ImplementationDraftPrAmendmentError, match="drifted"):
        execute(backend)


def test_public_update_and_transport_patch_have_no_force_argument() -> None:
    assert "force" not in inspect.signature(Backend.update_existing_ref_fast_forward).parameters
    assert "force" not in inspect.signature(UrllibGitHubDraftPrAmendmentTransport.patch_ref_fast_forward).parameters


def test_token_never_falls_back_to_generic_credentials() -> None:
    with pytest.raises(ImplementationDraftPrAmendmentControlPlaneError, match="forbidden"):
        resolve_amendment_token({"GITHUB_TOKEN": "generic", "GH_TOKEN": "generic"})
    assert resolve_amendment_token({AMENDMENT_TOKEN_ENV: "dedicated", "GITHUB_TOKEN": "generic"}) == "dedicated"


def test_request_rejects_noncanonical_branch() -> None:
    with pytest.raises(ValidationError):
        request().model_copy(update={"work_branch": "bad branch"}).__class__.model_validate(
            request().model_dump() | {"work_branch": "bad branch"}
        )


def _execute_request(
    amendment_request: ImplementationDraftPrAmendmentRequest,
    backend: Backend,
):
    clock = Clock()
    return execute_draft_pr_amendment(
        amendment_request,
        backend,
        timeout_seconds=3,
        poll_interval_seconds=1,
        clock=clock,
        sleeper=clock.sleep,
    )


def _request_with_pr_base(
    expected_pr_base_sha: str,
) -> ImplementationDraftPrAmendmentRequest:
    return ImplementationDraftPrAmendmentRequest.model_validate(
        request().model_dump(mode="python")
        | {"expected_pr_base_sha": expected_pr_base_sha}
    )


def test_old_pr_base_snapshot_is_independent_from_live_main() -> None:
    backend = Backend(pr_base_sha=PR_BASE_OLD)
    result = _execute_request(
        _request_with_pr_base(PR_BASE_OLD),
        backend,
    )

    assert result.base_sha == BASE
    assert result.pr_base_sha_before == PR_BASE_OLD
    assert result.pr_base_sha_after == PR_BASE_OLD
    assert result.ci.base_head_after_ci == BASE
    assert result.ci.base_fresh_after_ci is True


def test_incorrect_pr_base_snapshot_fails_before_mutation() -> None:
    backend = Backend(pr_base_sha=PR_BASE_OLD)

    with pytest.raises(
        ImplementationDraftPrAmendmentError,
        match="binding is stale",
    ):
        _execute_request(
            _request_with_pr_base("wrong-pr-base"),
            backend,
        )

    assert backend.branches[BRANCH] == OLD
    assert backend.dispatched == 0


def test_live_main_mismatch_is_rejected_independently() -> None:
    backend = Backend(pr_base_sha=PR_BASE_OLD)
    backend.branches["main"] = "stale-live-main"

    with pytest.raises(
        ImplementationDraftPrAmendmentError,
        match="branch 'main' moved",
    ):
        _execute_request(
            _request_with_pr_base(PR_BASE_OLD),
            backend,
        )

    assert backend.branches[BRANCH] == OLD
    assert backend.dispatched == 0


def test_post_amendment_pr_base_may_refresh_to_live_main() -> None:
    backend = Backend(
        pr_base_sha=PR_BASE_OLD,
        post_update_pr_base_sha=BASE,
    )

    result = _execute_request(
        _request_with_pr_base(PR_BASE_OLD),
        backend,
    )

    assert result.pr_base_sha_before == PR_BASE_OLD
    assert result.pr_base_sha_after == BASE
    assert result.base_sha == BASE


def test_unexpected_third_post_amendment_pr_base_is_rejected() -> None:
    backend = Backend(
        pr_base_sha=PR_BASE_OLD,
        post_update_pr_base_sha="unexpected-third-base",
    )

    with pytest.raises(
        ImplementationDraftPrAmendmentError,
        match="binding is stale",
    ):
        _execute_request(
            _request_with_pr_base(PR_BASE_OLD),
            backend,
        )

    assert backend.branches[BRANCH] == NEW
    assert backend.dispatched == 0

