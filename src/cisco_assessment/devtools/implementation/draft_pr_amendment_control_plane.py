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

AMENDMENT_TOKEN_ENV: Literal["CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"] = "CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"


class ImplementationDraftPrAmendmentControlPlaneError(RuntimeError):
    pass


class ImplementationDraftPrAmendmentOperation(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    request: ImplementationDraftPrAmendmentRequest


class ImplementationDraftPrAmendmentControlPlaneResult(FrozenImplementationModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    credential_source: Literal["CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"] = AMENDMENT_TOKEN_ENV
    amendment: ImplementationDraftPrAmendmentResult


def resolve_amendment_token(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    token = source.get(AMENDMENT_TOKEN_ENV)
    if token is None or not token.strip():
        raise ImplementationDraftPrAmendmentControlPlaneError(f"{AMENDMENT_TOKEN_ENV} is required; GITHUB_TOKEN and GH_TOKEN are forbidden fallbacks")
    return token


def load_amendment_operation(path: Path) -> ImplementationDraftPrAmendmentOperation:
    try:
        return ImplementationDraftPrAmendmentOperation.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ImplementationDraftPrAmendmentControlPlaneError(f"invalid amendment operation {path}: {exc}") from exc


def execute_amendment_control_plane(operation: ImplementationDraftPrAmendmentOperation, *, environ: Mapping[str, str] | None = None, backend_factory: Callable[[str], ImplementationDraftPrAmendmentBackend] = lambda token: GitHubImplementationDraftPrAmendmentBackend(token=token)) -> ImplementationDraftPrAmendmentControlPlaneResult:
    operation = ImplementationDraftPrAmendmentOperation.model_validate(operation.model_dump(mode="python"))
    backend = backend_factory(resolve_amendment_token(environ))
    return ImplementationDraftPrAmendmentControlPlaneResult(amendment=execute_draft_pr_amendment(operation.request, backend))
