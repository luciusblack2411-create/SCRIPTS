from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import IOSShowInterfacesStatusParser, ParseStatus

FIXTURES = Path(__file__).parents[2] / "fixtures" / "ios" / "show_interfaces_status"
BASELINE_FIXTURE = FIXTURES / "c9300_iosxe_genie_v0_1.txt"
STACK_MEMBER_FIXTURE = FIXTURES / "c9300_iosxe_stack_member_v0_1.txt"


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.INTERFACES_STATUS.value,
        command="show interfaces status",
        sequence=1,
    )


def _parse_fixture(path: Path):
    execution = _execution()
    content = path.read_text(encoding="utf-8")
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    result = IOSShowInterfacesStatusParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )
    return content, raw, result


def test_baseline_fixture_preserves_every_observed_token_and_complete_field_evidence() -> None:
    _, _, result = _parse_fixture(BASELINE_FIXTURE)

    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert [
        (
            record.interface,
            record.description,
            record.status,
            record.vlan,
            record.duplex,
            record.speed,
            record.media_type,
        )
        for record in result.data.interfaces
    ] == [
        (
            "GigabitEthernet1/0/1",
            "USER-ACCESS",
            "connected",
            "10",
            "a-full",
            "a-1000",
            "10/100/1000BaseTX",
        ),
        (
            "GigabitEthernet1/0/2",
            None,
            "notconnect",
            "20",
            "auto",
            "auto",
            "10/100/1000BaseTX",
        ),
        (
            "GigabitEthernet1/0/3",
            "ADMIN-DOWN",
            "disabled",
            "30",
            "auto",
            "auto",
            "10/100/1000BaseTX",
        ),
        (
            "GigabitEthernet1/0/4",
            "BPDU-GUARD",
            "err-disabled",
            "40",
            "auto",
            "auto",
            "10/100/1000BaseTX",
        ),
        (
            "GigabitEthernet1/0/47",
            "CORE-TRUNK",
            "connected",
            "trunk",
            "a-full",
            "a-1000",
            "1000BaseLX SFP",
        ),
        (
            "TenGigabitEthernet1/1/1",
            "DIST-UPLINK",
            "connected",
            "routed",
            "full",
            "a-10G",
            "10GBase-SR",
        ),
        (
            "Port-channel10",
            "SERVER-LAG",
            "connected",
            "trunk",
            "a-full",
            "a-10G",
            None,
        ),
    ]

    expected_fields = {"interfaces"}
    for index, record in enumerate(result.data.interfaces):
        prefix = f"interfaces[{index}]"
        expected_fields.update(
            {
                prefix,
                f"{prefix}.ordinal",
                f"{prefix}.interface",
                f"{prefix}.status",
                f"{prefix}.vlan",
                f"{prefix}.duplex",
                f"{prefix}.speed",
            }
        )
        if record.description is not None:
            expected_fields.add(f"{prefix}.description")
        if record.media_type is not None:
            expected_fields.add(f"{prefix}.media_type")

    evidence_by_field = {item.field: item for item in result.evidence}
    assert set(evidence_by_field) == expected_fields
    for index, expected_line in enumerate(range(2, 9)):
        prefix = f"interfaces[{index}]"
        for field in expected_fields:
            if field == prefix or field.startswith(f"{prefix}."):
                assert evidence_by_field[field].line_start == expected_line
                assert evidence_by_field[field].line_end == expected_line


def test_iosxe_stack_member_fixture_is_canonical_ordered_and_traceable() -> None:
    content, raw, result = _parse_fixture(STACK_MEMBER_FIXTURE)
    original_bytes = content.encode("utf-8")
    original_sha256 = hashlib.sha256(original_bytes).hexdigest()

    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert [record.ordinal for record in result.data.interfaces] == [1, 2]
    assert [record.interface for record in result.data.interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet2/0/3",
    ]

    evidence_by_field = {item.field: item for item in result.evidence}
    assert evidence_by_field["interfaces[0].interface"].line_start == 2
    assert evidence_by_field["interfaces[1].interface"].line_start == 3
    assert evidence_by_field["interfaces[0].interface"].line_end == 2
    assert evidence_by_field["interfaces[1].interface"].line_end == 3

    assert raw.content == content
    assert raw.content.encode(raw.encoding) == original_bytes
    assert raw.sha256 == original_sha256
    assert result.trace.raw_sha256 == original_sha256
