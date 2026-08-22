from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentType
from cisco_assessment.parsers import IOSShowInventoryParser, ParseStatus, build_parser_registry

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ios" / "show_inventory"


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.SYSTEM_INVENTORY.value,
        command="show inventory",
        sequence=2,
    )


def test_parse_show_inventory_preserves_field_to_raw_traceability() -> None:
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
    assert len(result.data.members) == 1
    assert result.data.members[0].pid == "C9300-48P"
    assert result.data.members[0].serial_number == "FOC0000AAAA"
    assert result.data.members[0].component_type is HardwareComponentType.CHASSIS_MEMBER

    power_supply = next(item for item in result.data.all_components if item.pid == "PWR-C1-715WAC")
    transceiver = next(item for item in result.data.all_components if item.pid == "SFP-10G-SR")
    assert power_supply.component_type is HardwareComponentType.OTHER
    assert transceiver.component_type is HardwareComponentType.OTHER

    assert result.trace.parser_id is ParserId.IOS_SHOW_INVENTORY_V1
    assert result.trace.normalized_model is NormalizedModelId.HARDWARE_INVENTORY
    assert result.trace.command_execution_id == execution.id
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == raw.sha256
    assert any(item.field == "chassis.serial_number" for item in result.evidence)
    assert raw.content == content


def test_parse_show_inventory_neutralizes_pager_artifacts_in_derived_view() -> None:
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
    components = result.data.all_components
    assert len(components) == 17
    assert len(result.data.members) == 2

    target = next(component for component in components if component.name == "Gi2/1/2")
    assert target.pid == "GLC-SX-MMD"
    assert target.vid == "V03"
    assert all(warning.code != "inventory_record_incomplete" for warning in result.warnings)

    raw_lines = content.replace("\r\n", "\n").split("\n")
    pager_line_number = next(
        line_number
        for line_number, line in enumerate(raw_lines, start=1)
        if "--More--" in line
    )
    components_evidence = next(item for item in result.evidence if item.field == "components")
    assert components_evidence.line_start <= pager_line_number <= components_evidence.line_end
    assert result.trace.command_execution_id == execution.id
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == original_sha256
    assert raw.content == content
    assert raw.sha256 == original_sha256


def test_registry_resolves_productive_show_inventory_parser() -> None:
    parser = build_parser_registry().resolve(
        ParserId.IOS_SHOW_INVENTORY_V1,
        PlatformFamily.IOS_XE,
    )
    assert isinstance(parser, IOSShowInventoryParser)
