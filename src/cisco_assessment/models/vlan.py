"""Normalized models for ``show vlan brief`` observations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import PlatformFamily

VLAN_OBSERVATION_SCHEMA_VERSION: Literal["0.1"] = "0.1"

VlanId = Annotated[int, Field(strict=True, ge=1, le=4094)]
VlanOrdinal = Annotated[int, Field(strict=True, ge=1)]


class VlanStatus(StrEnum):
    """Normalized status values supported by VLAN Observation v0.1."""

    ACTIVE = "active"
    SUSPENDED = "suspend"
    ACTIVE_UNSUPPORTED = "act/unsup"
    UNKNOWN = "unknown"


class VlanRecord(BaseModel):
    """One immutable VLAN observation from ``show vlan brief``.

    ``ports`` has three deliberate states:
    - a non-empty tuple when the authoritative output reports associated ports;
    - an empty tuple when the VLAN is observed with no ports listed;
    - ``None`` when port association cannot be demonstrated.

    RAW text, source lines, parser metadata and evidence remain outside this
    normalized contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: VlanOrdinal
    vlan_id: VlanId
    name: str | None
    status: VlanStatus
    ports: tuple[str, ...] | None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("ports")
    @classmethod
    def normalize_ports(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None

        normalized: list[str] = []
        for port in value:
            cleaned = port.strip()
            if not cleaned:
                raise ValueError("VlanRecord ports must not contain blank values")
            normalized.append(cleaned)

        if len(normalized) != len(set(normalized)):
            raise ValueError("VlanRecord ports must be unique within the VLAN")

        return tuple(normalized)


class VlanObservation(BaseModel):
    """Framework-owned normalized snapshot of ``show vlan brief``.

    ``vlans`` preserves authoritative observation order. The model does not
    consult InterfaceObservation or any other domain to complete VLAN facts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = VLAN_OBSERVATION_SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    vlans: tuple[VlanRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_observation_sequence(self) -> VlanObservation:
        ordinals = [record.ordinal for record in self.vlans]
        expected_ordinals = list(range(1, len(self.vlans) + 1))
        if ordinals != expected_ordinals:
            raise ValueError(
                "VlanObservation ordinals must be contiguous, start at 1, "
                "and match observation order"
            )

        vlan_ids = [record.vlan_id for record in self.vlans]
        if len(vlan_ids) != len(set(vlan_ids)):
            raise ValueError("VlanObservation VLAN IDs must be unique")

        return self
