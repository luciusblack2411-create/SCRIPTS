from __future__ import annotations
import re, time
from collections.abc import Callable
from cisco_switch_assessment.collector.exceptions import CommandAuthorizationError, CommandTimeoutError, CommandUnsupportedError, SessionSetupError
from cisco_switch_assessment.collector.session.base import SessionCommandResult
from cisco_switch_assessment.collector.transport.base import SSHTransport

_PROMPT_RE = re.compile(rb"(?:^|\r?\n)[^\r\n]{1,200}[>#]\s*\Z")
_UNSUPPORTED_MARKERS = (b"% Invalid input", b"% Incomplete command", b"% Ambiguous command")
_AUTH_MARKERS = (b"% Authorization failed", b"% Authorization denied")

class CiscoIOSSession:
    def __init__(self, transport: SSHTransport, *, clock: Callable[[], float] = time.monotonic, sleeper: Callable[[float], None] = time.sleep, poll_interval: float = 0.02) -> None:
        self._transport, self._clock, self._sleeper, self._poll_interval = transport, clock, sleeper, poll_interval

    def open(self) -> None:
        initial = self._read_until_prompt(timeout=10.0)
        if not _PROMPT_RE.search(initial):
            raise SessionSetupError("unable to detect Cisco CLI prompt")
        self._send_session_control("terminal length 0", timeout=5.0)

    def execute(self, command: str, *, timeout: float) -> SessionCommandResult:
        self._transport.send(command.encode("ascii") + b"\n")
        raw = self._read_until_prompt(timeout=timeout, command_timeout=True)
        if any(marker in raw for marker in _AUTH_MARKERS):
            raise CommandAuthorizationError("command authorization failed", partial_raw=raw)
        if any(marker in raw for marker in _UNSUPPORTED_MARKERS):
            raise CommandUnsupportedError("command is unsupported by device", partial_raw=raw)
        return SessionCommandResult(raw=raw)

    def close(self) -> None:
        self._transport.close()

    def _send_session_control(self, command: str, *, timeout: float) -> None:
        self._transport.send(command.encode("ascii") + b"\n")
        self._read_until_prompt(timeout=timeout)

    def _read_until_prompt(self, *, timeout: float, command_timeout: bool = False) -> bytes:
        deadline = self._clock() + timeout
        chunks: list[bytes] = []
        while self._clock() < deadline:
            if self._transport.receive_ready():
                chunk = self._transport.receive()
                if chunk:
                    chunks.append(chunk)
                    raw = b"".join(chunks)
                    if _PROMPT_RE.search(raw):
                        return raw
            else:
                self._sleeper(self._poll_interval)
        raw = b"".join(chunks)
        if command_timeout:
            raise CommandTimeoutError("command timed out waiting for prompt", partial_raw=raw)
        raise SessionSetupError("session timed out waiting for prompt")
