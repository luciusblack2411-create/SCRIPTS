from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from cisco_assessment.devtools.implementation.ci_validation import (
    ImplementationCiJobResult,
    ImplementationCiStatus,
    ImplementationCiValidationResult,
    ImplementationOperationalDecision,
)
from cisco_assessment.devtools.implementation.draft_pr import (
    ImplementationDraftPrDecision,
    ImplementationDraftPrError,
    ImplementationDraftPrRequest,
    prepare_implementation_draft_pr,
)
from cisco_assessment.devtools.implementation.enums import (
    ImplementationAuthorization,
    ImplementationFileChangeKind,
)
from cisco_assessment.devtools.implementation.mutation import (
    ImplementationMutationChangeResult,
    ImplementationMutationResult,
)
from cisco_assessment.devtools.implementation.operational import ImplementationOperationalResult

BASE_SHA = "base-123"
COMMIT_SHA = "commit-456"
WORK_BRANCH = "agent/implementation/draft-pr-example"
OBJECTIVE = "Create a Draft PR only after exact work-branch CI passes."
TITLE = "feat(devtools): controlled Draft PR pilot"
BODY = "Draft PR prepared from exact IMPLEMENTATION_AGENT_V1 evidence."


def _mutation() -> ImplementationMutationResult:
    content = b"test = True\n"
    return ImplementationMutationResult(
        repository="owner/repo",
        base_branch="main",
        base_sha=BASE_SHA,
        workspace_sha256="a" * 64,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        tree_sha="tree-789",
        changes=(
            ImplementationMutationChangeResult(
                ordinal=1,
                change_id="impl-change:0001",
                kind=ImplementationFileChangeKind.CREATE,
                path="tests/unit/devtools/implementation/test_generated.py",
                published_blob_sha="blob-new",
                proposed_content_sha256=hashlib.sha256(content).hexdigest(),
            ),
        ),
        base_head_after_publish=BASE_SHA,
        base_fresh_after_publish=True,
    )


def _ci(*, base_after: str = BASE_SHA) -> ImplementationCiValidationResult:
    return ImplementationCiValidationResult(
        repository="owner/repo",
        base_branch="main",
        base_sha=BASE_SHA,
        work_branch=WORK_BRANCH,
        commit_sha=COMMIT_SHA,
        run_id=101,
        ci_status=ImplementationCiStatus.PASSED,
        workflow_conclusion="success",
        jobs=(
            ImplementationCiJobResult(
                job_id=11,
                name="quality (3.11)",
                conclusion="success",
            ),
        ),
        base_head_after_ci=base_after,
        base_fresh_after_ci=base_after == BASE_SHA,
        decision=(
            ImplementationOperationalDecision.READY_FOR_DRAFT_PR
            if base_after == BASE_SHA
            else ImplementationOperationalDecision.NEEDS_BASE_REFRESH
        ),
    )


def _operational() -> ImplementationOperationalResult:
    return ImplementationOperationalResult(
        repository="owner/repo",
        objective=OBJECTIVE,
        mutation=_mutation(),
        ci_validation=_ci(),
        decision=ImplementationOperationalDecision.READY_FOR_DRAFT_PR,
    )


def _request(**updates: object) -> ImplementationDraftPrRequest:
    values: dict[str, object] = {
        "repository": "owner/repo",
        "objective": OBJECTIVE,
        "base_branch": "main",
        "base_sha": BASE_SHA,
        "work_branch": WORK_BRANCH,
        "commit_sha": COMMIT_SHA,
        "title": TITLE,
        "body": BODY,
        "authorization": ImplementationAuthorization.DRAFT_PR,
    }
    values.update(updates)
    return ImplementationDraftPrRequest(**values)  # type: ignore[arg-type]


def _branch(sha: str) -> Mapping[str, object]:
    return {"commit": {"sha": sha}}


def _pr_payload() -> Mapping[str, object]:
    return {
        "number": 57,
        "html_url": "https://github.com/owner/repo/pull/57",
        "title": TITLE,
        "state": "open",
        "draft": True,
        "base": {"ref": "main", "sha": BASE_SHA},
        "head": {"ref": WORK_BRANCH, "sha": COMMIT_SHA},
    }


class FakeDraftPrBackend:
    def __init__(self, *, base_after_create: str = BASE_SHA) -> None:
        self.base_after_create = base_after_create
        self.create_calls = 0
        self.base_reads = 0
        self.existing: tuple[Mapping[str, object], ...] = ()

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        assert repository == "owner/repo"
        if branch == "main":
            self.base_reads += 1
            return _branch(BASE_SHA if self.base_reads == 1 else self.base_after_create)
        if branch == WORK_BRANCH:
            return _branch(COMMIT_SHA)
        return None

    def list_open_pull_requests(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> Sequence[Mapping[str, object]]:
        assert repository == "owner/repo"
        assert base_branch == "main"
        assert head_branch == WORK_BRANCH
        return self.existing

    def create_draft_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
    ) -> Mapping[str, object]:
        assert repository == "owner/repo"
        assert (title, body, base_branch, head_branch) == (TITLE, BODY, "main", WORK_BRANCH)
        self.create_calls += 1
        return _pr_payload()

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        assert repository == "owner/repo"
        assert pr_number == 57
        return _pr_payload()


def test_prepare_draft_pr_creates_only_verified_draft() -> None:
    backend = FakeDraftPrBackend()

    result = prepare_implementation_draft_pr(_operational(), _request(), backend)

    assert backend.create_calls == 1
    assert result.pr_number == 57
    assert result.draft is True
    assert result.decision is ImplementationDraftPrDecision.DRAFT_PR_CREATED
    assert result.pull_request_created is True
    assert result.pull_request_ready_for_review is False
    assert result.review_executed is False
    assert result.merge_performed is False
    assert result.human_merge_gate_required is True
    assert result.cisco_execution_allowed is False


def test_prepare_draft_pr_records_post_create_base_drift() -> None:
    backend = FakeDraftPrBackend(base_after_create="base-new")

    result = prepare_implementation_draft_pr(_operational(), _request(), backend)

    assert result.pull_request_created is True
    assert result.base_fresh_after_create is False
    assert result.decision is ImplementationDraftPrDecision.NEEDS_BASE_REFRESH
    assert result.pull_request_ready_for_review is False


def test_prepare_draft_pr_rejects_stale_base_before_creation() -> None:
    backend = FakeDraftPrBackend()
    backend.base_reads = -1
    backend.base_after_create = "base-new"

    def stale_get_branch(repository: str, branch: str) -> Mapping[str, object] | None:
        if branch == "main":
            return _branch("base-new")
        if branch == WORK_BRANCH:
            return _branch(COMMIT_SHA)
        return None

    backend.get_branch = stale_get_branch  # type: ignore[method-assign]

    with pytest.raises(ImplementationDraftPrError, match="moved"):
        prepare_implementation_draft_pr(_operational(), _request(), backend)

    assert backend.create_calls == 0


def test_prepare_draft_pr_rejects_duplicate_open_pr() -> None:
    backend = FakeDraftPrBackend()
    backend.existing = (_pr_payload(),)

    with pytest.raises(ImplementationDraftPrError, match="already exists"):
        prepare_implementation_draft_pr(_operational(), _request(), backend)

    assert backend.create_calls == 0


def test_prepare_draft_pr_rejects_authorization_not_bound_to_operational_evidence() -> None:
    with pytest.raises(ImplementationDraftPrError, match="exact operational result"):
        prepare_implementation_draft_pr(
            _operational(),
            _request(commit_sha="different-commit"),
            FakeDraftPrBackend(),
        )


def test_draft_pr_request_requires_explicit_draft_pr_authorization() -> None:
    with pytest.raises(ValidationError, match="DRAFT_PR"):
        _request(authorization=ImplementationAuthorization.WORK_BRANCH)
