"""Normalized models produced by parser outputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import SCHEMA_VERSION
from .enums import PlatformFamily


class DeviceInfo(BaseModel):
    """Normalized device identity and software facts from ``show version``.

    This model intentionally contains no RAW text or parser metadata. Source
    traceability is carried by ``ParseResult`` in the parser layer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    software_version: str = Field(min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    serial_number: str | None = Field(default=None, min_length=1, max_length=128)
    system_image: str | None = Field(default=None, min_length=1, max_length=512)
    uptime_text: str | None = Field(default=None, min_length=1, max_length=512)
    boot_mode: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator(
        "software_version",
        "hostname",
        "model",
        "serial_number",
        "system_image",
        "uptime_text",
        "boot_mode",
    )
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


class HardwareComponentKind(StrEnum):
    """Normalized physical role without inferring stack topology."""

    CHASSIS = "chassis"
    MODULE = "module"
    COMPONENT = "component"


class HardwareComponent(BaseModel):
    """One physical inventory record reported by ``show inventory``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, min_length=1, max_length=512)
    pid: str | None = Field(default=None, min_length=1, max_length=128)
    vid: str | None = Field(default=None, min_length=1, max_length=64)
    serial_number: str | None = Field(default=None, min_length=1, max_length=128)
    kind: HardwareComponentKind

    @field_validator("name", "description", "pid", "vid", "serial_number")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned


class HardwareInventory(BaseModel):
    """Normalized physical inventory for one IOS/IOS-XE device.

    Stack membership is intentionally not inferred in v0.1; every ``show inventory``
    record is represented only by its physical role and source evidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    chassis: HardwareComponent | None = None
    modules: tuple[HardwareComponent, ...] = ()
    components: tuple[HardwareComponent, ...] = ()

    @property
    def all_components(self) -> tuple[HardwareComponent, ...]:
        chassis = () if self.chassis is None else (self.chassis,)
        return chassis + self.modules + self.components
