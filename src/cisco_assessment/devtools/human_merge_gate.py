"""Controlled human-authorized merge gate with fresh PR review and exact ref checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pr_review.check_ids import ReviewCheckId
from .pr_review.enums import ReviewCheckStatus, ReviewDecision
from .pr_review.github import GitHubReadBackend
from .pr_review.models import ReviewReport, ReviewRequest
from .pr_review.reviewer import review_pr

CONTROL_PLANE_ID: Literal["CONTROLLED_HUMAN_MERGE_V1"] = "CONTROLLED_HUMAN_MERGE_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class HumanMergeError(RuntimeError): pass


class HumanMergeDecision(StrEnum):
    MERGED = "MERGED"
    REVIEW_NOT_APPROVED = "REVIEW_NOT_APPROVED"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"


class FrozenHumanMergeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HumanMergeAuthorization(FrozenHumanMergeModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    decision: Literal["MERGE_APPROVED"]
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_sha: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    authorized_by: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class HumanMergeOperation(FrozenHumanMergeModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_HUMAN_MERGE_V1"] = CONTROL_PLANE_ID
    review_request: ReviewRequest
    authorization: HumanMergeAuthorization
    merge_method: Literal["merge"] = "merge"

    @model_validator(mode="after")
    def validate_authorization_binding(self) -> HumanMergeOperation:
        if self.authorization.repository != self.review_request.repository:
            raise ValueError("human merge authorization repository must match review request")
        if self.authorization.pr_number != self.review_request.pr_number:
            raise ValueError("human merge authorization PR number must match review request")
        return self


class HumanMergeResult(FrozenHumanMergeModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_HUMAN_MERGE_V1"] = CONTROL_PLANE_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    pr_url: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    head_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    review_report: ReviewReport
    authorization: HumanMergeAuthorization
    decision: HumanMergeDecision
    merge_performed: bool
    merge_commit_sha: str | None
    main_head_after_merge: str | None
    review_executed: Literal[True] = True
    human_authorization_verified: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


class HumanMergeBackend(Protocol):
    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]: ...
    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None: ...
    def get_commit(self, repository: str, commit_sha: str) -> Mapping[str, object]: ...
    def merge_pull_request(self, repository: str, pr_number: int, *, expected_head_sha: str, merge_method: Literal["merge"]) -> Mapping[str, object]: ...


ReviewExecutor = Callable[[ReviewRequest, GitHubReadBackend], ReviewReport]


def execute_human_merge(operation: HumanMergeOperation, *, review_backend: GitHubReadBackend, merge_backend: HumanMergeBackend, reviewer: ReviewExecutor = review_pr) -> HumanMergeResult:
    operation = HumanMergeOperation.model_validate(operation.model_dump(mode="python"))
    report = ReviewReport.model_validate(reviewer(operation.review_request, review_backend).model_dump(mode="python"))
    _validate_report_binding(operation.review_request, report)
    pr_url = f"https://github.com/{report.repository}/pull/{report.pr_number}"

    if report.decision is not ReviewDecision.APPROVE:
        return _result(report, operation.authorization, pr_url, HumanMergeDecision.REVIEW_NOT_APPROVED)
    if report.base_branch_head_sha is None:
        raise HumanMergeError("APPROVE report must contain current base branch HEAD evidence")
    _require_ci_merge_provenance_pass(report)
    _validate_authorization(operation.authorization, report)

    live_pr = merge_backend.get_pull_request(report.repository, report.pr_number)
    _validate_live_ready_state(live_pr)
    if not _live_refs_match_report(live_pr, report):
        return _result(report, operation.authorization, pr_url, HumanMergeDecision.NEEDS_BASE_REFRESH)
    if not _refs_match_report(merge_backend, report):
        return _result(report, operation.authorization, pr_url, HumanMergeDecision.NEEDS_BASE_REFRESH)

    # This is the final read of both refs before the sole permitted mutation.
    if not _refs_match_report(merge_backend, report):
        return _result(report, operation.authorization, pr_url, HumanMergeDecision.NEEDS_BASE_REFRESH)

    merge_payload = merge_backend.merge_pull_request(
        report.repository, report.pr_number,
        expected_head_sha=report.head_sha, merge_method=operation.merge_method,
    )
    if not _require_bool(merge_payload, "merged"):
        raise HumanMergeError("GitHub did not confirm the pull request merge")
    merge_sha = _require_str(merge_payload, "sha")
    _validate_merged_pr(merge_backend.get_pull_request(report.repository, report.pr_number), report)
    main_head = _branch_sha(merge_backend.get_branch(report.repository, report.base_branch), "base branch")
    if main_head != merge_sha:
        raise HumanMergeError("base branch HEAD does not match the confirmed merge commit")
    _validate_merge_commit_parents(
        merge_backend.get_commit(report.repository, merge_sha),
        expected_base_sha=report.base_branch_head_sha,
        expected_head_sha=report.head_sha,
    )
    return HumanMergeResult(
        repository=report.repository, pr_number=report.pr_number, pr_url=pr_url,
        base_branch=report.base_branch, base_sha=report.base_branch_head_sha,
        head_branch=report.head_branch, head_sha=report.head_sha,
        review_report=report, authorization=operation.authorization,
        decision=HumanMergeDecision.MERGED, merge_performed=True,
        merge_commit_sha=merge_sha, main_head_after_merge=main_head,
    )


def _require_ci_merge_provenance_pass(report: ReviewReport) -> None:
    matches = tuple(check for check in report.checks if check.check_id is ReviewCheckId.CI_003)
    if len(matches) != 1:
        raise HumanMergeError("APPROVE report must contain exactly one CI-003 merge-provenance check")
    check = matches[0]
    if not check.applicable or check.status is not ReviewCheckStatus.PASS or not check.evidence:
        raise HumanMergeError("APPROVE report must contain applicable CI-003 PASS evidence")


def _validate_report_binding(request: ReviewRequest, report: ReviewReport) -> None:
    if report.agent_id != "PR_REVIEW_AGENT_V1":
        raise HumanMergeError("review report must originate from PR_REVIEW_AGENT_V1")
    if (report.repository, report.pr_number) != (request.repository, request.pr_number):
        raise HumanMergeError("review report repository/PR binding does not match the request")
    if report.base_branch != request.expected_base_branch or report.objective != request.objective:
        raise HumanMergeError("review report does not match the request")


def _validate_authorization(authorization: HumanMergeAuthorization, report: ReviewReport) -> None:
    if (authorization.repository, authorization.pr_number) != (report.repository, report.pr_number):
        raise HumanMergeError("human authorization repository/PR does not match reviewed evidence")
    if authorization.base_sha != report.base_branch_head_sha:
        raise HumanMergeError("human authorization base SHA does not match reviewed live base HEAD")
    if authorization.head_sha != report.head_sha:
        raise HumanMergeError("human authorization head SHA does not match reviewed evidence")


def _validate_live_ready_state(payload: Mapping[str, object]) -> None:
    if _require_str(payload, "state") != "open": raise HumanMergeError("pull request must be open before merge")
    if _require_bool(payload, "draft"): raise HumanMergeError("pull request must be Ready for Review before merge")
    if _require_bool(payload, "merged"): raise HumanMergeError("pull request is already merged")


def _live_refs_match_report(payload: Mapping[str, object], report: ReviewReport) -> bool:
    base = _require_mapping(payload.get("base"), "base")
    head = _require_mapping(payload.get("head"), "head")
    return (_require_str(base, "ref") == report.base_branch and _require_str(base, "sha") == report.base_sha and _require_str(head, "ref") == report.head_branch and _require_str(head, "sha") == report.head_sha)


def _refs_match_report(backend: HumanMergeBackend, report: ReviewReport) -> bool:
    if report.base_branch_head_sha is None: return False
    base = _branch_sha(backend.get_branch(report.repository, report.base_branch), "base branch")
    head = _branch_sha(backend.get_branch(report.repository, report.head_branch), "head branch")
    return base == report.base_branch_head_sha and head == report.head_sha


def _validate_merged_pr(payload: Mapping[str, object], report: ReviewReport) -> None:
    if _require_str(payload, "state") != "closed" or not _require_bool(payload, "merged"):
        raise HumanMergeError("GitHub read-back did not confirm the merge")
    if _require_bool(payload, "draft"): raise HumanMergeError("merged pull request unexpectedly returned to Draft")
    base = _require_mapping(payload.get("base"), "base")
    head = _require_mapping(payload.get("head"), "head")
    if _require_str(base, "ref") != report.base_branch or _require_str(head, "ref") != report.head_branch or _require_str(head, "sha") != report.head_sha:
        raise HumanMergeError("merged pull request refs changed unexpectedly")


def _validate_merge_commit_parents(payload: Mapping[str, object], *, expected_base_sha: str, expected_head_sha: str) -> None:
    parents = payload.get("parents")
    if not isinstance(parents, list) or len(parents) != 2:
        raise HumanMergeError("merge commit must have exactly two parents")
    shas = tuple(_require_str(_require_mapping(item, "parent"), "sha") for item in parents)
    if shas != (expected_base_sha, expected_head_sha):
        raise HumanMergeError("merge commit parents do not match live base/reviewed head evidence")


def _result(report: ReviewReport, authorization: HumanMergeAuthorization, pr_url: str, decision: HumanMergeDecision) -> HumanMergeResult:
    base_sha = report.base_branch_head_sha or authorization.base_sha
    return HumanMergeResult(
        repository=report.repository, pr_number=report.pr_number, pr_url=pr_url,
        base_branch=report.base_branch, base_sha=base_sha,
        head_branch=report.head_branch, head_sha=report.head_sha,
        review_report=report, authorization=authorization, decision=decision,
        merge_performed=False, merge_commit_sha=None,
        main_head_after_merge=report.base_branch_head_sha,
    )


def _branch_sha(payload: Mapping[str, object] | None, label: str) -> str:
    if payload is None: raise HumanMergeError(f"{label} is unavailable")
    return _require_str(_require_mapping(payload.get("commit"), "commit"), "sha")


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping): raise HumanMergeError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value: raise HumanMergeError(f"GitHub field {key!r} must be a non-empty string")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool): raise HumanMergeError(f"GitHub field {key!r} must be a boolean")
    return value
