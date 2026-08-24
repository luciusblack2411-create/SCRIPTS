"""Local Agent-First execution surface for the protected feature controller."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from ..pr_review.github_rest import UrllibGitHubTransport
from ..ready_for_review_control_plane import (
    PR_REVIEW_TOKEN_ENV,
    READY_FOR_REVIEW_TOKEN_ENV,
    ReadyForReviewControlPlaneResult,
    execute_ready_for_review_control_plane,
)
from .codex_cli_backend import CodexCliSynthesisBackend
from .draft_pr_control_plane import (
    DRAFT_PR_CONTROL_PLANE_TOKEN_ENV,
    ImplementationDraftPrControlPlaneResult,
    execute_draft_pr_control_plane,
)
from .feature_controller import (
    FeatureExecutionDependencies,
    FeatureExecutionOperation,
    FeatureExecutionResult,
    execute_feature_delivery_controller,
)
from .github_ci import (
    GitHubImplementationCiBackend,
    UrllibGitHubImplementationCiTransport,
)
from .github_mutation import (
    GitHubImplementationMutationBackend,
    UrllibGitHubImplementationMutationTransport,
)
from .github_rest import GitHubImplementationReadBackend
from .models import FrozenImplementationModel
from .run_journal import JsonFeatureRunJournalStore

LOCAL_FEATURE_EXECUTION_RUNTIME_ID: Literal["LOCAL_FEATURE_EXECUTION_RUNTIME_V1"] = (
    "LOCAL_FEATURE_EXECUTION_RUNTIME_V1"
)
SCHEMA_VERSION: Literal["1.0"] = "1.0"
IMPLEMENTATION_TOKEN_ENV: Literal["CISCO_ASSESSMENT_IMPLEMENTATION_TOKEN"] = (
    "CISCO_ASSESSMENT_IMPLEMENTATION_TOKEN"
)
VALIDATED_CODEX_CLI_VERSION: Literal["0.149.1"] = "0.149.1"
VALIDATED_CODEX_MODEL: Literal["gpt-5.6-sol"] = "gpt-5.6-sol"


class LocalFeatureExecutionError(RuntimeError):
    """Raised when the local Agent-First runtime cannot be trusted."""


class LocalFeatureExecutionPreflight(FrozenImplementationModel):
    """Non-secret evidence that the local execution dependencies are bounded."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    runtime_id: Literal["LOCAL_FEATURE_EXECUTION_RUNTIME_V1"] = LOCAL_FEATURE_EXECUTION_RUNTIME_ID
    implementation_credential_source: Literal["CISCO_ASSESSMENT_IMPLEMENTATION_TOKEN"] = (
        IMPLEMENTATION_TOKEN_ENV
    )
    draft_pr_credential_source: Literal["CISCO_ASSESSMENT_DRAFT_PR_TOKEN"] = (
        DRAFT_PR_CONTROL_PLANE_TOKEN_ENV
    )
    review_credential_source: Literal["CISCO_ASSESSMENT_PR_REVIEW_TOKEN"] = PR_REVIEW_TOKEN_ENV
    codex_executable: str
    codex_cli_version: Literal["0.149.1"] = VALIDATED_CODEX_CLI_VERSION
    codex_model: Literal["gpt-5.6-sol"] = VALIDATED_CODEX_MODEL
    merge_performed: Literal[False] = False
    human_merge_gate_required: Literal[True] = True
    cisco_execution_allowed: Literal[False] = False


CodexVersionProbe = Callable[[str, Mapping[str, str]], str]


def resolve_local_feature_execution_tokens(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str, str]:
    """Resolve only explicit implementation, Draft PR, and review credentials."""
    source = os.environ if environ is None else environ
    implementation_token = _required_secret(source, IMPLEMENTATION_TOKEN_ENV)
    draft_pr_token = _required_secret(source, DRAFT_PR_CONTROL_PLANE_TOKEN_ENV)
    review_token = _required_secret(source, PR_REVIEW_TOKEN_ENV)
    if len({implementation_token, draft_pr_token, review_token}) != 3:
        raise LocalFeatureExecutionError(
            "implementation, Draft PR, and PR Review credentials must be distinct"
        )
    return implementation_token, draft_pr_token, review_token


def build_local_feature_execution_dependencies(
    *,
    journal_root: Path,
    environ: Mapping[str, str] | None = None,
    codex_executable: str = "codex",
    codex_version_probe: CodexVersionProbe | None = None,
) -> tuple[LocalFeatureExecutionPreflight, FeatureExecutionDependencies]:
    """Instantiate real local/GitHub dependencies without granting merge or Cisco authority."""
    source = os.environ if environ is None else environ
    implementation_token, draft_pr_token, review_token = resolve_local_feature_execution_tokens(source)
    probe = codex_version_probe or _probe_codex_cli_version
    codex_version = probe(codex_executable, source)
    if codex_version != VALIDATED_CODEX_CLI_VERSION:
        raise LocalFeatureExecutionError(
            "Codex CLI version is not validated for LOCAL_FEATURE_EXECUTION_RUNTIME_V1: "
            f"expected {VALIDATED_CODEX_CLI_VERSION}, observed {codex_version!r}"
        )

    source_backend = GitHubImplementationReadBackend(
        transport=UrllibGitHubTransport(token=implementation_token)
    )
    mutation_backend = GitHubImplementationMutationBackend(
        transport=UrllibGitHubImplementationMutationTransport(token=implementation_token)
    )
    ci_backend = GitHubImplementationCiBackend(
        transport=UrllibGitHubImplementationCiTransport(token=implementation_token)
    )
    codex_backend = CodexCliSynthesisBackend(
        executable=codex_executable,
        model=VALIDATED_CODEX_MODEL,
        host_environment=source,
    )

    def draft_pr_executor(operation: object) -> ImplementationDraftPrControlPlaneResult:
        from .draft_pr_control_plane import ImplementationDraftPrControlPlaneOperation

        validated = ImplementationDraftPrControlPlaneOperation.model_validate(operation)
        return execute_draft_pr_control_plane(
            validated,
            environ={DRAFT_PR_CONTROL_PLANE_TOKEN_ENV: draft_pr_token},
        )

    def ready_for_review_executor(operation: object) -> ReadyForReviewControlPlaneResult:
        from ..ready_for_review import ReadyForReviewOperation

        validated = ReadyForReviewOperation.model_validate(operation)
        return execute_ready_for_review_control_plane(
            validated,
            environ={
                PR_REVIEW_TOKEN_ENV: review_token,
                READY_FOR_REVIEW_TOKEN_ENV: draft_pr_token,
            },
        )

    preflight = LocalFeatureExecutionPreflight(
        codex_executable=codex_executable,
    )
    dependencies = FeatureExecutionDependencies(
        source_backend=source_backend,
        codex_backend=codex_backend,
        mutation_backend=mutation_backend,
        ci_backend=ci_backend,
        draft_pr_executor=draft_pr_executor,
        ready_for_review_executor=ready_for_review_executor,
        journal_store=JsonFeatureRunJournalStore(journal_root),
    )
    return preflight, dependencies


def execute_local_feature_delivery(
    operation: FeatureExecutionOperation,
    *,
    journal_root: Path,
    environ: Mapping[str, str] | None = None,
    codex_executable: str = "codex",
    codex_version_probe: CodexVersionProbe | None = None,
) -> tuple[LocalFeatureExecutionPreflight, FeatureExecutionResult]:
    """Run the real controller through Ready and stop before the Human Merge control plane."""
    preflight, dependencies = build_local_feature_execution_dependencies(
        journal_root=journal_root,
        environ=environ,
        codex_executable=codex_executable,
        codex_version_probe=codex_version_probe,
    )
    result = execute_feature_delivery_controller(operation, dependencies)
    return preflight, result


def _probe_codex_cli_version(executable: str, environment: Mapping[str, str]) -> str:
    if not executable.strip():
        raise LocalFeatureExecutionError("Codex CLI executable must not be blank")
    probe_environment = {
        name: value
        for name, value in environment.items()
        if name in {"HOME", "PATH", "CODEX_HOME"} and value
    }
    try:
        completed = subprocess.run(
            (executable, "--version"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=10.0,
            check=False,
            env=probe_environment,
        )
    except FileNotFoundError as exc:
        raise LocalFeatureExecutionError("Codex CLI executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise LocalFeatureExecutionError("Codex CLI version probe timed out") from exc
    except (OSError, UnicodeError) as exc:
        raise LocalFeatureExecutionError("Codex CLI version probe failed") from exc
    if completed.returncode != 0:
        raise LocalFeatureExecutionError(
            f"Codex CLI version probe failed with exit code {completed.returncode}"
        )
    output = completed.stdout.strip()
    prefix = "codex-cli "
    if not output.startswith(prefix) or not output[len(prefix) :].strip():
        raise LocalFeatureExecutionError("Codex CLI version output is not recognized")
    return output[len(prefix) :].strip()


def _required_secret(source: Mapping[str, str], name: str) -> str:
    value = source.get(name)
    if value is None or not value.strip():
        raise LocalFeatureExecutionError(
            f"{name} is required; generic GITHUB_TOKEN/GH_TOKEN fallbacks are not accepted"
        )
    return value
