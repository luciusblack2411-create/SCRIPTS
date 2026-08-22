from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentType
from cisco_assessment.parsers import IOSShowInventoryParser, ParseStatus


def test_duplicate_member_number_keeps_explicit_child_parent_unknown() -> None:
    execution = CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.SYSTEM_INVENTORY.value,
        command="show inventory",
        sequence=2,
    )
    content = "\n".join(
        (
            'NAME: "Switch 1", DESCR: "Cisco Catalyst Switch"',
            "PID: C9300-48P, VID: V01, SN: MEMBER1A",
            'NAME: "Switch 1", DESCR: "Duplicate member identity"',
            "PID: C9300-48P, VID: V01, SN: MEMBER1B",
            'NAME: "Gi1/1/1", DESCR: "1000BaseSX SFP"',
            "PID: GLC-SX-MMD, VID: V03, SN: OPTIC1",
        )
    )
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)

    result = IOSShowInventoryParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.SUCCESS
    assert [record.component_type for record in result.data.records] == [
        HardwareComponentType.CHASSIS_MEMBER,
        HardwareComponentType.CHASSIS_MEMBER,
        HardwareComponentType.TRANSCEIVER,
    ]
    assert result.data.records[2].name == "Gi1/1/1"
    assert result.data.records[2].parent_id is None
    assert raw.content == content
