from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cisco_assessment.devtools.implementation.codex_cli_backend import (
    CodexCliBackendError,
    CodexCliProcessResult,
    CodexCliSynthesisBackend,
)


class RecordingRunner:
    def __init__(self, *, returncode: int = 0, write_output: bool = True) -> None:
        self.returncode = returncode
        self.write_output = write_output
        self.argv: tuple[str, ...] | None = None
        self.cwd: Path | None = None
        self.input_text: str | None = None
        self.timeout_seconds: float | None = None
        self.env: dict[str, str] | None = None
        self.schema_payload: object | None = None

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        timeout_seconds: float,
        env: Mapping[str, str],
    ) -> CodexCliProcessResult:
        self.argv = tuple(argv)
        self.cwd = cwd
        self.input_text = input_text
        self.timeout_seconds = timeout_seconds
        self.env = dict(env)

        schema_path = Path(self.argv[self.argv.index("--output-schema") + 1])
        self.schema_payload = json.loads(schema_path.read_text(encoding="utf-8"))
        if self.write_output:
            output_path = Path(self.argv[self.argv.index("--output-last-message") + 1])
            output_path.write_text(_valid_output(), encoding="utf-8")
        return CodexCliProcessResult(
            returncode=self.returncode,
            stdout="ignored event stream",
            stderr="ignored diagnostics",
        )


def _valid_output() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "synthesis_id": "IMPLEMENTATION_SYNTHESIS_V1",
            "adapter_id": "CODEX_ADAPTER_V1",
            "repository": "owner/repo",
            "base_sha": "base-123",
            "objective": "Implement the approved slice.",
            "changes": [
                {
                    "kind": "CREATE",
                    "path": "tests/unit/test_generated.py",
                    "proposed_content": "def test_generated():\n    assert True\n",
                    "rationale": "Exercise the approved behavior.",
                    "acceptance_criteria": ["The generated test passes."],
                }
            ],
            "notes": [],
            "repository_mutation_requested": False,
            "contract_approval_claimed": False,
            "cisco_execution_allowed": False,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def test_local_codex_backend_uses_ephemeral_schema_constrained_read_only_exec() -> None:
    runner = RecordingRunner()
    backend = CodexCliSynthesisBackend(
        runner=runner,
        host_environment={"HOME": "/home/operator", "PATH": "/usr/bin"},
        timeout_seconds=42.0,
    )

    output = backend.synthesize("bounded prompt")

    assert output == _valid_output()
    assert runner.argv is not None
    assert runner.argv[:2] == ("codex", "exec")
    assert "--ephemeral" in runner.argv
    assert "--ignore-user-config" in runner.argv
    assert "--skip-git-repo-check" in runner.argv
    assert runner.argv[runner.argv.index("--sandbox") + 1] == "read-only"
    assert runner.argv[runner.argv.index("--model") + 1] == "gpt-5.6-sol"
    assert runner.argv[runner.argv.index("--color") + 1] == "never"
    assert runner.argv[-1] == "-"
    assert "--dangerously-bypass-approvals-and-sandbox" not in runner.argv
    assert "--dangerously-bypass-hook-trust" not in runner.argv
    assert runner.input_text == "bounded prompt"
    assert runner.timeout_seconds == 42.0
    assert runner.cwd is not None
    assert runner.cwd.name.startswith("cisco-assessment-codex-")


def test_local_codex_backend_writes_project_owned_output_schema() -> None:
    runner = RecordingRunner()
    backend = CodexCliSynthesisBackend(
        runner=runner,
        host_environment={"HOME": "/home/operator", "PATH": "/usr/bin"},
    )

    backend.synthesize("bounded prompt")

    assert isinstance(runner.schema_payload, dict)
    properties = runner.schema_payload["properties"]
    assert "repository" in properties
    assert "base_sha" in properties
    assert "changes" in properties
    assert "repository_mutation_requested" in properties
    assert "contract_approval_claimed" in properties
    assert "cisco_execution_allowed" in properties


def test_local_codex_backend_does_not_forward_control_plane_or_cisco_secrets() -> None:
    runner = RecordingRunner()
    backend = CodexCliSynthesisBackend(
        runner=runner,
        host_environment={
            "HOME": "/home/operator",
            "PATH": "/usr/bin",
            "CODEX_HOME": "/home/operator/.codex",
            "CISCO_ASSESSMENT_HUMAN_MERGE_TOKEN": "merge-secret",
            "CISCO_ASSESSMENT_PR_REVIEW_TOKEN": "review-secret",
            "CISCO_USERNAME": "switch-user",
            "CISCO_PASSWORD": "switch-password",
            "GITHUB_TOKEN": "github-secret",
            "GH_TOKEN": "gh-secret",
            "OPENAI_API_KEY": "api-secret",
        },
    )

    backend.synthesize("bounded prompt")

    assert runner.env == {
        "HOME": "/home/operator",
        "PATH": "/usr/bin",
        "CODEX_HOME": "/home/operator/.codex",
    }


def test_local_codex_backend_fails_closed_on_nonzero_exit() -> None:
    runner = RecordingRunner(returncode=7)
    backend = CodexCliSynthesisBackend(
        runner=runner,
        host_environment={"HOME": "/home/operator", "PATH": "/usr/bin"},
    )

    with pytest.raises(CodexCliBackendError, match="exit code 7"):
        backend.synthesize("bounded prompt")


def test_local_codex_backend_fails_closed_when_final_message_is_missing() -> None:
    runner = RecordingRunner(write_output=False)
    backend = CodexCliSynthesisBackend(
        runner=runner,
        host_environment={"HOME": "/home/operator", "PATH": "/usr/bin"},
    )

    with pytest.raises(CodexCliBackendError, match="did not produce its final message"):
        backend.synthesize("bounded prompt")


def test_local_codex_backend_rejects_blank_prompt_and_invalid_config() -> None:
    runner = RecordingRunner()
    backend = CodexCliSynthesisBackend(
        runner=runner,
        host_environment={"HOME": "/home/operator", "PATH": "/usr/bin"},
    )

    with pytest.raises(CodexCliBackendError, match="must not be blank"):
        backend.synthesize("   ")
    with pytest.raises(ValueError, match="model must not be blank"):
        CodexCliSynthesisBackend(model=" ")
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        CodexCliSynthesisBackend(timeout_seconds=0)
