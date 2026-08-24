"""Local Codex CLI backend for proposal-only implementation synthesis."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from .synthesis import CodexSynthesisOutput, ImplementationSynthesisError

LOCAL_CODEX_CLI_BACKEND_ID: Final = "LOCAL_CODEX_CLI_BACKEND_V1"

_ALLOWED_ENVIRONMENT_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ALL_PROXY",
        "CODEX_HOME",
        "HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "LANG",
        "LC_ALL",
        "NO_PROXY",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "all_proxy",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
)


class CodexCliBackendError(ImplementationSynthesisError):
    """Raised when the bounded local Codex CLI invocation cannot be trusted."""


@dataclass(frozen=True)
class CodexCliProcessResult:
    """Minimal subprocess result exposed to the backend."""

    returncode: int
    stdout: str
    stderr: str


class CodexCliProcessRunner(Protocol):
    """Project-owned process seam used by the local Codex CLI backend."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        timeout_seconds: float,
        env: Mapping[str, str],
    ) -> CodexCliProcessResult:
        """Execute one exact argv without a shell and return captured text streams."""
        ...


class SubprocessCodexCliProcessRunner:
    """Stdlib process runner with no shell command surface."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        input_text: str,
        timeout_seconds: float,
        env: Mapping[str, str],
    ) -> CodexCliProcessResult:
        try:
            completed = subprocess.run(
                tuple(argv),
                cwd=cwd,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=timeout_seconds,
                check=False,
                env=dict(env),
            )
        except FileNotFoundError as exc:
            raise CodexCliBackendError("Codex CLI executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexCliBackendError("Codex CLI synthesis timed out") from exc
        except UnicodeError as exc:
            raise CodexCliBackendError("Codex CLI emitted non-UTF-8 process output") from exc
        except OSError as exc:
            raise CodexCliBackendError("Codex CLI process could not be started") from exc
        return CodexCliProcessResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class CodexCliSynthesisBackend:
    """Concrete CODEX_ADAPTER_V1 backend using a local non-interactive Codex CLI."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        model: str = "gpt-5.6-sol",
        timeout_seconds: float = 300.0,
        runner: CodexCliProcessRunner | None = None,
        host_environment: Mapping[str, str] | None = None,
    ) -> None:
        if not executable.strip():
            raise ValueError("Codex CLI executable must not be blank")
        if not model.strip():
            raise ValueError("Codex CLI model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("Codex CLI timeout_seconds must be positive")
        self._executable = executable
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._runner = runner or SubprocessCodexCliProcessRunner()
        self._host_environment = dict(host_environment) if host_environment is not None else None

    def synthesize(self, prompt: str) -> str:
        """Return one schema-constrained proposal without repository or Cisco mutation."""
        if not prompt.strip():
            raise CodexCliBackendError("Codex synthesis prompt must not be blank")

        source_environment = (
            self._host_environment if self._host_environment is not None else os.environ
        )
        environment = _sanitized_environment(source_environment)

        with tempfile.TemporaryDirectory(prefix="cisco-assessment-codex-") as directory:
            root = Path(directory)
            schema_path = root / "codex-synthesis-output.schema.json"
            output_path = root / "codex-synthesis-output.json"
            schema_path.write_text(
                json.dumps(
                    CodexSynthesisOutput.model_json_schema(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            argv = (
                self._executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--disable",
                "shell_tool",
                "--disable",
                "unified_exec",
                "--disable",
                "code_mode",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--model",
                self._model,
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            )
            result = self._runner.run(
                argv,
                cwd=root,
                input_text=prompt,
                timeout_seconds=self._timeout_seconds,
                env=environment,
            )
            if result.returncode != 0:
                raise CodexCliBackendError(
                    f"Codex CLI synthesis failed with exit code {result.returncode}"
                )
            try:
                output = output_path.read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise CodexCliBackendError("Codex CLI did not produce its final message file") from exc
            except UnicodeError as exc:
                raise CodexCliBackendError("Codex CLI final message is not strict UTF-8") from exc
            if not output.strip():
                raise CodexCliBackendError("Codex CLI produced an empty final message")
            return output


def _sanitized_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Forward only runtime variables needed by Codex, never project control-plane secrets."""
    return {
        name: value
        for name, value in source.items()
        if name in _ALLOWED_ENVIRONMENT_NAMES and value
    }
