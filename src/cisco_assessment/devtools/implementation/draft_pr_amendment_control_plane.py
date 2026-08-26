"""Least-privilege control plane for controlled Draft PR amendments."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from .draft_pr_amendment import (
    ImplementationDraftPrAmendmentBackend,
    ImplementationDraftPrAmendmentRequest,
    ImplementationDraftPrAmendmentResult,
    execute_draft_pr_amendment,
)
from .github_draft_pr_amendment import GitHubImplementationDraftPrAmendmentBackend
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel

AMENDMENT_TOKEN_ENV: Literal["CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"] = (
    "CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"
)


class ImplementationDraftPrAmendmentControlPlaneError(RuntimeError):
    """Raised when the dedicated Amendment control plane cannot proceed."""


class ImplementationDraftPrAmendmentOperation(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    request: ImplementationDraftPrAmendmentRequest
    timeout_seconds: float = 900.0
    poll_interval_seconds: float = 5.0


class ImplementationDraftPrAmendmentControlPlaneResult(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    credential_source: Literal["CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"] = AMENDMENT_TOKEN_ENV
    amendment: ImplementationDraftPrAmendmentResult
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


def resolve_amendment_token(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    token = source.get(AMENDMENT_TOKEN_ENV)
    if token is None or not token.strip():
        raise ImplementationDraftPrAmendmentControlPlaneError(
            f"{AMENDMENT_TOKEN_ENV} is required; GITHUB_TOKEN and GH_TOKEN are forbidden fallbacks"
        )
    return token


def load_amendment_operation(path: Path) -> ImplementationDraftPrAmendmentOperation:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ImplementationDraftPrAmendmentControlPlaneError(
            f"cannot read amendment operation {path}: {exc}"
        ) from exc
    try:
        return ImplementationDraftPrAmendmentOperation.model_validate_json(content)
    except ValidationError as exc:
        raise ImplementationDraftPrAmendmentControlPlaneError(
            f"invalid amendment operation {path}: {exc}"
        ) from exc


def _default_backend_factory(token: str) -> ImplementationDraftPrAmendmentBackend:
    return GitHubImplementationDraftPrAmendmentBackend(token=token)


def execute_amendment_control_plane(
    operation: ImplementationDraftPrAmendmentOperation,
    *,
    environ: Mapping[str, str] | None = None,
    backend_factory: Callable[[str], ImplementationDraftPrAmendmentBackend] = _default_backend_factory,
) -> ImplementationDraftPrAmendmentControlPlaneResult:
    operation = ImplementationDraftPrAmendmentOperation.model_validate(
        operation.model_dump(mode="python")
    )
    token = resolve_amendment_token(environ)
    backend = backend_factory(token)
    amendment = execute_draft_pr_amendment(
        operation.request,
        backend,
        timeout_seconds=operation.timeout_seconds,
        poll_interval_seconds=operation.poll_interval_seconds,
    )
    return ImplementationDraftPrAmendmentControlPlaneResult(amendment=amendment)
