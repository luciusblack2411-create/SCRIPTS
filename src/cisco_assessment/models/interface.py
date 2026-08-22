"""Normalized interface-observation models for the Genie extraction spike."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import PlatformFamily

INTERFACE_OBSERVATION_SCHEMA_VERSION: Literal["0.1"] = "0.1"


class InterfaceStatusRecord(BaseModel):
    """One normalized row from ``show interfaces status``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    interface: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=256)
    status: str = Field(min_length=1, max_length=64)
    vlan: str = Field(min_length=1, max_length=64)
    duplex: str = Field(min_length=1, max_length=64)
    speed: str = Field(min_length=1, max_length=64)
    media_type: str | None = Field(default=None, max_length=256)

    @field_validator("interface", "status", "vlan", "duplex", "speed")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned

    @field_validator("description", "media_type")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class InterfaceObservation(BaseModel):
    """Framework-owned normalized snapshot of interface status rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = INTERFACE_OBSERVATION_SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    interfaces: tuple[InterfaceStatusRecord, ...] = Field(min_length=1)
