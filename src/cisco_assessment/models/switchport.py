"""Normalized models for ``show interfaces switchport`` observations."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StrictBool,
    field_validator,
    model_validator,
)

from .enums import PlatformFamily

SWITCHPORT_OBSERVATION_SCHEMA_VERSION: Literal["0.1"] = "0.1"


class SwitchportRecord(BaseModel):
    """One immutable per-interface switchport observation.

    Boolean fields are normalized only when the authoritative output makes the
    mapping unambiguous. ``None`` means the fact could not be demonstrated.

    Mode and VLAN-related values intentionally remain open strings in v0.1 so
    valid IOS/IOS-XE tokens are not discarded merely because the framework has
    not observed them before. RAW text and evidence stay outside this model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: PositiveInt
    interface: str = Field(min_length=1, max_length=128)
    switchport_enabled: StrictBool | None
    administrative_mode: str | None = Field(max_length=128)
    operational_mode: str | None = Field(max_length=128)
    access_vlan: str | None = Field(max_length=256)
    native_vlan: str | None = Field(max_length=256)
    allowed_vlans: str | None
    voice_vlan: str | None = Field(max_length=256)
    negotiation_of_trunking: StrictBool | None

    @field_validator("interface")
    @classmethod
    def normalize_interface(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("interface must not be blank")
        return cleaned

    @field_validator(
        "administrative_mode",
        "operational_mode",
        "access_vlan",
        "native_vlan",
        "allowed_vlans",
        "voice_vlan",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SwitchportObservation(BaseModel):
    """Framework-owned normalized snapshot of switchport observations.

    ``interfaces`` preserves authoritative observation order. The model does
    not consult InterfaceObservation, VlanObservation, configuration text or
    any other domain to complete missing switchport facts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = SWITCHPORT_OBSERVATION_SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    interfaces: tuple[SwitchportRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_observation_sequence(self) -> SwitchportObservation:
        ordinals = [record.ordinal for record in self.interfaces]
        expected_ordinals = list(range(1, len(self.interfaces) + 1))
        if ordinals != expected_ordinals:
            raise ValueError(
                "SwitchportObservation ordinals must be contiguous, start at 1, "
                "and match observation order"
            )

        interface_names = [record.interface for record in self.interfaces]
        if len(interface_names) != len(set(interface_names)):
            raise ValueError("SwitchportObservation interface names must be unique")

        return self
