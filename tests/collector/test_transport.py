from __future__ import annotations

import socket
import sys
from types import SimpleNamespace

import pytest

from cisco_assessment.collector.exceptions import AuthenticationError, ConnectionTimeoutError
from cisco_assessment.collector.transport import (
    ParamikoSSHTransport,
    SSHConnectionOptions,
    SSHCredentials,
    SSHTimeouts,
)
from cisco_assessment.models import Device, PlatformFamily


class FakeAuthenticationException(Exception):
    pass


class FakeSSHException(Exception):
    pass


class FakePolicy:
    pass


class FakeClient:
    connect_error: Exception | None = None
    last_kwargs: dict[str, object] | None = None

    def load_system_host_keys(self) -> None:
        pass

    def set_missing_host_key_policy(self, policy: object) -> None:
        del policy

    def connect(self, **kwargs: object) -> None:
        type(self).last_kwargs = kwargs
        if type(self).connect_error is not None:
            raise type(self).connect_error

    def invoke_shell(self):
        return SimpleNamespace(settimeout=lambda value: None)

    def close(self) -> None:
        pass


def _fake_paramiko() -> SimpleNamespace:
    return SimpleNamespace(
        SSHClient=FakeClient,
        RejectPolicy=FakePolicy,
        AutoAddPolicy=FakePolicy,
        AuthenticationException=FakeAuthenticationException,
        SSHException=FakeSSHException,
    )


def _device() -> Device:
    return Device(management_address="192.0.2.10", platform_family=PlatformFamily.IOS)


def test_paramiko_transport_uses_device_and_ephemeral_credentials(monkeypatch) -> None:
    FakeClient.connect_error = None
    monkeypatch.setitem(sys.modules, "paramiko", _fake_paramiko())
    transport = ParamikoSSHTransport()

    transport.connect(
        device=_device(),
        credentials=SSHCredentials(username="assessment", password="secret"),
        options=SSHConnectionOptions(port=2222, strict_host_key=True),
        timeouts=SSHTimeouts(connect=3, auth=4, banner=5, channel_read=1),
    )

    assert FakeClient.last_kwargs is not None
    assert FakeClient.last_kwargs["hostname"] == "192.0.2.10"
    assert FakeClient.last_kwargs["port"] == 2222
    assert FakeClient.last_kwargs["username"] == "assessment"
    assert FakeClient.last_kwargs["password"] == "secret"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FakeAuthenticationException("no"), AuthenticationError),
        (socket.timeout("late"), ConnectionTimeoutError),
    ],
)
def test_paramiko_transport_maps_connection_errors(monkeypatch, error, expected) -> None:
    FakeClient.connect_error = error
    monkeypatch.setitem(sys.modules, "paramiko", _fake_paramiko())
    transport = ParamikoSSHTransport()

    with pytest.raises(expected):
        transport.connect(
            device=_device(),
            credentials=SSHCredentials(username="assessment", password="secret"),
            options=SSHConnectionOptions(),
            timeouts=SSHTimeouts(),
        )
