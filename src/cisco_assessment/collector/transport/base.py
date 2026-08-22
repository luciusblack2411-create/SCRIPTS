"""SSH transport contracts independent of Cisco CLI behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cisco_assessment.models import Device


@dataclass(frozen=True, slots=True)
class SSHCredentials:
    """Ephemeral SSH credentials; intentionally not part of Device."""

    username: str
    password: str | None = None
    key_filename: str | None = None

    def __post_init__(self) -> None:
        if not self.username.strip():
            raise ValueError("SSH username must not be blank")


@dataclass(frozen=True, slots=True)
class SSHConnectionOptions:
    port: int = 22
    strict_host_key: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535")


@dataclass(frozen=True, slots=True)
class SSHTimeouts:
    connect: float = 10.0
    auth: float = 10.0
    banner: float = 10.0
    channel_read: float = 0.5

    def __post_init__(self) -> None:
        for name, value in (
            ("connect", self.connect),
            ("auth", self.auth),
            ("banner", self.banner),
            ("channel_read", self.channel_read),
        ):
            if value <= 0:
                raise ValueError(f"SSH {name} timeout must be greater than zero")


class SSHTransport(Protocol):
    """Byte-oriented interactive SSH transport."""

    def connect(
        self,
        *,
        device: Device,
        credentials: SSHCredentials,
        options: SSHConnectionOptions,
        timeouts: SSHTimeouts,
    ) -> None: ...

    def send(self, data: bytes) -> None: ...

    def receive(self, max_bytes: int = 65535) -> bytes: ...

    def receive_ready(self) -> bool: ...

    def close(self) -> None: ...
