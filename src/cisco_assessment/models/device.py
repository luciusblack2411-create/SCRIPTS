"""Persistent device identity and assessment-time target snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .base import SCHEMA_VERSION, DomainModel, normalize_utc, utc_now
from .enums import PlatformFamily


class DeviceSnapshot(DomainModel):
    """Immutable-by-convention view of the assessment target at run start."""

    management_address: str = Field(min_length=1, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    platform_family: PlatformFamily = PlatformFamily.UNKNOWN

    @field_validator("management_address", "hostname")
    @classmethod
    def strip_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


class Device(DomainModel):
    """Stable identity for a managed Cisco device.

    Observed facts such as serial number, software version and uptime do not
    belong here; those will live in normalized assessment data (DeviceInfo).
    """

    schema_version: Literal["0.1"] = SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)

    management_address: str = Field(min_length=1, max_length=255)
    hostname: str | None = Field(default=None, max_length=255)
    vendor: Literal["cisco"] = "cisco"
    platform_family: PlatformFamily = PlatformFamily.UNKNOWN

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("management_address", "hostname")
    @classmethod
    def strip_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return normalize_utc(value)

    @model_validator(mode="after")
    def updated_not_before_created(self) -> "Device":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be greater than or equal to created_at")
        return self

    def snapshot(self) -> DeviceSnapshot:
        """Capture the target metadata that must remain stable for a run."""
        return DeviceSnapshot(
            management_address=self.management_address,
            hostname=self.hostname,
            platform_family=self.platform_family,
        )
