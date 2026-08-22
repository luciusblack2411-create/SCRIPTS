from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentType
from cisco_assessment.parsers import IOSShowInventoryParser, ParseStatus, build_parser_registry

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ios" / "show_inventory"

_LEGACY_EVIDENCE_FIELDS = {
    "chassis",
    "chassis.pid",
    "chassis.serial_number",
    "modules",
    "components",
}

_EXPECTED_17 = (
    (
        "Switch 1",
        "Cisco Catalyst 9300 48 Port PoE+ Switch",
        "C9300-48P",
        "V02",
        "FOC0000AAAA",
        HardwareComponentType.CHASSIS_MEMBER,
        None,
    ),
    (
        "StackPort1/1",
        "StackPort1/1",
        "STACK-T1-50CM",
        "V01",
        "FOC0000A101",
        HardwareComponentType.STACK_CABLE_ENDPOINT,
        "hw:0001",
    ),
    (
        "StackPort1/2",
        "StackPort1/2",
        "STACK-T1-50CM",
        "V01",
        "FOC0000A102",
        HardwareComponentType.STACK_CABLE_ENDPOINT,
        "hw:0001",
    ),
    (
        "Power Supply Module 1",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000A111",
        HardwareComponentType.POWER_SUPPLY,
        None,
    ),
    (
        "Power Supply Module 2",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000A112",
        HardwareComponentType.POWER_SUPPLY,
        None,
    ),
    (
        "Fan Tray",
        "Cisco Catalyst 9300 Fan Module",
        "C9300-FAN",
        "V01",
        "FOC0000A120",
        HardwareComponentType.FAN,
        None,
    ),
    (
        "Gi1/1/1",
        "1000BaseSX SFP",
        "GLC-SX-MMD",
        "V03",
        "FNS0000A201",
        HardwareComponentType.TRANSCEIVER,
        "hw:0001",
    ),
    (
        "Gi1/1/2",
        "1000BaseSX SFP",
        "GLC-SX-MMD",
        "V03",
        "FNS0000A202",
        HardwareComponentType.TRANSCEIVER,
        "hw:0001",
    ),
    (
        "Gi1/1/3",
        "1000BaseLX SFP",
        "GLC-LH-SMD",
        "V03",
        "FNS0000A203",
        HardwareComponentType.TRANSCEIVER,
        "hw:0001",
    ),
    (
        "Gi1/1/4",
        "1000BaseSX SFP",
        "GLC-SX-MMD",
        "V03",
        "FNS0000A204",
        HardwareComponentType.TRANSCEIVER,
        "hw:0001",
    ),
    (
        "Switch 2",
        "Cisco Catalyst 9300 48 Port PoE+ Switch",
        "C9300-48P",
        "V02",
        "FOC0000BBBB",
        HardwareComponentType.CHASSIS_MEMBER,
        None,
    ),
    (
        "Power Supply Module 1/2",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000B111",
        HardwareComponentType.POWER_SUPPLY,
        "hw:0011",
    ),
    (
        "Power Supply Module 2/2",
        "Cisco Catalyst 9300 715WAC Power Supply",
        "PWR-C1-715WAC",
        "V02",
        "DTN0000B112",
        HardwareComponentType.POWER_SUPPLY,
        "hw:0011",
    ),
    (
        "Gi2/1/1",
        "1000BaseSX SFP",
        "GLC-SX-MMD",
        "V03",
        "FNS0000B201",
        HardwareComponentType.TRANSCEIVER,
        "hw:0011",
    ),
    (
        "Gi2/1/2",
        "1000BaseSX SFP",
        "GLC-SX-MMD",
        "V03",
        "FNS0000B202",
        HardwareComponentType.TRANSCEIVER,
        "hw:0011",
    ),
    (
        "Gi2/1/3",
        "1000BaseLX SFP",
        "GLC-LH-SMD",
        "V03",
        "FNS0000B203",
        HardwareComponentType.TRANSCEIVER,
        "hw:0011",
    ),
    (
        "Gi2/1/4",
        "1000BaseSX SFP",
        "GLC-SX-MMD",
        "V03",
        "FNS0000B204",
        HardwareComponentType.TRANSCEIVER,
        "hw:0011",
    ),
)


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.SYSTEM_INVENTORY.value,
        command="show inventory",
        sequence=2,
    )


def test_parse_show_inventory_produces_canonical_v0_2_records() -> None:
    execution = _execution()
    content = (FIXTURES / "c9300_iosxe.txt").read_text(encoding="utf-8")
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.SUCCESS
    assert result.data.schema_version == "0.2"
    assert [record.id for record in result.data.records] == ["hw:0001", "hw:0002", "hw:0003"]
    assert [record.ordinal for record in result.data.records] == [1, 2, 3]
    assert [record.component_type for record in result.data.records] == [
        HardwareComponentType.CHASSIS_MEMBER,
        HardwareComponentType.POWER_SUPPLY,
        HardwareComponentType.TRANSCEIVER,
    ]
    assert all(record.parent_id is None for record in result.data.records)
    assert result.data.records[0].pid == "C9300-48P"
    assert result.data.records[1].pid == "PWR-C1-715WAC"
    assert result.data.records[2].pid == "SFP-10G-SR"

    assert result.trace.parser_id is ParserId.IOS_SHOW_INVENTORY_V1
    assert result.trace.parser_version == "0.2.0"
    assert result.trace.normalized_model is NormalizedModelId.HARDWARE_INVENTORY
    assert result.trace.command_execution_id == execution.id
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == raw.sha256
    evidence_fields = {item.field for item in result.evidence}
    assert "records[0].serial_number" in evidence_fields
    assert evidence_fields.isdisjoint(_LEGACY_EVIDENCE_FIELDS)
    assert all(field == "records" or field.startswith("records[") for field in evidence_fields)
    assert raw.content == content


def test_real_17_record_fixture_preserves_order_classification_and_explicit_parents() -> None:
    execution = _execution()
    content = (FIXTURES / "c9300_iosxe_pager_backspace.txt").read_text(encoding="utf-8")
    assert content.count('NAME: "') == 17
    assert "--More--" in content
    assert "\x08" in content

    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    original_sha256 = raw.sha256

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.SUCCESS
    assert len(result.data.records) == 17
    assert [member.name for member in result.data.members] == ["Switch 1", "Switch 2"]

    for ordinal, (record, expected) in enumerate(zip(result.data.records, _EXPECTED_17), start=1):
        name, description, pid, vid, serial_number, component_type, parent_id = expected
        assert record.ordinal == ordinal
        assert record.id == f"hw:{ordinal:04d}"
        assert record.name == name
        assert record.description == description
        assert record.pid == pid
        assert record.vid == vid
        assert record.serial_number == serial_number
        assert record.component_type is component_type
        assert record.parent_id == parent_id

    assert result.data.records[3].parent_id is None
    assert result.data.records[4].parent_id is None
    assert result.data.records[5].parent_id is None
    assert result.data.children_of_member("hw:0001") == tuple(
        result.data.records[index] for index in (1, 2, 6, 7, 8, 9)
    )
    assert result.data.children_of_member("hw:0011") == tuple(result.data.records[11:17])

    target = result.data.component_by_id("hw:0015")
    assert target.name == "Gi2/1/2"
    assert target.pid == "GLC-SX-MMD"
    assert target.vid == "V03"
    assert target.parent_id == "hw:0011"
    assert all(warning.code != "inventory_record_incomplete" for warning in result.warnings)

    evidence_fields = {item.field for item in result.evidence}
    expected_evidence_fields = {"records"}
    for index, record in enumerate(result.data.records):
        prefix = f"records[{index}]"
        expected_evidence_fields.update(
            {
                prefix,
                f"{prefix}.name",
                f"{prefix}.description",
                f"{prefix}.pid",
                f"{prefix}.vid",
                f"{prefix}.serial_number",
                f"{prefix}.component_type",
            }
        )
        if record.parent_id is not None:
            expected_evidence_fields.add(f"{prefix}.parent_id")
    assert evidence_fields == expected_evidence_fields
    assert evidence_fields.isdisjoint(_LEGACY_EVIDENCE_FIELDS)

    raw_lines = content.replace("\r\n", "\n").split("\n")
    pager_line_number = next(
        line_number
        for line_number, line in enumerate(raw_lines, start=1)
        if "--More--" in line
    )
    target_pid_evidence = next(
        item for item in result.evidence if item.field == "records[14].pid"
    )
    target_parent_evidence = next(
        item for item in result.evidence if item.field == "records[14].parent_id"
    )
    assert target_pid_evidence.line_start == pager_line_number
    assert target_pid_evidence.line_end == pager_line_number
    assert target_parent_evidence.line_start == pager_line_number - 1
    assert target_parent_evidence.line_end == pager_line_number - 1

    assert result.trace.command_execution_id == execution.id
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == original_sha256
    assert raw.content == content
    assert raw.sha256 == original_sha256


def test_explicit_type_patterns_cover_stack_adapter_network_module_and_other() -> None:
    execution = _execution()
    content = (
        'NAME: "Stack Adapter1/1", DESCR: "Cisco Stack Adapter"\n'
        "PID: STACK-ADPT-1, VID: V01, SN: STACK0001\n"
        'NAME: "Network Module 1", DESCR: "Cisco Network Module"\n'
        "PID: C9300-NM-8X, VID: V01, SN: NM0001\n"
        'NAME: "Mystery Widget/2", DESCR: "Unclassified hardware"\n'
        "PID: UNKNOWN-PID, VID: V99, SN: UNKNOWN0001"
    )
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.SUCCESS
    assert [record.component_type for record in result.data.records] == [
        HardwareComponentType.STACK_ADAPTER,
        HardwareComponentType.NETWORK_MODULE,
        HardwareComponentType.OTHER,
    ]
    assert all(record.parent_id is None for record in result.data.records)
    assert result.data.records[2].name == "Mystery Widget/2"
    assert raw.content == content


def test_registry_resolves_productive_show_inventory_parser() -> None:
    parser = build_parser_registry().resolve(
        ParserId.IOS_SHOW_INVENTORY_V1,
        PlatformFamily.IOS_XE,
    )
    assert isinstance(parser, IOSShowInventoryParser)
