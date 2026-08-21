"""Assessment run model."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .base import SCHEMA_VERSION, DomainModel, normalize_utc, utc_now
from .device import DeviceSnapshot
from .enums import AssessmentRunStatus


class AssessmentRun(DomainModel):
    """Auditable execution of the framework against one Device."""

    schema_version: Literal["0.1"] = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    device_id: UUID

    framework_version: str = Field(min_length=1, max_length=64)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: AssessmentRunStatus = AssessmentRunStatus.CREATED

    target_snapshot: DeviceSnapshot
    command_catalog_version: str | None = Field(default=None, max_length=64)
    ruleset_version: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=4096)

    @field_validator(
        "framework_version",
        "command_catalog_version",
        "ruleset_version",
        "error_message",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
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
    def finished_not_before_started(self) -> AssessmentRun:
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must be greater than or equal to started_at")
        return self
