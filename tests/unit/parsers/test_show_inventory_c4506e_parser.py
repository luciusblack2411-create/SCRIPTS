from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentType
from cisco_assessment.parsers import IOSShowInventoryParser, ParseStatus

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "ios"
    / "show_inventory"
    / "c4506e_ios_real_sanitized.raw"
)

EXPECTED_SHA256 = (
    "a7f02f982177caaa361d9dfe84265d18d699c17e3833ca2fe1c077d3541f6b27"
)

EXPECTED_NAMES = (
    "Switch System",
    "Supervisor(slot 1)",
    "Linecard(slot 2)",
    "Linecard(slot 3)",
    "Linecard(slot 4)",
    "GigabitEthernet4/1",
    "GigabitEthernet4/2",
    "GigabitEthernet4/3",
    "GigabitEthernet4/4",
    "GigabitEthernet4/5",
    "FanTray 1",
    "Power Supply 1",
    "Power Supply 2",
)

EXPECTED_TYPES = (
    HardwareComponentType.CHASSIS_MEMBER,
    HardwareComponentType.SUPERVISOR,
    HardwareComponentType.LINE_CARD,
    HardwareComponentType.LINE_CARD,
    HardwareComponentType.LINE_CARD,
    HardwareComponentType.TRANSCEIVER,
    HardwareComponentType.TRANSCEIVER,
    HardwareComponentType.TRANSCEIVER,
    HardwareComponentType.TRANSCEIVER,
    HardwareComponentType.TRANSCEIVER,
    HardwareComponentType.FAN,
    HardwareComponentType.POWER_SUPPLY,
    HardwareComponentType.POWER_SUPPLY,
)


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.SYSTEM_INVENTORY.value,
        command="show inventory",
        sequence=2,
    )


def _line_number(content: str, needle: str) -> int:
    raw_lines = content.replace("\r\n", "\n").split("\n")
    return next(
        line_number
        for line_number, line in enumerate(raw_lines, start=1)
        if needle in line
    )


def test_c4506e_real_fixture_normalizes_physical_roles_and_slot_parent() -> None:
    fixture_bytes = FIXTURE.read_bytes()
    assert sha256(fixture_bytes).hexdigest() == EXPECTED_SHA256
    content = fixture_bytes.decode("utf-8")

    execution = _execution()
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=content,
    )
    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS,
    )

    assert result.status is ParseStatus.SUCCESS
    assert result.trace.parser_id is ParserId.IOS_SHOW_INVENTORY_V1
    assert result.trace.parser_version == "0.3.0"
    assert result.trace.normalized_model is NormalizedModelId.HARDWARE_INVENTORY
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == EXPECTED_SHA256

    records = result.data.records
    assert result.data.schema_version == "0.3"
    assert tuple(record.name for record in records) == EXPECTED_NAMES
    assert tuple(record.component_type for record in records) == EXPECTED_TYPES
    assert tuple(record.ordinal for record in records) == tuple(range(1, 14))
    assert tuple(record.id for record in records) == tuple(
        f"hw:{ordinal:04d}" for ordinal in range(1, 14)
    )
    assert tuple(record.parent_id for record in records) == (
        None,
        None,
        None,
        None,
        None,
        "hw:0005",
        "hw:0005",
        "hw:0005",
        "hw:0005",
        "hw:0005",
        None,
        None,
        None,
    )
    assert tuple(member.name for member in result.data.members) == ("Switch System",)

    supervisor = records[1]
    assert supervisor.pid == "WS-X45-SUP6L-E"
    assert supervisor.component_type is HardwareComponentType.SUPERVISOR
    assert supervisor.parent_id is None

    slot_4_owner = records[4]
    assert slot_4_owner.pid == "WS-X4306-GB"
    assert slot_4_owner.component_type is HardwareComponentType.LINE_CARD
    assert slot_4_owner.parent_id is None

    owner_line = _line_number(content, 'NAME: "Linecard(slot 4)"')
    for index, port in enumerate(range(1, 6), start=5):
        child_line = _line_number(content, f'NAME: "GigabitEthernet4/{port}"')
        parent_evidence = tuple(
            item
            for item in result.evidence
            if item.field == f"records[{index}].parent_id"
        )
        assert {
            (item.extractor, item.line_start, item.line_end)
            for item in parent_evidence
        } == {
            ("modular_interface_slot_pattern", child_line, child_line),
            ("unique_slot_owner_name_pattern", owner_line, owner_line),
        }

    assert raw.content == content
    assert raw.sha256 == EXPECTED_SHA256
    assert fixture_bytes == FIXTURE.read_bytes()


def test_c4506e_slot_parent_stays_unknown_when_slot_owner_is_ambiguous() -> None:
    content = (
        'NAME: "Supervisor(slot 4)", DESCR: "Supervisor module"\n'
        "PID: WS-X45-SUP6L-E, VID: V06, SN: SUP0001\n"
        'NAME: "Linecard(slot 4)", DESCR: "1000BaseX (GBIC) module"\n'
        "PID: WS-X4306-GB, VID: V12, SN: LC0001\n"
        'NAME: "GigabitEthernet4/1", DESCR: "1000BaseSX"\n'
        "PID: Unspecified, VID: , SN: OPTIC0001"
    )
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS,
    )

    assert tuple(record.component_type for record in result.data.records) == (
        HardwareComponentType.SUPERVISOR,
        HardwareComponentType.LINE_CARD,
        HardwareComponentType.TRANSCEIVER,
    )
    assert result.data.records[2].parent_id is None
    assert all(item.field != "records[2].parent_id" for item in result.evidence)


def test_modular_interface_requires_positive_optic_evidence() -> None:
    content = (
        'NAME: "Linecard(slot 2)", DESCR: "10/100/1000BaseT copper module"\n'
        "PID: WS-X4648-RJ45V+E, VID: V06, SN: LC0002\n"
        'NAME: "GigabitEthernet2/1", DESCR: "1000BaseT"\n'
        "PID: Unspecified, VID: , SN: PORT0001"
    )
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS,
    )

    assert result.data.records[0].component_type is HardwareComponentType.LINE_CARD
    assert result.data.records[1].component_type is HardwareComponentType.OTHER
    assert result.data.records[1].parent_id is None
