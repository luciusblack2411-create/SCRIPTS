from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import IOSShowVlanBriefParser, ParseStatus

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "ios"
    / "show_vlan_brief"
    / "c9300_iosxe_real_sanitized.raw"
)

_VLAN_ROW_LINES = [
    5,
    23,
    24,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
]


def _parse_fixture():
    payload = FIXTURE.read_bytes()
    execution = CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.VLANS_BRIEF.value,
        command="show vlan brief",
        sequence=1,
    )
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=payload.decode("utf-8"),
        encoding="utf-8",
    )
    result = IOSShowVlanBriefParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )
    return payload, result


def test_real_fixture_complete_field_evidence_uses_original_raw_lines() -> None:
    payload, result = _parse_fixture()

    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()

    raw_lines = payload.split(b"\r\n")
    assert b"--More--" in raw_lines[24]
    assert raw_lines[25] == b"VLAN Name                             Status    Ports"
    assert raw_lines[26] == b"---- -------------------------------- --------- -------------------------------"

    expected_fields = {"vlans"}
    for index in range(17):
        prefix = f"vlans[{index}]"
        expected_fields.update(
            {
                f"{prefix}.vlan_id",
                f"{prefix}.name",
                f"{prefix}.status",
                f"{prefix}.ports",
            }
        )

    evidence = {item.field: item for item in result.evidence}
    assert set(evidence) == expected_fields
    assert evidence["vlans"].line_start == 5
    assert evidence["vlans"].line_end == 41

    for index, row_line in enumerate(_VLAN_ROW_LINES):
        prefix = f"vlans[{index}]"
        for field_name in ("vlan_id", "name", "status"):
            field_evidence = evidence[f"{prefix}.{field_name}"]
            assert field_evidence.line_start == row_line
            assert field_evidence.line_end == row_line

        ports_evidence = evidence[f"{prefix}.ports"]
        if index == 0:
            assert ports_evidence.line_start == 5
            assert ports_evidence.line_end == 22
        else:
            assert ports_evidence.line_start == row_line
            assert ports_evidence.line_end == row_line

    pager_and_repeated_header_lines = {25, 26, 27}
    field_level_evidence = [item for item in result.evidence if item.field != "vlans"]
    assert all(
        item.line_start not in pager_and_repeated_header_lines
        and item.line_end not in pager_and_repeated_header_lines
        for item in field_level_evidence
    )
