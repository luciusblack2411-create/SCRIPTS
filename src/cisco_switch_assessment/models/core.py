from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4


class Platform(StrEnum):
    IOS = "ios"
    IOS_XE = "ios-xe"
    NX_OS = "nx-os"


class CommandExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"
    AUTHORIZATION_FAILED = "authorization_failed"
    POLICY_REJECTED = "policy_rejected"
    FAILED = "failed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    host: str
    platform: Platform
    username: str
    password: str | None = None
    port: int = 22

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("device id must not be empty")
        if not self.host.strip():
            raise ValueError("device host must not be empty")
        if not self.username.strip():
            raise ValueError("device username must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("device port must be between 1 and 65535")


@dataclass(frozen=True, slots=True)
class CommandExecution:
    id: UUID
    assessment_run_id: str
    device_id: str
    command_id: str
    status: CommandExecutionStatus
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    raw_output_id: UUID | None = None

    @property
    def duration_ms(self) -> int:
        return max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))

    @classmethod
    def new_id(cls) -> UUID:
        return uuid4()


@dataclass(frozen=True, slots=True)
class RawCommandOutput:
    id: UUID
    command_execution_id: UUID
    storage_path: Path
    size_bytes: int
    sha256: str
    captured_at: datetime

    @classmethod
    def new_id(cls) -> UUID:
        return uuid4()
