"""Separate control plane for PR review handoff and Ready-for-Review transition."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .github_ready_for_review import GitHubReadyForReviewBackend
from .pr_review.github import GitHubReadBackend
from .pr_review.github_rest import GitHubRestReadBackend, UrllibGitHubTransport
from .ready_for_review import (
    CONTROL_PLANE_ID,
    SCHEMA_VERSION,
    ReadyForReviewBackend,
    ReadyForReviewOperation,
    ReadyForReviewResult,
    execute_ready_for_review,
)

PR_REVIEW_TOKEN_ENV: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = (
    "CISCO_ASSESSMENT_PR_REVIEW_TOKEN"
)
READY_FOR_REVIEW_TOKEN_ENV: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = (
    "CISCO_ASSESSMENT_DRAFT_PR_TOKEN"
)


class ReadyForReviewControlPlaneError(RuntimeError):
    """Raised when the review handoff control plane cannot execute safely."""


class ReadyForReviewControlPlaneFileError(ReadyForReviewControlPlaneError):
    """Raised when a strict Ready-for-Review operation file cannot be loaded."""


class FrozenControlPlaneModel(BaseModel):
    """Strict immutable base model for control-plane outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReadyForReviewControlPlaneResult(FrozenControlPlaneModel):
    """Canonical output recording credential sources without credential values."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_READY_FOR_REVIEW_V1"] = CONTROL_PLANE_ID
    review_credential_source: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = PR_REVIEW_TOKEN_ENV
    transition_credential_source: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = (
        READY_FOR_REVIEW_TOKEN_ENV
    )
    ready_for_review: ReadyForReviewResult


ReviewBackendFactory = Callable[[str], GitHubReadBackend]
TransitionBackendFactory = Callable[[str], ReadyForReviewBackend]


def resolve_ready_for_review_tokens(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve only explicit review/read and transition/write control-plane credentials."""
    source = os.environ if environ is None else environ
    review_token = source.get(PR_REVIEW_TOKEN_ENV)
    transition_token = source.get(READY_FOR_REVIEW_TOKEN_ENV)
    if review_token is None or not review_token.strip():
        raise ReadyForReviewControlPlaneError(
            f"{PR_REVIEW_TOKEN_ENV} is required for the read-only PR Review Agent; "
            "GITHUB_TOKEN and GH_TOKEN are intentionally not accepted as fallbacks"
        )
    if transition_token is None or not transition_token.strip():
        raise ReadyForReviewControlPlaneError(
            f"{READY_FOR_REVIEW_TOKEN_ENV} is required for the controlled transition; "
            "GITHUB_TOKEN and GH_TOKEN are intentionally not accepted as fallbacks"
        )
    if review_token == transition_token:
        raise ReadyForReviewControlPlaneError(
            "review/read credential and Ready-for-Review write credential must be distinct"
        )
    return review_token, transition_token


def load_ready_for_review_operation(path: Path) -> ReadyForReviewOperation:
    """Load one strict JSON operation without inferring scope or authorization."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReadyForReviewControlPlaneFileError(
            f"cannot read Ready-for-Review operation {path}: {exc}"
        ) from exc
    try:
        return ReadyForReviewOperation.model_validate_json(content)
    except ValidationError as exc:
        raise ReadyForReviewControlPlaneFileError(
            f"invalid Ready-for-Review operation {path}: {exc}"
        ) from exc


def _default_review_backend_factory(token: str) -> GitHubReadBackend:
    return GitHubRestReadBackend(UrllibGitHubTransport(token=token))


def _default_transition_backend_factory(token: str) -> ReadyForReviewBackend:
    return GitHubReadyForReviewBackend(token=token)


def execute_ready_for_review_control_plane(
    operation: ReadyForReviewOperation,
    *,
    environ: Mapping[str, str] | None = None,
    review_backend_factory: ReviewBackendFactory = _default_review_backend_factory,
    transition_backend_factory: TransitionBackendFactory = _default_transition_backend_factory,
) -> ReadyForReviewControlPlaneResult:
    """Run independent review, transition only on APPROVE, and stop before merge."""
    operation = ReadyForReviewOperation.model_validate(operation.model_dump(mode="python"))
    review_token, transition_token = resolve_ready_for_review_tokens(environ)
    result = execute_ready_for_review(
        operation,
        review_backend=review_backend_factory(review_token),
        transition_backend=transition_backend_factory(transition_token),
    )
    return ReadyForReviewControlPlaneResult(ready_for_review=result)


def render_ready_for_review_control_plane_json(
    result: ReadyForReviewControlPlaneResult,
) -> str:
    """Render canonical JSON without credential material."""
    return result.model_dump_json(indent=2)


def render_ready_for_review_control_plane_human(
    result: ReadyForReviewControlPlaneResult,
) -> str:
    """Render a compact human summary without credential material."""
    ready = result.ready_for_review
    return "\n".join(
        (
            f"Decision: {ready.decision.value}",
            f"PR: #{ready.pr_number} {ready.pr_url}",
            f"Review decision: {ready.review_report.decision.value}",
            f"Base: {ready.base_branch}@{ready.base_sha}",
            f"Head: {ready.head_branch}@{ready.head_sha}",
            f"Review credential source: {result.review_credential_source}",
            f"Transition credential source: {result.transition_credential_source}",
            f"Base fresh after transition: {ready.base_fresh_after_transition}",
            f"Ready for Review: {str(ready.ready_for_review).lower()}",
            "Review executed: true",
            "Merge performed: false",
            "Human merge gate required: true",
            "Cisco execution allowed: false",
        )
    )
