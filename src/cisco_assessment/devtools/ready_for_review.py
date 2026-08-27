"""Controlled Ready-for-Review transition gated by a fresh PR_REVIEW_AGENT_V1 report."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from .pr_review.check_ids import ReviewCheckId
from .pr_review.enums import ReviewCheckStatus, ReviewDecision
from .pr_review.github import GitHubReadBackend
from .pr_review.models import ReviewReport, ReviewRequest
from .pr_review.reviewer import review_pr

CONTROL_PLANE_ID: Literal["CONTROLLED_READY_FOR_REVIEW_V1"] = "CONTROLLED_READY_FOR_REVIEW_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class ReadyForReviewError(RuntimeError):
    """Raised when the Ready-for-Review gate cannot proceed safely."""


class ReadyForReviewAuthorization(StrEnum):
    """Explicit authorization accepted by the transition gate."""

    READY_FOR_REVIEW = "READY_FOR_REVIEW"


class ReadyForReviewDecision(StrEnum):
    """Canonical outcomes of the controlled transition."""

    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REVIEW_NOT_APPROVED = "REVIEW_NOT_APPROVED"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"


class FrozenReadyForReviewModel(BaseModel):
    """Strict immutable base model for Ready-for-Review contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReadyForReviewOperation(FrozenReadyForReviewModel):
    """Bind one explicit transition authorization to one strict ReviewRequest."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_READY_FOR_REVIEW_V1"] = CONTROL_PLANE_ID
    review_request: ReviewRequest
    authorization: ReadyForReviewAuthorization


class ReadyForReviewResult(FrozenReadyForReviewModel):
    """Canonical output of a review-gated Ready-for-Review transition."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_READY_FOR_REVIEW_V1"] = CONTROL_PLANE_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    pr_url: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    head_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    review_report: ReviewReport
    base_head_after_transition: str | None
    base_fresh_after_transition: bool
    decision: ReadyForReviewDecision
    ready_for_review: bool
    review_executed: Literal[True] = True
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


class ReadyForReviewBackend(Protocol):
    """Minimal mutation surface for the controlled transition."""

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        """Read current pull-request state."""
        ...

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Read one branch ref."""
        ...

    def mark_pull_request_ready(
        self,
        repository: str,
        pr_number: int,
    ) -> Mapping[str, object]:
        """Perform only the Draft -> Ready-for-Review transition."""
        ...


ReviewExecutor = Callable[[ReviewRequest, GitHubReadBackend], ReviewReport]


def execute_ready_for_review(
    operation: ReadyForReviewOperation,
    *,
    review_backend: GitHubReadBackend,
    transition_backend: ReadyForReviewBackend,
    reviewer: ReviewExecutor = review_pr,
) -> ReadyForReviewResult:
    """Run a fresh independent review and mark Ready only on exact APPROVE evidence."""
    operation = ReadyForReviewOperation.model_validate(operation.model_dump(mode="python"))
    if operation.authorization is not ReadyForReviewAuthorization.READY_FOR_REVIEW:
        raise ReadyForReviewError("READY_FOR_REVIEW authorization is required")

    report = ReviewReport.model_validate(
        reviewer(operation.review_request, review_backend).model_dump(mode="python")
    )
    _validate_report_binding(operation.review_request, report)
    pr_url = _pull_request_url(report.repository, report.pr_number)

    if report.decision is not ReviewDecision.APPROVE:
        return _result(
            report=report,
            pr_url=pr_url,
            base_head_after_transition=report.base_branch_head_sha,
            base_fresh_after_transition=report.base_branch_head_sha is not None,
            decision=ReadyForReviewDecision.REVIEW_NOT_APPROVED,
            ready_for_review=False,
        )

    if report.base_branch_head_sha is None:
        raise ReadyForReviewError("APPROVE report must contain current base branch HEAD evidence")
    _require_ci_merge_provenance_pass(report)

    _validate_live_draft_pr(
        transition_backend.get_pull_request(report.repository, report.pr_number),
        report,
    )
    if not _refs_match_report(transition_backend, report):
        return _result(
            report=report,
            pr_url=pr_url,
            base_head_after_transition=_branch_sha(
                transition_backend.get_branch(report.repository, report.base_branch),
                "base branch",
            ),
            base_fresh_after_transition=False,
            decision=ReadyForReviewDecision.NEEDS_BASE_REFRESH,
            ready_for_review=False,
        )

    # Re-read both refs immediately before the only permitted mutation.
    if not _refs_match_report(transition_backend, report):
        return _result(
            report=report,
            pr_url=pr_url,
            base_head_after_transition=_branch_sha(
                transition_backend.get_branch(report.repository, report.base_branch),
                "base branch",
            ),
            base_fresh_after_transition=False,
            decision=ReadyForReviewDecision.NEEDS_BASE_REFRESH,
            ready_for_review=False,
        )

    transition_backend.mark_pull_request_ready(report.repository, report.pr_number)
    _validate_ready_pr(
        transition_backend.get_pull_request(report.repository, report.pr_number),
        report,
    )
    base_head_after = _branch_sha(
        transition_backend.get_branch(report.repository, report.base_branch),
        "base branch",
    )
    head_after = _branch_sha(
        transition_backend.get_branch(report.repository, report.head_branch),
        "head branch",
    )
    base_fresh = (
        base_head_after == report.base_branch_head_sha
        and head_after == report.head_sha
    )
    return _result(
        report=report,
        pr_url=pr_url,
        base_head_after_transition=base_head_after,
        base_fresh_after_transition=base_fresh,
        decision=(
            ReadyForReviewDecision.READY_FOR_REVIEW
            if base_fresh
            else ReadyForReviewDecision.NEEDS_BASE_REFRESH
        ),
        ready_for_review=True,
    )


def _require_ci_merge_provenance_pass(report: ReviewReport) -> None:
    matches = tuple(
        check for check in report.checks if check.check_id is ReviewCheckId.CI_003
    )
    if len(matches) != 1:
        raise ReadyForReviewError(
            "APPROVE report must contain exactly one CI-003 merge-provenance check"
        )
    check = matches[0]
    if (
        not check.applicable
        or check.status is not ReviewCheckStatus.PASS
        or not check.evidence
    ):
        raise ReadyForReviewError(
            "APPROVE report must contain applicable CI-003 PASS evidence"
        )


def _validate_report_binding(request: ReviewRequest, report: ReviewReport) -> None:
    if report.agent_id != "PR_REVIEW_AGENT_V1":
        raise ReadyForReviewError("review report must originate from PR_REVIEW_AGENT_V1")
    if report.repository != request.repository or report.pr_number != request.pr_number:
        raise ReadyForReviewError("review report repository/PR binding does not match the request")
    if report.base_branch != request.expected_base_branch:
        raise ReadyForReviewError("review report base branch does not match the request")
    if report.objective != request.objective:
        raise ReadyForReviewError("review report objective does not match the request")


def _validate_live_draft_pr(payload: Mapping[str, object], report: ReviewReport) -> None:
    if _require_str(payload, "state") != "open":
        raise ReadyForReviewError("pull request must remain open before Ready-for-Review")
    if _require_bool(payload, "draft") is not True:
        raise ReadyForReviewError("pull request must still be Draft before transition")
    if _require_bool(payload, "merged") is not False:
        raise ReadyForReviewError("merged pull requests cannot enter Ready-for-Review gate")
    _validate_live_refs(payload, report)


def _validate_ready_pr(payload: Mapping[str, object], report: ReviewReport) -> None:
    if _require_str(payload, "state") != "open":
        raise ReadyForReviewError("pull request must remain open after Ready-for-Review")
    if _require_bool(payload, "draft") is not False:
        raise ReadyForReviewError("GitHub read-back did not confirm Ready-for-Review")
    if _require_bool(payload, "merged") is not False:
        raise ReadyForReviewError("Ready-for-Review transition must never merge the pull request")
    _validate_live_refs(payload, report)


def _validate_live_refs(payload: Mapping[str, object], report: ReviewReport) -> None:
    base = _require_mapping(payload, "base")
    head = _require_mapping(payload, "head")
    if _require_str(base, "ref") != report.base_branch or _require_str(base, "sha") != report.base_sha:
        raise ReadyForReviewError("pull request base ref/SHA no longer matches reviewed evidence")
    if _require_str(head, "ref") != report.head_branch or _require_str(head, "sha") != report.head_sha:
        raise ReadyForReviewError("pull request head ref/SHA no longer matches reviewed evidence")


def _refs_match_report(backend: ReadyForReviewBackend, report: ReviewReport) -> bool:
    if report.base_branch_head_sha is None:
        return False
    base_sha = _branch_sha(backend.get_branch(report.repository, report.base_branch), "base branch")
    head_sha = _branch_sha(backend.get_branch(report.repository, report.head_branch), "head branch")
    return base_sha == report.base_branch_head_sha and head_sha == report.head_sha


def _branch_sha(payload: Mapping[str, object] | None, label: str) -> str:
    if payload is None:
        raise ReadyForReviewError(f"{label} is unavailable")
    commit = _require_mapping(payload, "commit")
    return _require_str(commit, "sha")


def _pull_request_url(repository: str, pr_number: int) -> str:
    return f"https://github.com/{repository}/pull/{pr_number}"


def _result(
    *,
    report: ReviewReport,
    pr_url: str,
    base_head_after_transition: str | None,
    base_fresh_after_transition: bool,
    decision: ReadyForReviewDecision,
    ready_for_review: bool,
) -> ReadyForReviewResult:
    return ReadyForReviewResult(
        repository=report.repository,
        pr_number=report.pr_number,
        pr_url=pr_url,
        base_branch=report.base_branch,
        base_sha=report.base_sha,
        head_branch=report.head_branch,
        head_sha=report.head_sha,
        review_report=report,
        base_head_after_transition=base_head_after_transition,
        base_fresh_after_transition=base_fresh_after_transition,
        decision=decision,
        ready_for_review=ready_for_review,
    )


def _require_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ReadyForReviewError(f"GitHub field {key!r} must be an object")
    return cast(Mapping[str, object], value)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ReadyForReviewError(f"GitHub field {key!r} must be a non-empty string")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ReadyForReviewError(f"GitHub field {key!r} must be a boolean")
    return value
