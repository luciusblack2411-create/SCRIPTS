"""Human-facing execution surface for exact controlled merge authorization."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .human_merge_gate import HumanMergeAuthorization, HumanMergeOperation
from .pr_review.models import ReviewRequest

EXECUTION_SURFACE_ID: Literal["HUMAN_MERGE_EXECUTION_V1"] = "HUMAN_MERGE_EXECUTION_V1"
SCHEMA_VERSION: Literal["1.0"] = "1.0"


class HumanMergeExecutionError(RuntimeError):
    """Raised when an interactive human-merge operation cannot be prepared safely."""


class HumanMergeReviewRequestFileError(HumanMergeExecutionError):
    """Raised when a strict review-request file cannot be loaded."""


class HumanMergeChallengeBackend(Protocol):
    """Minimal read-only GitHub surface needed before asking for authorization."""

    def get_pull_request(self, repository: str, pr_number: int) -> Mapping[str, object]:
        """Read current pull-request state and refs."""
        ...

    def get_branch(self, repository: str, branch: str) -> Mapping[str, object] | None:
        """Read one current branch ref."""
        ...


class FrozenExecutionModel(BaseModel):
    """Strict immutable base model for execution-surface contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HumanMergeAuthorizationChallenge(FrozenExecutionModel):
    """Exact live refs shown to the human before accepting MERGE_APPROVED."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    execution_surface_id: Literal["HUMAN_MERGE_EXECUTION_V1"] = EXECUTION_SURFACE_ID
    review_request: ReviewRequest
    repository: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    pr_url: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    head_branch: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    cisco_execution_allowed: Literal[False] = False


def load_human_merge_review_request(path: Path) -> ReviewRequest:
    """Load one strict ReviewRequest without inferring scope or authorization."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HumanMergeReviewRequestFileError(
            f"cannot read human merge review request {path}: {exc}"
        ) from exc
    try:
        return ReviewRequest.model_validate_json(content)
    except ValidationError as exc:
        raise HumanMergeReviewRequestFileError(
            f"invalid human merge review request {path}: {exc}"
        ) from exc


def prepare_human_merge_authorization_challenge(
    review_request: ReviewRequest,
    backend: HumanMergeChallengeBackend,
) -> HumanMergeAuthorizationChallenge:
    """Read exact live PR refs and fail closed before requesting human authorization."""
    request = ReviewRequest.model_validate(review_request.model_dump(mode="python"))
    pull_request = backend.get_pull_request(request.repository, request.pr_number)

    observed_pr_number = _require_int(pull_request, "number")
    if observed_pr_number != request.pr_number:
        raise HumanMergeExecutionError(
            f"pull-request number mismatch: requested {request.pr_number}, got {observed_pr_number}"
        )
    if _require_str(pull_request, "state") != "open":
        raise HumanMergeExecutionError("pull request must be open before authorization")
    if _require_bool(pull_request, "draft") is not False:
        raise HumanMergeExecutionError("pull request must be Ready for Review before authorization")
    if _require_bool(pull_request, "merged") is not False:
        raise HumanMergeExecutionError("pull request is already merged")

    base = _require_mapping(pull_request.get("base"), "base")
    head = _require_mapping(pull_request.get("head"), "head")
    base_branch = _require_str(base, "ref")
    head_branch = _require_str(head, "ref")
    head_sha = _require_str(head, "sha")

    if base_branch != request.expected_base_branch:
        raise HumanMergeExecutionError(
            "pull request base branch does not match the ReviewRequest expected base branch"
        )

    live_base_sha = _branch_sha(
        backend.get_branch(request.repository, base_branch),
        "base branch",
    )

    live_head_sha = _branch_sha(
        backend.get_branch(request.repository, head_branch),
        "head branch",
    )
    if live_head_sha != head_sha:
        raise HumanMergeExecutionError(
            "current head branch HEAD does not match the pull-request head SHA"
        )

    return HumanMergeAuthorizationChallenge(
        review_request=request,
        repository=request.repository,
        pr_number=request.pr_number,
        pr_url=f"https://github.com/{request.repository}/pull/{request.pr_number}",
        base_branch=base_branch,
        base_sha=live_base_sha,
        head_branch=head_branch,
        head_sha=head_sha,
    )


def build_human_merge_operation_from_challenge(
    challenge: HumanMergeAuthorizationChallenge,
    *,
    decision: str,
    authorized_by: str,
    rationale: str,
) -> HumanMergeOperation:
    """Convert one exact displayed challenge into the existing protected operation contract."""
    challenge = HumanMergeAuthorizationChallenge.model_validate(
        challenge.model_dump(mode="python")
    )
    if decision != "MERGE_APPROVED":
        raise HumanMergeExecutionError(
            "human authorization requires the exact decision MERGE_APPROVED"
        )
    authorization = HumanMergeAuthorization(
        decision="MERGE_APPROVED",
        repository=challenge.repository,
        pr_number=challenge.pr_number,
        base_sha=challenge.base_sha,
        head_sha=challenge.head_sha,
        authorized_by=authorized_by,
        rationale=rationale,
    )
    return HumanMergeOperation(
        review_request=challenge.review_request,
        authorization=authorization,
        merge_method="merge",
    )


def render_human_merge_authorization_challenge(
    challenge: HumanMergeAuthorizationChallenge,
) -> str:
    """Render the exact refs the human is authorizing without credential material."""
    return "\n".join(
        (
            "Human Merge Authorization Challenge",
            f"PR: #{challenge.pr_number} {challenge.pr_url}",
            f"Base: {challenge.base_branch}@{challenge.base_sha}",
            f"Head: {challenge.head_branch}@{challenge.head_sha}",
            "Cisco execution allowed: false",
            "Type MERGE_APPROVED only if you authorize this exact repository/PR/base/head.",
        )
    )


def _branch_sha(payload: Mapping[str, object] | None, label: str) -> str:
    if payload is None:
        raise HumanMergeExecutionError(f"{label} is unavailable")
    commit = _require_mapping(payload.get("commit"), "commit")
    return _require_str(commit, "sha")


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise HumanMergeExecutionError(f"GitHub {label} payload must be an object")
    return cast(Mapping[str, object], value)


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HumanMergeExecutionError(f"GitHub field {key!r} must be a non-empty string")
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HumanMergeExecutionError(f"GitHub field {key!r} must be an integer")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HumanMergeExecutionError(f"GitHub field {key!r} must be a boolean")
    return value
