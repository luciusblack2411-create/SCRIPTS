"""Credential-separated factory layer for controlled Return-to-Draft."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .github_return_to_draft import GitHubReturnToDraftBackend
from .pr_review.github_rest import GitHubRestReadBackend, UrllibGitHubTransport
from .return_to_draft import (
    CONTROL_PLANE_ID,
    SCHEMA_VERSION,
    ReturnToDraftOperation,
    ReturnToDraftReadBackend,
    ReturnToDraftResult,
    ReturnToDraftTransitionBackend,
    execute_return_to_draft,
)

PR_REVIEW_TOKEN_ENV: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = "CISCO_ASSESSMENT_PR_REVIEW_TOKEN"
RETURN_TO_DRAFT_TOKEN_ENV: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = "CISCO_ASSESSMENT_DRAFT_PR_TOKEN"


class ReturnToDraftControlPlaneError(RuntimeError):
    pass


class ReturnToDraftControlPlaneFileError(ReturnToDraftControlPlaneError):
    pass


class FrozenControlPlaneModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReturnToDraftControlPlaneResult(FrozenControlPlaneModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    control_plane_id: Literal["CONTROLLED_RETURN_TO_DRAFT_V1"] = CONTROL_PLANE_ID
    read_credential_source: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = PR_REVIEW_TOKEN_ENV
    transition_credential_source: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = RETURN_TO_DRAFT_TOKEN_ENV
    return_to_draft: ReturnToDraftResult


ReadBackendFactory = Callable[[str], ReturnToDraftReadBackend]
TransitionBackendFactory = Callable[[str], ReturnToDraftTransitionBackend]


def resolve_return_to_draft_tokens(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    source = os.environ if environ is None else environ
    read_token = source.get(PR_REVIEW_TOKEN_ENV)
    transition_token = source.get(RETURN_TO_DRAFT_TOKEN_ENV)
    if read_token is None or not read_token.strip():
        raise ReturnToDraftControlPlaneError(
            f"{PR_REVIEW_TOKEN_ENV} is required; GITHUB_TOKEN and GH_TOKEN are not fallbacks"
        )
    if transition_token is None or not transition_token.strip():
        raise ReturnToDraftControlPlaneError(
            f"{RETURN_TO_DRAFT_TOKEN_ENV} is required; GITHUB_TOKEN and GH_TOKEN are not fallbacks"
        )
    if read_token == transition_token:
        raise ReturnToDraftControlPlaneError("read and transition credentials must be distinct")
    return read_token, transition_token


def load_return_to_draft_operation(path: Path) -> ReturnToDraftOperation:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReturnToDraftControlPlaneFileError(f"cannot read operation {path}: {exc}") from exc
    try:
        return ReturnToDraftOperation.model_validate_json(content)
    except ValidationError as exc:
        raise ReturnToDraftControlPlaneFileError(f"invalid operation {path}: {exc}") from exc


def _default_read_backend_factory(token: str) -> ReturnToDraftReadBackend:
    return GitHubRestReadBackend(UrllibGitHubTransport(token=token))


def _default_transition_backend_factory(token: str) -> ReturnToDraftTransitionBackend:
    return GitHubReturnToDraftBackend(token=token)


def execute_return_to_draft_control_plane(
    operation: ReturnToDraftOperation,
    *,
    environ: Mapping[str, str] | None = None,
    read_backend_factory: ReadBackendFactory = _default_read_backend_factory,
    transition_backend_factory: TransitionBackendFactory = _default_transition_backend_factory,
) -> ReturnToDraftControlPlaneResult:
    read_token, transition_token = resolve_return_to_draft_tokens(environ)
    result = execute_return_to_draft(
        operation,
        read_backend=read_backend_factory(read_token),
        transition_backend=transition_backend_factory(transition_token),
    )
    return ReturnToDraftControlPlaneResult(return_to_draft=result)


def render_return_to_draft_control_plane_json(result: ReturnToDraftControlPlaneResult) -> str:
    return result.model_dump_json(indent=2)


def render_return_to_draft_control_plane_human(result: ReturnToDraftControlPlaneResult) -> str:
    value = result.return_to_draft
    return "\n".join(
        (
            f"Decision: {value.decision.value}",
            f"PR: {value.repository}#{value.pr_number}",
            f"Historical base: {value.base_branch}@{value.historical_pr_base_sha}",
            f"Expected live base: {value.base_branch}@{value.expected_live_base_sha}",
            f"Head: {value.head_branch}@{value.head_sha}",
            f"Transition performed: {str(value.transition_performed).lower()}",
            f"Returned to Draft: {str(value.returned_to_draft).lower()}",
            "Ready for Review: false",
            "Merge performed: false",
            "Human merge gate required: true",
            "Cisco execution allowed: false",
        )
    )
