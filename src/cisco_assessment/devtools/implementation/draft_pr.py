"""Controlled Draft PR preparation for Implementation Agent v0.1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import Field, model_validator

from .ci_validation import ImplementationCiStatus, ImplementationOperationalDecision
from .enums import ImplementationAuthorization
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .operational import ImplementationOperationalResult

WORK_BRANCH_PREFIX = "agent/implementation/"


class ImplementationDraftPrError(RuntimeError):
    """Raised when a validated work branch cannot safely become a Draft PR."""


class ImplementationDraftPrDecision(StrEnum):
    """Next-step decision after controlled Draft PR creation."""

    DRAFT_PR_CREATED = "DRAFT_PR_CREATED"
    NEEDS_BASE_REFRESH = "NEEDS_BASE_REFRESH"


class ImplementationDraftPrBackend(Protocol):
    """Minimal repository surface needed to create and verify one Draft PR."""

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Observe one branch without mutation."""
        ...

    def list_open_pull_requests(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> Sequence[Mapping[str, object]]:
        """Observe existing open PRs for the exact base/head pair."""
        ...

    def create_draft_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
    ) -> Mapping[str, object]:
        """Create exactly one Draft PR and return its metadata."""
        ...

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        """Read back one PR for post-create verification."""
        ...


class ImplementationDraftPrRequest(FrozenImplementationModel):
    """Explicit human authorization to promote validated work-branch evidence to a Draft PR."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str
    authorization: ImplementationAuthorization
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_request_contract(self) -> ImplementationDraftPrRequest:
        if self.authorization is not ImplementationAuthorization.DRAFT_PR:
            raise ValueError("Draft PR preparation requires DRAFT_PR authorization exactly")
        if not self.work_branch.startswith(WORK_BRANCH_PREFIX):
            raise ValueError("Draft PR work branch must use agent/implementation/ namespace")
        if self.work_branch == self.base_branch:
            raise ValueError("Draft PR work branch must differ from base branch")
        if not self.title.strip():
            raise ValueError("Draft PR title must not be blank")
        return self


class ImplementationDraftPrResult(FrozenImplementationModel):
    """Canonical evidence for one created Draft PR and its post-create base freshness."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    repository: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    work_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    pr_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    state: Literal["open"] = "open"
    draft: Literal[True] = True
    base_head_after_create: str = Field(min_length=1)
    base_fresh_after_create: bool
    decision: ImplementationDraftPrDecision
    pull_request_created: Literal[True] = True
    pull_request_ready_for_review: Literal[False] = False
    review_executed: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_result_contract(self) -> ImplementationDraftPrResult:
        expected_fresh = self.base_head_after_create == self.base_sha
        if self.base_fresh_after_create is not expected_fresh:
            raise ValueError("base_fresh_after_create must match observed base head evidence")
        expected_decision = (
            ImplementationDraftPrDecision.DRAFT_PR_CREATED
            if self.base_fresh_after_create
            else ImplementationDraftPrDecision.NEEDS_BASE_REFRESH
        )
        if self.decision is not expected_decision:
            raise ValueError("Draft PR decision must reflect post-create base freshness")
        return self


def prepare_implementation_draft_pr(
    operational_result: ImplementationOperationalResult,
    request: ImplementationDraftPrRequest,
    backend: ImplementationDraftPrBackend,
) -> ImplementationDraftPrResult:
    """Create one Draft PR from exact successful operational evidence and stop."""
    operational_result = ImplementationOperationalResult.model_validate(
        operational_result.model_dump(mode="python")
    )
    request = ImplementationDraftPrRequest.model_validate(request.model_dump(mode="python"))
    _validate_operational_evidence(operational_result, request)

    _require_branch_sha(
        backend.get_branch(request.repository, request.base_branch),
        request.base_branch,
        request.base_sha,
    )
    _require_branch_sha(
        backend.get_branch(request.repository, request.work_branch),
        request.work_branch,
        request.commit_sha,
    )
    existing = tuple(
        backend.list_open_pull_requests(
            request.repository,
            base_branch=request.base_branch,
            head_branch=request.work_branch,
        )
    )
    if existing:
        raise ImplementationDraftPrError(
            "an open pull request already exists for the exact implementation base/head pair"
        )

    # Close the pre-create race as far as the API permits. If main moves after this
    # observation, the created PR remains draft and post-create evidence records drift.
    _require_branch_sha(
        backend.get_branch(request.repository, request.base_branch),
        request.base_branch,
        request.base_sha,
    )
    _require_branch_sha(
        backend.get_branch(request.repository, request.work_branch),
        request.work_branch,
        request.commit_sha,
    )

    created = backend.create_draft_pull_request(
        request.repository,
        title=request.title,
        body=request.body,
        base_branch=request.base_branch,
        head_branch=request.work_branch,
    )
    pr_number = _required_int(created, "number", "created pull request")
    observed = backend.get_pull_request(request.repository, pr_number)
    _validate_created_pull_request(observed, request, pr_number)

    base_after = _observed_branch_sha(
        backend.get_branch(request.repository, request.base_branch), request.base_branch
    )
    base_fresh = base_after == request.base_sha
    return ImplementationDraftPrResult(
        repository=request.repository,
        objective=request.objective,
        base_branch=request.base_branch,
        base_sha=request.base_sha,
        work_branch=request.work_branch,
        commit_sha=request.commit_sha,
        pr_number=pr_number,
        pr_url=_required_string(observed, "html_url", "pull request"),
        title=request.title,
        base_head_after_create=base_after,
        base_fresh_after_create=base_fresh,
        decision=(
            ImplementationDraftPrDecision.DRAFT_PR_CREATED
            if base_fresh
            else ImplementationDraftPrDecision.NEEDS_BASE_REFRESH
        ),
    )


def _validate_operational_evidence(
    result: ImplementationOperationalResult,
    request: ImplementationDraftPrRequest,
) -> None:
    if result.decision is not ImplementationOperationalDecision.READY_FOR_DRAFT_PR:
        raise ImplementationDraftPrError("operational result is not READY_FOR_DRAFT_PR")
    if result.ci_validation.ci_status is not ImplementationCiStatus.PASSED:
        raise ImplementationDraftPrError("Draft PR preparation requires PASSED CI evidence")
    if not result.mutation.base_fresh_after_publish or not result.ci_validation.base_fresh_after_ci:
        raise ImplementationDraftPrError("Draft PR preparation requires fresh base evidence")
    if (
        request.repository != result.repository
        or request.repository != result.mutation.repository
        or request.objective != result.objective
        or request.base_branch != result.mutation.base_branch
        or request.base_sha != result.mutation.base_sha
        or request.work_branch != result.mutation.work_branch
        or request.commit_sha != result.mutation.commit_sha
    ):
        raise ImplementationDraftPrError(
            "Draft PR authorization does not bind to the exact operational result"
        )


def _validate_created_pull_request(
    payload: Mapping[str, object],
    request: ImplementationDraftPrRequest,
    pr_number: int,
) -> None:
    if _required_int(payload, "number", "pull request") != pr_number:
        raise ImplementationDraftPrError("created pull request identity changed during read-back")
    if payload.get("state") != "open" or payload.get("draft") is not True:
        raise ImplementationDraftPrError("created pull request must remain open and draft")
    if _required_string(payload, "title", "pull request") != request.title:
        raise ImplementationDraftPrError("created pull request title does not match authorization")
    if payload.get("body") != request.body:
        raise ImplementationDraftPrError("created pull request body does not match authorization")
    base = _required_mapping(payload, "base", "pull request")
    head = _required_mapping(payload, "head", "pull request")
    if _required_string(base, "ref", "pull request base") != request.base_branch:
        raise ImplementationDraftPrError("created pull request base branch is inconsistent")
    if _required_string(head, "ref", "pull request head") != request.work_branch:
        raise ImplementationDraftPrError("created pull request head branch is inconsistent")
    if _required_string(head, "sha", "pull request head") != request.commit_sha:
        raise ImplementationDraftPrError("created pull request head SHA is inconsistent")


def _require_branch_sha(
    branch: Mapping[str, object] | None,
    branch_name: str,
    expected_sha: str,
) -> None:
    observed = _observed_branch_sha(branch, branch_name)
    if observed != expected_sha:
        raise ImplementationDraftPrError(
            f"branch {branch_name!r} moved: expected {expected_sha}, observed {observed}"
        )


def _observed_branch_sha(branch: Mapping[str, object] | None, branch_name: str) -> str:
    if branch is None:
        raise ImplementationDraftPrError(f"cannot observe branch {branch_name!r}")
    commit = _required_mapping(branch, "commit", f"branch {branch_name!r}")
    return _required_string(commit, "sha", f"branch {branch_name!r} commit")


def _required_mapping(
    payload: Mapping[str, object], key: str, context: str
) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ImplementationDraftPrError(f"{context} has no valid {key}")
    return cast(Mapping[str, object], value)


def _required_string(payload: Mapping[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ImplementationDraftPrError(f"{context} has no valid {key}")
    return value


def _required_int(payload: Mapping[str, object], key: str, context: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ImplementationDraftPrError(f"{context} has no valid {key}")
    return value
