from __future__ import annotations

from uuid import uuid4

from cisco_assessment.catalog import COMMAND_CATALOG_V0_1
from cisco_assessment.collector.exceptions import AuthenticationError
from cisco_assessment.collector.executor import CommandExecutor
from cisco_assessment.collector.policy import ReadOnlyPolicy
from cisco_assessment.collector.service import DeviceCollector
from cisco_assessment.collector.session.factory import SessionFactory
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import CommandExecutionStatus, Device, PlatformFamily

from .fakes import InMemoryRawRepository


class FailingConnectTransport:
    def __init__(self) -> None:
        self.closed = False

    def connect(self, **kwargs: object) -> None:
        del kwargs
        raise AuthenticationError("bad credentials")

    def send(self, data: bytes) -> None:
        del data

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return b""

    def receive_ready(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


class SuccessfulTransport:
    def __init__(self) -> None:
        self._chunks = [b"SW1#", b"show version\r\nCisco IOS XE\r\nSW1#"]
        self.sent: list[bytes] = []
        self.closed = False

    def connect(self, **kwargs: object) -> None:
        del kwargs

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return self._chunks.pop(0)

    def receive_ready(self) -> bool:
        return bool(self._chunks)

    def close(self) -> None:
        self.closed = True


class PaginatedSuccessfulTransport:
    def __init__(self) -> None:
        self.first_page = b"show version\r\nCisco IOS XE\r\n--More--"
        self.final_page = b"\r\nSystem image file is flash:packages.conf\r\nSW1#"
        self._chunks = [b"SW1#", self.first_page]
        self._continuation: bytes | None = self.final_page
        self.sent: list[bytes] = []
        self.closed = False

    def connect(self, **kwargs: object) -> None:
        del kwargs

    def send(self, data: bytes) -> None:
        self.sent.append(data)
        if data == b" " and self._continuation is not None:
            self._chunks.append(self._continuation)
            self._continuation = None

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return self._chunks.pop(0)

    def receive_ready(self) -> bool:
        return bool(self._chunks)

    def close(self) -> None:
        self.closed = True


def _collector(transport) -> DeviceCollector:
    policy = ReadOnlyPolicy()
    return DeviceCollector(
        transport_factory=lambda: transport,
        session_factory=SessionFactory(),
        executor=CommandExecutor(policy=policy, raw_repository=InMemoryRawRepository()),
        policy=policy,
    )


def test_authentication_failure_produces_traceable_command_execution() -> None:
    transport = FailingConnectTransport()
    device = Device(management_address="192.0.2.10", platform_family=PlatformFamily.IOS_XE)

    result = _collector(transport).collect(
        assessment_run_id=uuid4(),
        device=device,
        credentials=SSHCredentials(username="assessment", password="wrong"),
        catalog=COMMAND_CATALOG_V0_1,
    )

    assert len(result.commands) == 1
    execution = result.commands[0].execution
    assert execution.status is CommandExecutionStatus.TRANSPORT_ERROR
    assert execution.error_type == "authentication_failed"
    assert execution.command_key == "system.version"
    assert transport.closed is True


def test_device_catalog_to_show_version_end_to_end_with_fake_transport() -> None:
    transport = SuccessfulTransport()
    device = Device(management_address="192.0.2.10", platform_family=PlatformFamily.IOS_XE)

    result = _collector(transport).collect(
        assessment_run_id=uuid4(),
        device=device,
        credentials=SSHCredentials(username="assessment", password="secret"),
        catalog=COMMAND_CATALOG_V0_1,
    )

    assert result.commands[0].execution.status is CommandExecutionStatus.SUCCESS
    assert result.commands[0].raw_output is not None
    assert transport.sent == [b"show version\n"]
    assert transport.closed is True


def test_paginated_show_version_finishes_as_success_with_full_raw() -> None:
    transport = PaginatedSuccessfulTransport()
    device = Device(management_address="192.0.2.10", platform_family=PlatformFamily.IOS_XE)

    result = _collector(transport).collect(
        assessment_run_id=uuid4(),
        device=device,
        credentials=SSHCredentials(username="assessment", password="secret"),
        catalog=COMMAND_CATALOG_V0_1,
    )

    command_result = result.commands[0]
    assert command_result.execution.status is CommandExecutionStatus.SUCCESS
    assert command_result.raw_output is not None
    assert command_result.raw_output.is_truncated is False
    expected_raw = transport.first_page + transport.final_page
    assert command_result.raw_output.content.encode(command_result.raw_output.encoding) == expected_raw
    assert transport.sent == [b"show version\n", b" "]
    assert transport.closed is True
