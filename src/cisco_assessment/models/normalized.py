"""Normalized models produced by parser outputs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)

from .base import SCHEMA_VERSION
from .enums import PlatformFamily

HARDWARE_INVENTORY_SCHEMA_VERSION: Literal["0.2"] = "0.2"


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


class HardwareComponentType(StrEnum):
    """Normalized physical role for one ``show inventory`` record."""

    CHASSIS_MEMBER = "chassis_member"
    POWER_SUPPLY = "power_supply"
    TRANSCEIVER = "transceiver"
    STACK_ADAPTER = "stack_adapter"
    STACK_CABLE_ENDPOINT = "stack_cable_endpoint"
    NETWORK_MODULE = "network_module"
    FAN = "fan"
    OTHER = "other"


def hardware_inventory_record_id(ordinal: int) -> str:
    """Return the deterministic snapshot-local ID for one physical record."""

    if ordinal < 1:
        raise ValueError("ordinal must be greater than or equal to 1")
    return f"hw:{ordinal:04d}"


class HardwareInventoryRecord(BaseModel):
    """One immutable physical record reported by ``show inventory``.

    ``ordinal`` is the one-based record position in the parser's logical
    inventory sequence. It is structural normalized data, not RAW evidence.
    RAW IDs, parser metadata and line numbers remain in ParseResult/FieldEvidence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: PositiveInt
    id: str = Field(default="", pattern=r"^hw:\d{4,}$")
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=512)
    pid: str | None = Field(default=None, max_length=128)
    vid: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=128)
    component_type: HardwareComponentType
    parent_id: str | None = Field(default=None, pattern=r"^hw:\d{4,}$")

    @model_validator(mode="before")
    @classmethod
    def populate_and_validate_deterministic_id(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        ordinal = data.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            return data
        expected = hardware_inventory_record_id(ordinal)
        supplied = data.get("id")
        if supplied is not None and supplied != expected:
            raise ValueError(f"id must be {expected!r} for ordinal {ordinal}")
        return {**data, "id": expected}

    @field_validator("name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("description", "pid", "vid", "serial_number")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def chassis_member_is_root(self) -> HardwareInventoryRecord:
        if (
            self.component_type is HardwareComponentType.CHASSIS_MEMBER
            and self.parent_id is not None
        ):
            raise ValueError("chassis_member records cannot have parent_id")
        return self


class HardwareInventory(BaseModel):
    """Canonical Hardware Inventory normalized contract v0.2.

    ``records`` is the only construction and serialization contract for physical
    inventory. Parent relationships are optional and must be explicit:
    ``parent_id=None`` means source evidence did not prove membership. RAW text,
    parser metadata and source line numbers remain outside this model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.2"] = HARDWARE_INVENTORY_SCHEMA_VERSION
    vendor: Literal["Cisco"] = "Cisco"
    platform: PlatformFamily
    records: tuple[HardwareInventoryRecord, ...] = Field(min_length=1)

    @field_validator("records")
    @classmethod
    def records_are_in_deterministic_order(
        cls,
        records: tuple[HardwareInventoryRecord, ...],
    ) -> tuple[HardwareInventoryRecord, ...]:
        return tuple(sorted(records, key=lambda item: item.ordinal))

    @model_validator(mode="after")
    def validate_record_graph(self) -> HardwareInventory:
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("HardwareInventory record IDs must be unique")

        ordinals = [record.ordinal for record in self.records]
        if ordinals != list(range(1, len(self.records) + 1)):
            raise ValueError("HardwareInventory ordinals must be contiguous and start at 1")

        ids_set = set(ids)
        for record in self.records:
            if record.parent_id is not None and record.parent_id not in ids_set:
                raise ValueError(
                    f"parent_id {record.parent_id!r} for {record.id!r} does not reference a record"
                )

        parent_by_id = {record.id: record.parent_id for record in self.records}
        for start_id in ids:
            seen: set[str] = set()
            current: str | None = start_id
            while current is not None:
                if current in seen:
                    raise ValueError(
                        "HardwareInventory parent relationships must not contain cycles"
                    )
                seen.add(current)
                current = parent_by_id[current]

        return self

    @property
    def all_components(self) -> tuple[HardwareInventoryRecord, ...]:
        """Return every canonical physical record in deterministic order."""

        return self.records

    @property
    def members(self) -> tuple[HardwareInventoryRecord, ...]:
        """Return all chassis/stack-member roots in deterministic order."""

        return tuple(
            record
            for record in self.records
            if record.component_type is HardwareComponentType.CHASSIS_MEMBER
        )

    def component_by_id(self, component_id: str) -> HardwareInventoryRecord:
        """Return one canonical record by deterministic ID."""

        for record in self.records:
            if record.id == component_id:
                return record
        raise KeyError(component_id)

    def children_of(self, parent_id: str) -> tuple[HardwareInventoryRecord, ...]:
        """Return direct children of an existing record in deterministic order."""

        self.component_by_id(parent_id)
        return tuple(record for record in self.records if record.parent_id == parent_id)

    def children_of_member(self, member_id: str) -> tuple[HardwareInventoryRecord, ...]:
        """Return direct children of a chassis/stack member."""

        member = self.component_by_id(member_id)
        if member.component_type is not HardwareComponentType.CHASSIS_MEMBER:
            raise ValueError(f"{member_id!r} does not reference a chassis_member")
        return self.children_of(member_id)
