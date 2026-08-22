"""Paramiko-backed SSH transport implementation."""

from __future__ import annotations

import importlib
import socket
from types import ModuleType
from typing import Any

from cisco_assessment.collector.exceptions import (
    AuthenticationError,
    ConnectionLostError,
    ConnectionTimeoutError,
    TransportError,
)
from cisco_assessment.collector.transport.base import (
    SSHConnectionOptions,
    SSHCredentials,
    SSHTimeouts,
)
from cisco_assessment.models import Device


class ParamikoSSHTransport:
    """Thin Paramiko adapter; no Cisco-specific command knowledge lives here."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._channel: Any | None = None

    def connect(
        self,
        *,
        device: Device,
        credentials: SSHCredentials,
        options: SSHConnectionOptions,
        timeouts: SSHTimeouts,
    ) -> None:
        paramiko = self._load_paramiko()
        client: Any = paramiko.SSHClient()
        client.load_system_host_keys()
        policy: Any = (
            paramiko.RejectPolicy() if options.strict_host_key else paramiko.AutoAddPolicy()
        )
        client.set_missing_host_key_policy(policy)

        try:
            client.connect(
                hostname=device.management_address,
                port=options.port,
                username=credentials.username,
                password=credentials.password,
                key_filename=credentials.key_filename,
                timeout=timeouts.connect,
                auth_timeout=timeouts.auth,
                banner_timeout=timeouts.banner,
                look_for_keys=credentials.key_filename is None and credentials.password is None,
                allow_agent=credentials.key_filename is None and credentials.password is None,
            )
            channel: Any = client.invoke_shell()
            channel.settimeout(timeouts.channel_read)
        except paramiko.AuthenticationException as exc:
            client.close()
            raise AuthenticationError(
                f"SSH authentication failed for device {device.id}"
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            client.close()
            raise ConnectionTimeoutError(
                f"SSH connection timed out for device {device.id}"
            ) from exc
        except (paramiko.SSHException, OSError) as exc:
            client.close()
            raise TransportError(f"SSH connection failed for device {device.id}: {exc}") from exc

        self._client = client
        self._channel = channel

    def send(self, data: bytes) -> None:
        if self._channel is None:
            raise ConnectionLostError("SSH channel is not open")
        try:
            self._channel.sendall(data)
        except OSError as exc:
            raise ConnectionLostError("SSH channel send failed") from exc

    def receive(self, max_bytes: int = 65535) -> bytes:
        if self._channel is None:
            raise ConnectionLostError("SSH channel is not open")
        try:
            data: bytes = self._channel.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise ConnectionLostError("SSH channel receive failed") from exc
        if data == b"" and bool(self._channel.closed):
            raise ConnectionLostError("SSH channel closed by remote host")
        return data

    def receive_ready(self) -> bool:
        return bool(self._channel is not None and self._channel.recv_ready())

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
        if self._client is not None:
            self._client.close()
        self._channel = None
        self._client = None

    @staticmethod
    def _load_paramiko() -> Any:
        try:
            module: ModuleType = importlib.import_module("paramiko")
        except ImportError as exc:
            raise TransportError("paramiko is required for SSH transport") from exc
        return module
