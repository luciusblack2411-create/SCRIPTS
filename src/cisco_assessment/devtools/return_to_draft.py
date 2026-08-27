"""Fail-closed control logic for one exact Ready-for-Review to Draft transition."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

CONTROL_PLANE_ID: Literal["CONTROLLED_RETURN_TO_DRAFT_V1"] = "CONTROLLED_RETURN_TO_DRAFT_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class ReturnToDraftError(RuntimeError):
    """Raised when an exact Return-to-Draft operation cannot proceed safely."""


class ReturnToDraftAuthorization(StrEnum):
    RETURN_TO_DRAFT = "RETURN_TO_DRAFT"


class ReturnToDraftDecision(StrEnum):
    RETURNED_TO_DRAFT = "RETURNED_TO_DRAFT"
    NEEDS_REF_REFRESH = "NEEDS_REF_REFRESH"


class FrozenReturnToDraftModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReturnToDraftOperation(FrozenReturnToDraftModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_RETURN_TO_DRAFT_V1"] = CONTROL_PLANE_ID
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    base_branch: str = Field(min_length=1)
    historical_pr_base_sha: str = Field(min_length=1)
    expected_live_base_sha: str = Field(min_length=1)
    head_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    authorization: ReturnToDraftAuthorization


class ReturnToDraftResult(FrozenReturnToDraftModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_RETURN_TO_DRAFT_V1"] = CONTROL_PLANE_ID
    repository: str
    pr_number: int
    base_branch: str
    historical_pr_base_sha: str
    expected_live_base_sha: str
    head_branch: str
    head_sha: str
    decision: ReturnToDraftDecision
    transition_performed: bool
    returned_to_draft: bool
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


class ReturnToDraftReadBackend(Protocol):
    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]: ...

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None: ...


class ReturnToDraftTransitionBackend(Protocol):
    def convert_pull_request_to_draft(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object]: ...


def execute_return_to_draft(
    operation: ReturnToDraftOperation,
    *,
    read_backend: ReturnToDraftReadBackend,
    transition_backend: ReturnToDraftTransitionBackend,
) -> ReturnToDraftResult:
    operation = ReturnToDraftOperation.model_validate(operation.model_dump(mode="python"))
    _validate_pr(read_backend.get_pull_request(operation.repository, operation.pr_number), operation, False)
    if not _refs_fresh(read_backend, operation):
        return _result(operation, ReturnToDraftDecision.NEEDS_REF_REFRESH, False, False)

    # This is the immediate pre-mutation freshness barrier.
    _validate_pr(read_backend.get_pull_request(operation.repository, operation.pr_number), operation, False)
    if not _refs_fresh(read_backend, operation):
        return _result(operation, ReturnToDraftDecision.NEEDS_REF_REFRESH, False, False)

    transition_backend.convert_pull_request_to_draft(operation.repository, operation.pr_number)
    _validate_pr(read_backend.get_pull_request(operation.repository, operation.pr_number), operation, True)
    if not _refs_fresh(read_backend, operation):
        raise ReturnToDraftError("live refs changed after Return-to-Draft transition")
    return _result(operation, ReturnToDraftDecision.RETURNED_TO_DRAFT, True, True)


def _validate_pr(
    payload: Mapping[str, object], operation: ReturnToDraftOperation, expected_draft: bool
) -> None:
    phase = "after" if expected_draft else "before"
    if _require_str(payload, "state") != "open":
        raise ReturnToDraftError(f"pull request must be open {phase} Return-to-Draft")
    if _require_bool(payload, "draft") is not expected_draft:
        expected = "Draft" if expected_draft else "Ready-for-Review"
        raise ReturnToDraftError(f"pull request must be {expected} {phase} transition")
    if _require_bool(payload, "merged") is not False:
        raise ReturnToDraftError("merged pull requests cannot enter Return-to-Draft")
    base = _require_mapping(payload, "base")
    head = _require_mapping(payload, "head")
    if (
        _require_str(base, "ref") != operation.base_branch
        or _require_str(base, "sha") != operation.historical_pr_base_sha
    ):
        raise ReturnToDraftError("pull request historical base binding does not match authorization")
    if (
        _require_str(head, "ref") != operation.head_branch
        or _require_str(head, "sha") != operation.head_sha
    ):
        raise ReturnToDraftError("pull request head binding does not match authorization")


def _refs_fresh(backend: ReturnToDraftReadBackend, operation: ReturnToDraftOperation) -> bool:
    base = _branch_sha(backend.get_branch(operation.repository, operation.base_branch), "base branch")
    head = _branch_sha(backend.get_branch(operation.repository, operation.head_branch), "head branch")
    return base == operation.expected_live_base_sha and head == operation.head_sha


def _branch_sha(payload: Mapping[str, object] | None, label: str) -> str:
    if payload is None:
        raise ReturnToDraftError(f"{label} is unavailable")
    return _require_str(_require_mapping(payload, "commit"), "sha")


def _result(
    operation: ReturnToDraftOperation,
    decision: ReturnToDraftDecision,
    transition_performed: bool,
    returned_to_draft: bool,
) -> ReturnToDraftResult:
    return ReturnToDraftResult(
        repository=operation.repository,
        pr_number=operation.pr_number,
        base_branch=operation.base_branch,
        historical_pr_base_sha=operation.historical_pr_base_sha,
        expected_live_base_sha=operation.expected_live_base_sha,
        head_branch=operation.head_branch,
        head_sha=operation.head_sha,
        decision=decision,
        transition_performed=transition_performed,
        returned_to_draft=returned_to_draft,
    )


def _require_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ReturnToDraftError(f"GitHub field {key!r} must be an object")
    return cast(Mapping[str, object], value)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ReturnToDraftError(f"GitHub field {key!r} must be a non-empty string")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ReturnToDraftError(f"GitHub field {key!r} must be a boolean")
    return value
