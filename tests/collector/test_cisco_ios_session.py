from __future__ import annotations

from collections import deque

import pytest

from cisco_assessment.collector.exceptions import (
    CommandCliError,
    CommandTimeoutError,
    SessionSetupError,
)
from cisco_assessment.collector.session.cisco_ios import CiscoIOSSession


class ScriptedTransport:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = deque(chunks)
        self.sent: list[bytes] = []
        self.closed = False

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def receive_ready(self) -> bool:
        return bool(self.chunks)

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return self.chunks.popleft()

    def close(self) -> None:
        self.closed = True


def test_session_learns_prompt_then_returns_exact_command_bytes() -> None:
    initial = [b"Cisco IOS XE\r\nSW1#"]
    command_chunks = [b"show version\r\nCisco IOS ", b"XE Software  \r\nSW1#"]
    transport = ScriptedTransport(initial + command_chunks)
    session = CiscoIOSSession(transport, sleeper=lambda _: None)

    session.open()
    result = session.execute("show version", timeout=1.0)

    assert transport.sent == [b"show version\n"]
    assert result.raw == b"".join(command_chunks)


def test_known_prompt_prevents_prompt_like_output_line_from_finishing_early() -> None:
    chunks = [
        b"SW1#",
        b"show version\r\nNotTheLearnedPrompt#\r\nmore output\r\n",
        b"SW1#",
    ]
    transport = ScriptedTransport(chunks)
    session = CiscoIOSSession(transport, sleeper=lambda _: None)
    session.open()

    result = session.execute("show version", timeout=1.0)
    assert result.raw == b"show version\r\nNotTheLearnedPrompt#\r\nmore output\r\nSW1#"


def test_cli_error_is_classified_with_raw_evidence() -> None:
    transport = ScriptedTransport([b"SW1#", b"show version\r\n% Invalid input\r\nSW1#"])
    session = CiscoIOSSession(transport, sleeper=lambda _: None)
    session.open()

    with pytest.raises(CommandCliError) as exc_info:
        session.execute("show version", timeout=1.0)

    assert exc_info.value.cli_error_type == "unsupported_command"
    assert b"% Invalid input" in exc_info.value.partial_raw


def test_command_timeout_carries_partial_raw() -> None:
    times = iter([0.0, 0.0, 0.0, 0.0, 2.0])
    transport = ScriptedTransport([b"SW1#", b"show version\r\npartial"])
    session = CiscoIOSSession(
        transport,
        clock=lambda: next(times),
        sleeper=lambda _: None,
    )
    session.open()

    with pytest.raises(CommandTimeoutError) as exc_info:
        session.execute("show version", timeout=1.0)

    assert exc_info.value.partial_raw == b"show version\r\npartial"


def test_session_refuses_configuration_mode_prompt() -> None:
    transport = ScriptedTransport([b"SW1(config)#"])
    session = CiscoIOSSession(transport, sleeper=lambda _: None)

    with pytest.raises(SessionSetupError, match="configuration mode"):
        session.open()
