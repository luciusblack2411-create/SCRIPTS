from __future__ import annotations

from collections import deque
from pathlib import Path

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


class PaginatedScriptedTransport:
    """Expose the next page only after the session sends a single space."""

    def __init__(self, pages: list[bytes]) -> None:
        if not pages:
            raise ValueError("pages must not be empty")
        self._available = deque([b"SWITCH#", pages[0]])
        self._remaining = deque(pages[1:])
        self.sent: list[bytes] = []
        self.closed = False

    def send(self, data: bytes) -> None:
        self.sent.append(data)
        if data == b" " and self._remaining:
            self._available.append(self._remaining.popleft())

    def receive_ready(self) -> bool:
        return bool(self._available)

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return self._available.popleft()

    def close(self) -> None:
        self.closed = True


def _load_paginated_show_version_fixture() -> list[bytes]:
    fixture_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "collector"
        / "iosxe"
        / "show_version_paginated.txt"
    )
    encoded_pages = fixture_path.read_text(encoding="ascii").strip().split("\n===PAGE===\n")
    return [
        page.encode("ascii").decode("unicode_escape").encode("latin-1")
        for page in encoded_pages
    ]


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


def test_single_pager_is_advanced_once_until_learned_prompt() -> None:
    pages = [
        b"show version\r\nCisco IOS XE Software\r\n--More--",
        b"\r\nSystem image file is flash:packages.conf\r\nSWITCH#",
    ]
    transport = PaginatedScriptedTransport(pages)
    session = CiscoIOSSession(transport, sleeper=lambda _: None)

    session.open()
    result = session.execute("show version", timeout=1.0)

    assert transport.sent == [b"show version\n", b" "]
    assert result.raw == b"".join(pages)
    assert result.raw.endswith(b"SWITCH#")


def test_multiple_pagers_advance_once_each_and_preserve_fixture_raw() -> None:
    pages = _load_paginated_show_version_fixture()
    transport = PaginatedScriptedTransport(pages)
    session = CiscoIOSSession(transport, sleeper=lambda _: None)

    session.open()
    result = session.execute("show version", timeout=1.0)

    assert transport.sent == [b"show version\n", b" ", b" "]
    assert result.raw == b"".join(pages)
    assert result.raw.count(b"--More--") == 2
    assert result.raw.endswith(b"SWITCH#")


def test_timeout_after_pager_keeps_full_partial_raw_and_does_not_repeat_space() -> None:
    page = b"show version\r\nCisco IOS XE Software\r\n--More--"
    times = iter([0.0, 0.0, 0.0, 0.0, 0.5, 2.0])
    transport = PaginatedScriptedTransport([page])
    session = CiscoIOSSession(
        transport,
        clock=lambda: next(times),
        sleeper=lambda _: None,
    )

    session.open()
    with pytest.raises(CommandTimeoutError) as exc_info:
        session.execute("show version", timeout=1.0)

    assert transport.sent == [b"show version\n", b" "]
    assert exc_info.value.partial_raw == page


def test_session_refuses_configuration_mode_prompt() -> None:
    transport = ScriptedTransport([b"SW1(config)#"])
    session = CiscoIOSSession(transport, sleeper=lambda _: None)

    with pytest.raises(SessionSetupError, match="configuration mode"):
        session.open()
