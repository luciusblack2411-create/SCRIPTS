from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentKind
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
    assert result.data.chassis is not None
    assert result.data.chassis.pid == "C9300-48P"
    assert result.data.chassis.serial_number == "FOC0000AAAA"
    assert result.data.chassis.kind is HardwareComponentKind.CHASSIS
    assert len(result.data.modules) == 1
    assert result.data.modules[0].pid == "PWR-C1-715WAC"
    assert len(result.data.components) == 1
    assert result.data.components[0].pid == "SFP-10G-SR"
    assert result.trace.parser_id is ParserId.IOS_SHOW_INVENTORY_V1
    assert result.trace.normalized_model is NormalizedModelId.HARDWARE_INVENTORY
    assert result.trace.command_execution_id == execution.id
    assert result.trace.raw_output_id == raw.id
    assert result.trace.raw_sha256 == raw.sha256
    assert any(item.field == "chassis.serial_number" for item in result.evidence)
    assert raw.content == content


def test_registry_resolves_productive_show_inventory_parser() -> None:
    parser = build_parser_registry().resolve(
        ParserId.IOS_SHOW_INVENTORY_V1,
        PlatformFamily.IOS_XE,
    )
    assert isinstance(parser, IOSShowInventoryParser)
