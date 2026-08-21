"""Command execution model."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, NonNegativeInt, PositiveInt, field_validator, model_validator

from .base import SCHEMA_VERSION, DomainModel, normalize_utc, utc_now
from .enums import CommandExecutionStatus


class CommandExecution(DomainModel):
    """One attempted command execution within an AssessmentRun.

    This model records execution metadata only. Raw CLI text is intentionally
    stored in RawCommandOutput, preserving the RAW/domain separation.
    """

    schema_version: Literal["0.1"] = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    assessment_run_id: UUID

    command_key: str = Field(min_length=1, max_length=128)
    command: str = Field(min_length=1, max_length=512)
    sequence: PositiveInt

    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    duration_ms: NonNegativeInt | None = None

    status: CommandExecutionStatus = CommandExecutionStatus.PENDING
    error_type: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=4096)

    @field_validator("command_key", "command", "error_type", "error_message")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned

    @field_validator("started_at", "finished_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return normalize_utc(value)

    @model_validator(mode="after")
    def finished_not_before_started(self) -> "CommandExecution":
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must be greater than or equal to started_at")
        return self
