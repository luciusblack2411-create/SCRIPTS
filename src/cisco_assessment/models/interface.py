"""Normalized models for ``show interfaces status`` observations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

from .enums import PlatformFamily

INTERFACE_OBSERVATION_SCHEMA_VERSION: Literal["0.1"] = "0.1"


class InterfaceStatusRecord(BaseModel):
    """One immutable normalized observation from ``show interfaces status``.

    Operational tokens such as status, VLAN, duplex and speed intentionally
    remain strings in v0.1. IOS/IOS-XE can expose values beyond the examples
    known to the framework, and normalized data must not discard a valid
    observed value merely because it is new to our current vocabulary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: PositiveInt
    interface: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=256)
    status: str = Field(min_length=1, max_length=64)
    vlan: str = Field(min_length=1, max_length=64)
    duplex: str = Field(min_length=1, max_length=64)
    speed: str = Field(min_length=1, max_length=64)
    media_type: str | None = Field(default=None, max_length=256)

    @field_validator("interface", "status", "vlan", "duplex", "speed")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned

    @field_validator("description", "media_type")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class InterfaceObservation(BaseModel):
    """Framework-owned normalized snapshot of interface status observations.

    ``interfaces`` preserves parser observation order. ``ordinal`` is structural
    normalized data used to make that order explicit; RAW, FieldEvidence and
    parser metadata remain outside this model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = INTERFACE_OBSERVATION_SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    interfaces: tuple[InterfaceStatusRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_observation_sequence(self) -> InterfaceObservation:
        ordinals = [record.ordinal for record in self.interfaces]
        expected_ordinals = list(range(1, len(self.interfaces) + 1))
        if ordinals != expected_ordinals:
            raise ValueError(
                "InterfaceObservation ordinals must be contiguous, start at 1, "
                "and match observation order"
            )

        interface_names = [record.interface for record in self.interfaces]
        if len(interface_names) != len(set(interface_names)):
            raise ValueError("InterfaceObservation interface names must be unique")

        return self
