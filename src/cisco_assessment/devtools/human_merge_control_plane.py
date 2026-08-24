"""Separate control plane for explicit human-authorized merges."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .github_human_merge import GitHubHumanMergeBackend
from .human_merge_gate import (
    CONTROL_PLANE_ID,
    SCHEMA_VERSION,
    HumanMergeBackend,
    HumanMergeOperation,
    HumanMergeResult,
    execute_human_merge,
)
from .pr_review.github import GitHubReadBackend
from .pr_review.github_rest import GitHubRestReadBackend, UrllibGitHubTransport

PR_REVIEW_TOKEN_ENV: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = (
    "CISCO_ASSESSMENT_PR_REVIEW_TOKEN"
)
HUMAN_MERGE_TOKEN_ENV: Literal["CISCO_ASSESSMENT_HUMAN_MERGE_TOKEN"] = (
    "CISCO_ASSESSMENT_HUMAN_MERGE_TOKEN"
)


class HumanMergeControlPlaneError(RuntimeError):
    """Raised when the human merge control plane cannot execute safely."""


class HumanMergeControlPlaneFileError(HumanMergeControlPlaneError):
    """Raised when a strict human merge operation file cannot be loaded."""


class FrozenControlPlaneModel(BaseModel):
    """Strict immutable base model for human merge control-plane outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class HumanMergeControlPlaneResult(FrozenControlPlaneModel):
    """Canonical output recording credential sources without credential values."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_HUMAN_MERGE_V1"] = CONTROL_PLANE_ID
    review_credential_source: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = PR_REVIEW_TOKEN_ENV
    merge_credential_source: Literal["CISCO_ASSESSMENT_HUMAN_MERGE_TOKEN"] = (
        HUMAN_MERGE_TOKEN_ENV
    )
    human_merge: HumanMergeResult


ReviewBackendFactory = Callable[[str], GitHubReadBackend]
MergeBackendFactory = Callable[[str], HumanMergeBackend]


def resolve_human_merge_tokens(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve only explicit read-only review and dedicated merge credentials."""
    source = os.environ if environ is None else environ
    review_token = source.get(PR_REVIEW_TOKEN_ENV)
    merge_token = source.get(HUMAN_MERGE_TOKEN_ENV)
    if review_token is None or not review_token.strip():
        raise HumanMergeControlPlaneError(
            f"{PR_REVIEW_TOKEN_ENV} is required for the read-only PR Review Agent; "
            "GITHUB_TOKEN and GH_TOKEN are intentionally not accepted as fallbacks"
        )
    if merge_token is None or not merge_token.strip():
        raise HumanMergeControlPlaneError(
            f"{HUMAN_MERGE_TOKEN_ENV} is required for the explicit human merge; "
            "GITHUB_TOKEN and GH_TOKEN are intentionally not accepted as fallbacks"
        )
    if review_token == merge_token:
        raise HumanMergeControlPlaneError(
            "review/read credential and human-merge credential must be distinct"
        )
    return review_token, merge_token


def load_human_merge_operation(path: Path) -> HumanMergeOperation:
    """Load one strict JSON operation without inferring human authorization."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HumanMergeControlPlaneFileError(
            f"cannot read human merge operation {path}: {exc}"
        ) from exc
    try:
        return HumanMergeOperation.model_validate_json(content)
    except ValidationError as exc:
        raise HumanMergeControlPlaneFileError(
            f"invalid human merge operation {path}: {exc}"
        ) from exc


def _default_review_backend_factory(token: str) -> GitHubReadBackend:
    return GitHubRestReadBackend(UrllibGitHubTransport(token=token))


def _default_merge_backend_factory(token: str) -> HumanMergeBackend:
    return GitHubHumanMergeBackend(token=token)


def execute_human_merge_control_plane(
    operation: HumanMergeOperation,
    *,
    environ: Mapping[str, str] | None = None,
    review_backend_factory: ReviewBackendFactory = _default_review_backend_factory,
    merge_backend_factory: MergeBackendFactory = _default_merge_backend_factory,
) -> HumanMergeControlPlaneResult:
    """Run fresh review, verify explicit authorization, merge once, and stop."""
    operation = HumanMergeOperation.model_validate(operation.model_dump(mode="python"))
    review_token, merge_token = resolve_human_merge_tokens(environ)
    result = execute_human_merge(
        operation,
        review_backend=review_backend_factory(review_token),
        merge_backend=merge_backend_factory(merge_token),
    )
    return HumanMergeControlPlaneResult(human_merge=result)


def render_human_merge_control_plane_json(result: HumanMergeControlPlaneResult) -> str:
    """Render canonical JSON without credential material."""
    return result.model_dump_json(indent=2)


def render_human_merge_control_plane_human(result: HumanMergeControlPlaneResult) -> str:
    """Render a compact human summary without credential material."""
    merge = result.human_merge
    return "\n".join(
        (
            f"Decision: {merge.decision.value}",
            f"PR: #{merge.pr_number} {merge.pr_url}",
            f"Review decision: {merge.review_report.decision.value}",
            f"Authorized by: {merge.authorization.authorized_by}",
            f"Base: {merge.base_branch}@{merge.base_sha}",
            f"Head: {merge.head_branch}@{merge.head_sha}",
            f"Merge commit: {merge.merge_commit_sha or 'none'}",
            f"Main after merge: {merge.main_head_after_merge or 'unknown'}",
            f"Review credential source: {result.review_credential_source}",
            f"Merge credential source: {result.merge_credential_source}",
            f"Merge performed: {str(merge.merge_performed).lower()}",
            "Review executed: true",
            "Human authorization verified: true",
            "Cisco execution allowed: false",
        )
    )
