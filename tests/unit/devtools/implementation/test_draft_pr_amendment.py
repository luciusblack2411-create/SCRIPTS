from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence

import pytest

from cisco_assessment.devtools.implementation.draft_pr_amendment import (
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
BRANCH = "feat/m14-switchport-observation-data-model"


def request() -> ImplementationDraftPrAmendmentRequest:
    return ImplementationDraftPrAmendmentRequest(repository="owner/repo", objective="correct amendment", pr_number=93, base_branch="main", base_sha=BASE, work_branch=BRANCH, expected_head_sha=OLD, commit_message="fix: amend draft", authorized_components=(ComponentId.TESTING_FIXTURES,), prohibited_components=(ComponentId.PARSER,), changes=(ImplementationDraftPrAmendmentChange(kind=ImplementationFileChangeKind.CREATE, path="tests/unit/test_fix.py", proposed_content="def test_fix():\n    assert True\n", component=ComponentId.TESTING_FIXTURES),))


class Backend:
    def __init__(self) -> None:
        self.branches = {"main": BASE, BRANCH: OLD}
        self.pr: Mapping[str, object] | None = self.payload(OLD)
        self.race = False
        self.base_drift_ci = False
        self.dispatched: list[tuple[str, str, str]] = []

    def payload(self, sha: str) -> Mapping[str, object]:
        return {"number": 93, "state": "open", "draft": True, "merged": False, "base": {"ref": "main", "sha": BASE}, "head": {"ref": BRANCH, "sha": sha, "repo": {"full_name": "owner/repo"}}}

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object] | None:
        del repository, pr_number
        return self.pr

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        del repository
        if self.base_drift_ci and self.dispatched and branch == "main":
            return {"commit": {"sha": "advanced"}}
        return {"commit": {"sha": self.branches[branch]}}

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
        if self.race:
            self.branches[BRANCH] = "racer"
        return NEW

    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]:
        del repository
        return {"sha": commit_sha, "tree": {"sha": "new-tree"}, "parents": [{"sha": OLD}]}

    def update_existing_ref_fast_forward(self, repository: str, branch: str, commit_sha: str) -> None:
        del repository
        self.branches[branch] = commit_sha
        self.pr = self.payload(commit_sha)

    def dispatch_amendment_ci(self, repository: str, workflow_file: str, branch: str) -> None:
        self.dispatched.append((repository, workflow_file, branch))

    def list_amendment_ci_runs(self, repository: str, workflow_file: str, *, branch: str, head_sha: str) -> Sequence[Mapping[str, object]]:
        del repository, workflow_file
        return ({"id": 7, "event": "workflow_dispatch", "head_branch": branch, "head_sha": head_sha, "status": "completed", "conclusion": "success"},)

    def list_amendment_ci_jobs(self, repository: str, run_id: int) -> Sequence[Mapping[str, object]]:
        del repository, run_id
        return ({"status": "completed", "conclusion": "success"},)


def test_success_supports_exact_non_agent_branch_and_result_flags() -> None:
    backend = Backend()
    result = execute_draft_pr_amendment(request(), backend)
    assert (result.old_head_sha, result.new_head_sha) == (OLD, NEW)
    assert result.ci.commit_sha == NEW
    assert backend.dispatched == [("owner/repo", "ci.yml", BRANCH)]
    assert result.ready_for_review is False and result.merge_performed is False
    assert result.human_merge_gate_required is True and result.cisco_execution_allowed is False


@pytest.mark.parametrize(("change", "match"), [(lambda b: setattr(b, "pr", None), "missing"), (lambda b: setattr(b, "pr", {**b.payload(OLD), "draft": False}), "open, Draft"), (lambda b: setattr(b, "pr", {**b.payload(OLD), "merged": True}), "open, Draft"), (lambda b: setattr(b, "pr", {**b.payload(OLD), "state": "closed"}), "open, Draft"), (lambda b: b.branches.__setitem__(BRANCH, "stale"), "moved"), (lambda b: b.branches.__setitem__("main", "stale"), "moved")])
def test_fail_closed_pr_and_ref_evidence(change: object, match: str) -> None:
    backend = Backend()
    change(backend)  # type: ignore[operator]
    with pytest.raises(ImplementationDraftPrAmendmentError, match=match):
        execute_draft_pr_amendment(request(), backend)


def test_unauthorized_path_and_concurrent_race_are_rejected() -> None:
    bad = request().model_copy(update={"changes": (request().changes[0].model_copy(update={"path": "src/cisco_assessment/parsers/x.py", "component": ComponentId.PARSER}),)})
    with pytest.raises(ImplementationDraftPrAmendmentError, match="unauthorized"):
        execute_draft_pr_amendment(bad, Backend())
    backend = Backend(); backend.race = True
    with pytest.raises(ImplementationDraftPrAmendmentError, match="moved"):
        execute_draft_pr_amendment(request(), backend)


def test_base_drift_during_ci_is_rejected() -> None:
    backend = Backend(); backend.base_drift_ci = True
    with pytest.raises(ImplementationDraftPrAmendmentError, match="drifted"):
        execute_draft_pr_amendment(request(), backend)


def test_force_is_not_public_and_payload_contract_is_fixed() -> None:
    signature = inspect.signature(UrllibGitHubDraftPrAmendmentTransport.patch_ref_fast_forward)
    assert "force" not in signature.parameters
    source = inspect.getsource(UrllibGitHubDraftPrAmendmentTransport.patch_ref_fast_forward)
    assert '"force": False' in source


def test_amendment_token_has_no_generic_fallback() -> None:
    with pytest.raises(ImplementationDraftPrAmendmentControlPlaneError, match="forbidden"):
        resolve_amendment_token({"GITHUB_TOKEN": "generic", "GH_TOKEN": "generic"})
    assert resolve_amendment_token({AMENDMENT_TOKEN_ENV: "dedicated", "GITHUB_TOKEN": "generic"}) == "dedicated"
