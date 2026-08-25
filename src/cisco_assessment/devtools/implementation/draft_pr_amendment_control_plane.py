"""Least-privilege control plane for exact Draft PR amendment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from .draft_pr_amendment import (
    ImplementationDraftPrAmendmentRequest,
    ImplementationDraftPrAmendmentResult,
    amend_implementation_draft_pr,
)
from .github_ci import (
    GitHubImplementationCiBackend,
    UrllibGitHubImplementationCiTransport,
)
from .github_draft_pr_amendment import (
    GitHubImplementationDraftPrAmendmentBackend,
    UrllibGitHubDraftPrAmendmentTransport,
)
from .models import AGENT_ID, SCHEMA_VERSION, FrozenImplementationModel

DRAFT_PR_AMENDMENT_TOKEN_ENV: Literal[
    "CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"
] = "CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"


class ImplementationDraftPrAmendmentControlPlaneError(RuntimeError):
    """Raised when the dedicated amendment control plane cannot run safely."""


class ImplementationDraftPrAmendmentControlPlaneOperation(FrozenImplementationModel):
    """Strict operation containing one exact amendment request."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    request: ImplementationDraftPrAmendmentRequest


class ImplementationDraftPrAmendmentControlPlaneResult(FrozenImplementationModel):
    """Non-secret amendment evidence with permanently disabled escalation flags."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    agent_id: Literal["IMPLEMENTATION_AGENT_V1"] = AGENT_ID
    credential_source: Literal[
        "CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"
    ] = DRAFT_PR_AMENDMENT_TOKEN_ENV
    amendment: ImplementationDraftPrAmendmentResult
    ready_for_review: Literal[False] = False
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


def execute_draft_pr_amendment_control_plane(
    operation: ImplementationDraftPrAmendmentControlPlaneOperation,
    *,
    environ: Mapping[str, str] | None = None,
) -> ImplementationDraftPrAmendmentControlPlaneResult:
    """Use only the dedicated amendment credential and stop after exact-head CI."""
    operation = ImplementationDraftPrAmendmentControlPlaneOperation.model_validate(
        operation.model_dump(mode="python")
    )
    source = os.environ if environ is None else environ
    token = source.get(DRAFT_PR_AMENDMENT_TOKEN_ENV)
    if token is None or not token.strip():
        raise ImplementationDraftPrAmendmentControlPlaneError(
            f"{DRAFT_PR_AMENDMENT_TOKEN_ENV} is required; "
            "GITHUB_TOKEN and GH_TOKEN are forbidden as fallbacks"
        )
    amendment_transport = UrllibGitHubDraftPrAmendmentTransport(token=token)
    amendment_backend = GitHubImplementationDraftPrAmendmentBackend(
        amendment_transport
    )
    ci_transport = UrllibGitHubImplementationCiTransport(token=token)
    ci_backend = GitHubImplementationCiBackend(transport=ci_transport)
    result = amend_implementation_draft_pr(
        operation.request, amendment_backend, ci_backend
    )
    return ImplementationDraftPrAmendmentControlPlaneResult(amendment=result)
