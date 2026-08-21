from __future__ import annotations
import socket
from cisco_switch_assessment.collector.exceptions import AuthenticationError, ConnectionLostError, ConnectionTimeoutError, TransportError
from cisco_switch_assessment.collector.transport.base import SSHTimeouts
from cisco_switch_assessment.models import Device

class ParamikoSSHTransport:
    def __init__(self, *, strict_host_key: bool = True) -> None:
        self._strict_host_key = strict_host_key
        self._client = None
        self._channel = None

    def connect(self, device: Device, timeouts: SSHTimeouts) -> None:
        try:
            import paramiko
        except ImportError as exc:
            raise TransportError("paramiko is required for SSH transport") from exc
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy() if self._strict_host_key else paramiko.AutoAddPolicy())
        try:
            client.connect(hostname=device.host, port=device.port, username=device.username, password=device.password, timeout=timeouts.connect, auth_timeout=timeouts.auth, banner_timeout=timeouts.auth, look_for_keys=device.password is None, allow_agent=device.password is None)
            channel = client.invoke_shell()
            channel.settimeout(timeouts.read_poll)
        except paramiko.AuthenticationException as exc:
            client.close(); raise AuthenticationError(f"SSH authentication failed for {device.id}") from exc
        except (socket.timeout, TimeoutError) as exc:
            client.close(); raise ConnectionTimeoutError(f"SSH connection timed out for {device.id}") from exc
        except (paramiko.SSHException, OSError) as exc:
            client.close(); raise TransportError(f"SSH connection failed for {device.id}: {exc}") from exc
        self._client, self._channel = client, channel

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
            data = self._channel.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise ConnectionLostError("SSH channel receive failed") from exc
        if data == b"" and self._channel.closed:
            raise ConnectionLostError("SSH channel closed by remote host")
        return data

    def receive_ready(self) -> bool:
        return bool(self._channel is not None and self._channel.recv_ready())

    def close(self) -> None:
        if self._channel is not None: self._channel.close()
        if self._client is not None: self._client.close()
        self._channel = self._client = None
