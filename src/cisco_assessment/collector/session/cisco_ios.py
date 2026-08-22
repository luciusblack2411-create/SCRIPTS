"""Cisco IOS/IOS-XE interactive exec session."""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from cisco_assessment.collector.exceptions import (
    CommandCliError,
    CommandTimeoutError,
    SessionSetupError,
)
from cisco_assessment.collector.session.base import SessionCommandResult
from cisco_assessment.collector.transport.base import SSHTransport

_GENERIC_PROMPT_RE = re.compile(rb"(?:^|\r?\n)([^\r\n]{1,200}[>#])\s*\Z")
_PAGER_MARKER = b"--More--"
_PAGER_CONTINUE = b" "
_CLI_ERROR_MARKERS: tuple[tuple[bytes, str], ...] = (
    (b"% Invalid input", "unsupported_command"),
    (b"% Incomplete command", "incomplete_command"),
    (b"% Ambiguous command", "ambiguous_command"),
    (b"% Authorization failed", "command_authorization_failed"),
    (b"% Authorization denied", "command_authorization_failed"),
)


class CiscoIOSSession:
    """Prompt-aware Cisco exec session that preserves received command bytes."""

    def __init__(
        self,
        transport: SSHTransport,
        *,
        setup_timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        poll_interval: float = 0.02,
    ) -> None:
        self._transport = transport
        self._setup_timeout = setup_timeout
        self._clock = clock
        self._sleeper = sleeper
        self._poll_interval = poll_interval
        self._prompt: bytes | None = None

    def open(self) -> None:
        initial = self._read_until_generic_prompt(timeout=self._setup_timeout)
        match = _GENERIC_PROMPT_RE.search(initial)
        if match is None:
            raise SessionSetupError("unable to detect Cisco CLI prompt")
        prompt = match.group(1)
        if b"(config" in prompt.lower():
            raise SessionSetupError("collector refuses to operate from configuration mode")
        self._prompt = prompt

    def execute(self, command: str, *, timeout: float) -> SessionCommandResult:
        if self._prompt is None:
            raise SessionSetupError("Cisco session must be opened before command execution")
        self._transport.send(command.encode("ascii") + b"\n")
        raw = self._read_until_known_prompt(timeout=timeout)
        for marker, error_type in _CLI_ERROR_MARKERS:
            if marker in raw:
                raise CommandCliError(
                    f"Cisco CLI returned {error_type}",
                    cli_error_type=error_type,
                    partial_raw=raw,
                )
        return SessionCommandResult(raw=raw)

    def close(self) -> None:
        self._transport.close()

    def _read_until_generic_prompt(self, *, timeout: float) -> bytes:
        return self._read_until(timeout=timeout, prompt_pattern=_GENERIC_PROMPT_RE, command=False)

    def _read_until_known_prompt(self, *, timeout: float) -> bytes:
        if self._prompt is None:
            raise SessionSetupError("Cisco prompt has not been learned")
        prompt_pattern = re.compile(
            rb"(?:^|\r?\n)" + re.escape(self._prompt) + rb"\s*\Z"
        )
        return self._read_until(timeout=timeout, prompt_pattern=prompt_pattern, command=True)

    def _read_until(
        self,
        *,
        timeout: float,
        prompt_pattern: re.Pattern[bytes],
        command: bool,
    ) -> bytes:
        deadline = self._clock() + timeout
        chunks: list[bytes] = []
        pagers_advanced = 0
        while self._clock() < deadline:
            if self._transport.receive_ready():
                chunk = self._transport.receive()
                if chunk:
                    chunks.append(chunk)
                    raw = b"".join(chunks)
                    if prompt_pattern.search(raw):
                        return raw
                    if command:
                        observed_pagers = raw.count(_PAGER_MARKER)
                        while pagers_advanced < observed_pagers:
                            # Space is interactive session control only; it is not a CLI command.
                            self._transport.send(_PAGER_CONTINUE)
                            pagers_advanced += 1
            else:
                self._sleeper(self._poll_interval)

        raw = b"".join(chunks)
        if command:
            raise CommandTimeoutError("command timed out waiting for prompt", partial_raw=raw)
        raise SessionSetupError("session timed out waiting for Cisco prompt")
