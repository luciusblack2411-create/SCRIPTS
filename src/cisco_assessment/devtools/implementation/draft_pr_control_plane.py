"""Separate least-privilege control plane for Implementation Agent Draft PR creation."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .draft_pr import (
    ImplementationDraftPrBackend,
    ImplementationDraftPrRequest,
    ImplementationDraftPrResult,
    prepare_implementation_draft_pr,
)
from .github_draft_pr import GitHubImplementationDraftPrBackend
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel
from .operational import ImplementationOperationalResult

DRAFT_PR_CONTROL_PLANE_TOKEN_ENV: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = (
    "CISCO_ASSESSMENT_DRAFT_PR_TOKEN"
)


class ImplementationDraftPrControlPlaneError(RuntimeError):
    """Raised when the dedicated Draft PR control plane cannot execute safely."""


class ImplementationDraftPrControlPlaneFileError(ImplementationDraftPrControlPlaneError):
    """Raised when a strict control-plane operation file cannot be loaded."""


class ImplementationDraftPrControlPlaneOperation(FrozenImplementationModel):
    """Strict input binding exact operational evidence to explicit Draft PR authorization."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    operational_result: ImplementationOperationalResult
    request: ImplementationDraftPrRequest


class ImplementationDraftPrControlPlaneResult(FrozenImplementationModel):
    """Canonical output that records credential source without exposing credential material."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    credential_source: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = (
        DRAFT_PR_CONTROL_PLANE_TOKEN_ENV
    )
    draft_pr: ImplementationDraftPrResult


def resolve_draft_pr_control_plane_token(
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve only the dedicated control-plane token; never fall back to runner credentials."""
    source = os.environ if environ is None else environ
    token = source.get(DRAFT_PR_CONTROL_PLANE_TOKEN_ENV)
    if token is None or not token.strip():
        raise ImplementationDraftPrControlPlaneError(
            f"{DRAFT_PR_CONTROL_PLANE_TOKEN_ENV} is required; "
            "GITHUB_TOKEN and GH_TOKEN are intentionally not accepted as fallbacks"
        )
    return token


def load_draft_pr_control_plane_operation(
    path: Path,
) -> ImplementationDraftPrControlPlaneOperation:
    """Load one strict JSON control-plane operation from disk."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ImplementationDraftPrControlPlaneFileError(
            f"cannot read Draft PR control-plane operation {path}: {exc}"
        ) from exc
    try:
        return ImplementationDraftPrControlPlaneOperation.model_validate_json(content)
    except ValidationError as exc:
        raise ImplementationDraftPrControlPlaneFileError(
            f"invalid Draft PR control-plane operation {path}: {exc}"
        ) from exc


def _default_backend_factory(token: str) -> ImplementationDraftPrBackend:
    return GitHubImplementationDraftPrBackend(token=token)


def execute_draft_pr_control_plane(
    operation: ImplementationDraftPrControlPlaneOperation,
    *,
    environ: Mapping[str, str] | None = None,
    backend_factory: Callable[[str], ImplementationDraftPrBackend] = _default_backend_factory,
) -> ImplementationDraftPrControlPlaneResult:
    """Create one verified Draft PR with a dedicated credential and stop before review or merge."""
    operation = ImplementationDraftPrControlPlaneOperation.model_validate(
        operation.model_dump(mode="python")
    )
    token = resolve_draft_pr_control_plane_token(environ)
    backend = backend_factory(token)
    draft_pr = prepare_implementation_draft_pr(
        operation.operational_result,
        operation.request,
        backend,
    )
    return ImplementationDraftPrControlPlaneResult(draft_pr=draft_pr)


def render_draft_pr_control_plane_result_json(
    result: ImplementationDraftPrControlPlaneResult,
) -> str:
    """Render canonical JSON without credential material."""
    return result.model_dump_json(indent=2)


def render_draft_pr_control_plane_result_human(
    result: ImplementationDraftPrControlPlaneResult,
) -> str:
    """Render a compact human summary without credential material."""
    draft_pr = result.draft_pr
    return "\n".join(
        (
            f"Decision: {draft_pr.decision.value}",
            f"Draft PR: #{draft_pr.pr_number} {draft_pr.pr_url}",
            f"Base: {draft_pr.base_branch}@{draft_pr.base_sha}",
            f"Head: {draft_pr.work_branch}@{draft_pr.commit_sha}",
            f"Credential source: {result.credential_source}",
            f"Base fresh after create: {draft_pr.base_fresh_after_create}",
            "Ready for Review: false",
            "Review executed: false",
            "Merge performed: false",
            "Human merge gate required: true",
            "Cisco execution allowed: false",
        )
    )
