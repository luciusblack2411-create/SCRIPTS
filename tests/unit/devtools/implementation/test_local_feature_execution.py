from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cisco_assessment.devtools.implementation import local_feature_execution
from cisco_assessment.devtools.implementation.codex_cli_backend import CodexCliSynthesisBackend
from cisco_assessment.devtools.implementation.github_ci import GitHubImplementationCiBackend
from cisco_assessment.devtools.implementation.github_mutation import (
    GitHubImplementationMutationBackend,
)
from cisco_assessment.devtools.implementation.github_rest import GitHubImplementationReadBackend
from cisco_assessment.devtools.implementation.local_feature_execution import (
    IMPLEMENTATION_TOKEN_ENV,
    LOCAL_FEATURE_EXECUTION_RUNTIME_ID,
    VALIDATED_CODEX_CLI_VERSION,
    VALIDATED_CODEX_MODEL,
    LocalFeatureExecutionError,
    build_local_feature_execution_dependencies,
    resolve_local_feature_execution_tokens,
)
from cisco_assessment.devtools.ready_for_review_control_plane import (
    PR_REVIEW_TOKEN_ENV,
    READY_FOR_REVIEW_TOKEN_ENV,
)


def _environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin",
        "HOME": "/home/operator",
        IMPLEMENTATION_TOKEN_ENV: "implementation-secret",
        READY_FOR_REVIEW_TOKEN_ENV: "draft-secret",
        PR_REVIEW_TOKEN_ENV: "review-secret",
        "GITHUB_TOKEN": "generic-secret",
        "GH_TOKEN": "generic-gh-secret",
        "OPENAI_API_KEY": "api-secret",
        "CISCO_USERNAME": "switch-user",
        "CISCO_PASSWORD": "switch-password",
        "CISCO_ASSESSMENT_HUMAN_MERGE_TOKEN": "merge-secret",
    }


def test_runtime_requires_explicit_distinct_credentials() -> None:
    with pytest.raises(LocalFeatureExecutionError, match=IMPLEMENTATION_TOKEN_ENV):
        resolve_local_feature_execution_tokens(
            {
                "GITHUB_TOKEN": "generic-only",
                READY_FOR_REVIEW_TOKEN_ENV: "draft-secret",
                PR_REVIEW_TOKEN_ENV: "review-secret",
            }
        )

    environment = _environment()
    environment[PR_REVIEW_TOKEN_ENV] = environment[READY_FOR_REVIEW_TOKEN_ENV]
    with pytest.raises(LocalFeatureExecutionError, match="must be distinct"):
        resolve_local_feature_execution_tokens(environment)


def test_runtime_builds_real_dependencies_with_bounded_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_feature_execution,
        "_probe_codex_cli_version",
        lambda executable, environment: VALIDATED_CODEX_CLI_VERSION,
    )

    preflight, dependencies = build_local_feature_execution_dependencies(
        journal_root=tmp_path,
        environ=_environment(),
    )

    assert preflight.runtime_id == LOCAL_FEATURE_EXECUTION_RUNTIME_ID
    assert preflight.codex_cli_version == VALIDATED_CODEX_CLI_VERSION
    assert preflight.codex_model == VALIDATED_CODEX_MODEL
    assert preflight.implementation_credential_source == IMPLEMENTATION_TOKEN_ENV
    assert preflight.draft_pr_credential_source == READY_FOR_REVIEW_TOKEN_ENV
    assert preflight.review_credential_source == PR_REVIEW_TOKEN_ENV
    assert preflight.merge_performed is False
    assert preflight.human_merge_gate_required is True
    assert preflight.cisco_execution_allowed is False

    assert isinstance(dependencies.source_backend, GitHubImplementationReadBackend)
    assert isinstance(dependencies.codex_backend, CodexCliSynthesisBackend)
    assert isinstance(dependencies.mutation_backend, GitHubImplementationMutationBackend)
    assert isinstance(dependencies.ci_backend, GitHubImplementationCiBackend)

    assert dependencies.source_backend._transport._token == "implementation-secret"
    assert dependencies.mutation_backend._transport._token == "implementation-secret"
    assert dependencies.ci_backend._transport._token == "implementation-secret"


def test_runtime_fails_closed_on_unvalidated_codex_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_feature_execution,
        "_probe_codex_cli_version",
        lambda executable, environment: "0.150.0",
    )

    with pytest.raises(LocalFeatureExecutionError, match="not validated"):
        build_local_feature_execution_dependencies(
            journal_root=tmp_path,
            environ=_environment(),
        )


def test_codex_version_probe_uses_exact_argv_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            args=("codex", "--version"),
            returncode=0,
            stdout="codex-cli 0.149.1\n",
            stderr="",
        )

    monkeypatch.setattr(local_feature_execution.subprocess, "run", fake_run)

    version = local_feature_execution._probe_codex_cli_version(
        "codex",
        {
            "PATH": "/usr/bin",
            "HOME": "/home/operator",
            IMPLEMENTATION_TOKEN_ENV: "implementation-secret",
            "GITHUB_TOKEN": "generic-secret",
        },
    )

    assert version == "0.149.1"
    assert observed["argv"] == ("codex", "--version")
    assert "shell" not in observed
    assert observed["env"] == {"PATH": "/usr/bin", "HOME": "/home/operator"}
