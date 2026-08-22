from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    HARDWARE_INVENTORY_SCHEMA_VERSION,
    HardwareComponent,
    HardwareComponentKind,
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
    PlatformFamily,
    hardware_inventory_record_id,
)


def _record(
    ordinal: int,
    *,
    name: str,
    component_type: HardwareComponentType,
    parent_id: str | None = None,
    description: str = "Observed component",
    pid: str = "PID-1",
    vid: str = "V01",
    serial_number: str = "SERIAL-1",
) -> HardwareInventoryRecord:
    return HardwareInventoryRecord(
        ordinal=ordinal,
        name=name,
        description=description,
        pid=pid,
        vid=vid,
        serial_number=serial_number,
        component_type=component_type,
        parent_id=parent_id,
    )


def test_multiple_members_and_known_or_unknown_parent_relationships() -> None:
    member_1 = _record(
        1,
        name="Switch 1",
        component_type=HardwareComponentType.CHASSIS_MEMBER,
    )
    child_1 = _record(
        2,
        name="Gi1/1/1",
        component_type=HardwareComponentType.TRANSCEIVER,
        parent_id=member_1.id,
    )
    unknown_parent = _record(
        3,
        name="Fan Tray",
        component_type=HardwareComponentType.FAN,
        parent_id=None,
    )
    member_2 = _record(
        4,
        name="Switch 2",
        component_type=HardwareComponentType.CHASSIS_MEMBER,
    )
    child_2 = _record(
        5,
        name="Gi2/1/1",
        component_type=HardwareComponentType.TRANSCEIVER,
        parent_id=member_2.id,
    )

    inventory = HardwareInventory(
        platform=PlatformFamily.IOS_XE,
        records=(child_2, member_1, unknown_parent, child_1, member_2),
    )

    assert inventory.schema_version == HARDWARE_INVENTORY_SCHEMA_VERSION == "0.2"
    assert [record.id for record in inventory.records] == [
        "hw:0001",
        "hw:0002",
        "hw:0003",
        "hw:0004",
        "hw:0005",
    ]
    assert [member.id for member in inventory.members] == ["hw:0001", "hw:0004"]
    assert inventory.children_of_member(member_1.id) == (child_1,)
    assert inventory.children_of_member(member_2.id) == (child_2,)
    assert inventory.component_by_id(unknown_parent.id).parent_id is None


def test_all_component_types_are_representable() -> None:
    records = tuple(
        _record(
            ordinal,
            name=component_type.value,
            component_type=component_type,
        )
        for ordinal, component_type in enumerate(HardwareComponentType, start=1)
    )

    inventory = HardwareInventory(platform=PlatformFamily.IOS_XE, records=records)

    assert {record.component_type for record in inventory.records} == set(HardwareComponentType)


def test_record_ids_are_deterministic_and_duplicate_or_inconsistent_ids_are_rejected() -> None:
    first = _record(1, name="A", component_type=HardwareComponentType.OTHER)
    seventeenth = _record(17, name="B", component_type=HardwareComponentType.OTHER)

    assert first.id == hardware_inventory_record_id(1) == "hw:0001"
    assert seventeenth.id == hardware_inventory_record_id(17) == "hw:0017"

    duplicate = _record(1, name="Duplicate", component_type=HardwareComponentType.OTHER)
    with pytest.raises(ValidationError, match="IDs must be unique"):
        HardwareInventory(
            platform=PlatformFamily.IOS_XE,
            records=(first, duplicate),
        )

    with pytest.raises(ValidationError, match="id must be"):
        HardwareInventoryRecord(
            ordinal=2,
            id="hw:9999",
            name="Wrong ID",
            component_type=HardwareComponentType.OTHER,
        )

    with pytest.raises(ValidationError, match="ordinals must be contiguous"):
        HardwareInventory(
            platform=PlatformFamily.IOS_XE,
            records=(first, seventeenth),
        )


def test_invalid_parent_references_cycles_and_member_parent_are_rejected() -> None:
    orphan = _record(
        1,
        name="Orphan",
        component_type=HardwareComponentType.OTHER,
        parent_id="hw:9999",
    )
    with pytest.raises(ValidationError, match="does not reference a record"):
        HardwareInventory(platform=PlatformFamily.IOS_XE, records=(orphan,))

    cycle_a = _record(
        1,
        name="Cycle A",
        component_type=HardwareComponentType.OTHER,
        parent_id="hw:0002",
    )
    cycle_b = _record(
        2,
        name="Cycle B",
        component_type=HardwareComponentType.OTHER,
        parent_id="hw:0001",
    )
    with pytest.raises(ValidationError, match="must not contain cycles"):
        HardwareInventory(
            platform=PlatformFamily.IOS_XE,
            records=(cycle_a, cycle_b),
        )

    with pytest.raises(ValidationError, match="chassis_member records cannot have parent_id"):
        _record(
            1,
            name="Invalid member",
            component_type=HardwareComponentType.CHASSIS_MEMBER,
            parent_id="hw:0002",
        )


def test_record_preserves_inventory_fields_and_other_is_explicit_and_immutable() -> None:
    record = HardwareInventoryRecord(
        ordinal=1,
        name="  Unknown Widget  ",
        description="  Unclassified hardware  ",
        pid="  UNKNOWN-PID  ",
        vid="  V99  ",
        serial_number="  SERIAL-XYZ  ",
        component_type=HardwareComponentType.OTHER,
    )

    assert record.name == "Unknown Widget"
    assert record.description == "Unclassified hardware"
    assert record.pid == "UNKNOWN-PID"
    assert record.vid == "V99"
    assert record.serial_number == "SERIAL-XYZ"
    assert record.component_type is HardwareComponentType.OTHER

    with pytest.raises(ValidationError):
        setattr(record, "name", "Changed")


OBSERVED_17 = (
    ("Switch 1", "Cisco Catalyst 9300 48 Port PoE+ Switch", "C9300-48P", "V02", "FOC0000AAAA"),
    ("StackPort1/1", "StackPort1/1", "STACK-T1-50CM", "V01", "FOC0000A101"),
    ("StackPort1/2", "StackPort1/2", "STACK-T1-50CM", "V01", "FOC0000A102"),
    (
        "Power Supply Module 1",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000A111",
    ),
    (
        "Power Supply Module 2",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000A112",
    ),
    ("Fan Tray", "Cisco Catalyst 9300 Fan Module", "C9300-FAN", "V01", "FOC0000A120"),
    ("Gi1/1/1", "1000BaseSX SFP", "GLC-SX-MMD", "V03", "FNS0000A201"),
    ("Gi1/1/2", "1000BaseSX SFP", "GLC-SX-MMD", "V03", "FNS0000A202"),
    ("Gi1/1/3", "1000BaseLX SFP", "GLC-LH-SMD", "V03", "FNS0000A203"),
    ("Gi1/1/4", "1000BaseSX SFP", "GLC-SX-MMD", "V03", "FNS0000A204"),
    ("Switch 2", "Cisco Catalyst 9300 48 Port PoE+ Switch", "C9300-48P", "V02", "FOC0000BBBB"),
    (
        "Power Supply Module 1/2",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000B111",
    ),
    (
        "Power Supply Module 2/2",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000B112",
    ),
    ("Gi2/1/1", "1000BaseSX SFP", "GLC-SX-MMD", "V03", "FNS0000B201"),
    ("Gi2/1/2", "1000BaseSX SFP", "GLC-SX-MMD", "V03", "FNS0000B202"),
    ("Gi2/1/3", "1000BaseLX SFP", "GLC-LH-SMD", "V03", "FNS0000B203"),
    ("Gi2/1/4", "1000BaseSX SFP", "GLC-SX-MMD", "V03", "FNS0000B204"),
)


def test_inventory_can_represent_all_17_observed_records_without_loss() -> None:
    records = tuple(
        HardwareInventoryRecord(
            ordinal=ordinal,
            name=name,
            description=description,
            pid=pid,
            vid=vid,
            serial_number=serial_number,
            component_type=(
                HardwareComponentType.CHASSIS_MEMBER
                if name in {"Switch 1", "Switch 2"}
                else HardwareComponentType.OTHER
            ),
            parent_id=None,
        )
        for ordinal, (name, description, pid, vid, serial_number) in enumerate(
            OBSERVED_17,
            start=1,
        )
    )

    inventory = HardwareInventory(platform=PlatformFamily.IOS_XE, records=records)

    assert len(inventory.all_components) == 17
    assert [record.id for record in inventory.records] == [
        hardware_inventory_record_id(index) for index in range(1, 18)
    ]
    assert [member.name for member in inventory.members] == ["Switch 1", "Switch 2"]
    assert [
        (
            record.name,
            record.description,
            record.pid,
            record.vid,
            record.serial_number,
        )
        for record in inventory.records
    ] == list(OBSERVED_17)

    target = inventory.component_by_id("hw:0015")
    assert target.name == "Gi2/1/2"
    assert target.pid == "GLC-SX-MMD"
    assert target.vid == "V03"
    assert target.parent_id is None


def test_v0_1_shape_has_a_non_ambiguous_migration_to_canonical_records() -> None:
    legacy_chassis = HardwareComponent(
        name="Switch 1",
        description="Cisco switch",
        pid="C9300-48P",
        vid="V02",
        serial_number="FOC0000AAAA",
        kind=HardwareComponentKind.CHASSIS,
    )
    legacy_module = HardwareComponent(
        name="Power Supply Module 1",
        description="Cisco power supply",
        pid="PWR-C1-715WAC",
        vid="V02",
        serial_number="DTN0000A111",
        kind=HardwareComponentKind.MODULE,
    )

    inventory = HardwareInventory(
        schema_version="0.1",
        platform=PlatformFamily.IOS_XE,
        chassis=legacy_chassis,
        modules=(legacy_module,),
    )

    assert inventory.schema_version == "0.2"
    assert [record.component_type for record in inventory.records] == [
        HardwareComponentType.CHASSIS_MEMBER,
        HardwareComponentType.OTHER,
    ]
    assert all(record.parent_id is None for record in inventory.records)

    payload = inventory.model_dump(mode="json")
    assert set(payload) == {"schema_version", "vendor", "platform", "records"}
    assert "chassis" not in payload
    assert "modules" not in payload
    assert "components" not in payload
    assert HardwareInventory.model_validate_json(inventory.model_dump_json()) == inventory
