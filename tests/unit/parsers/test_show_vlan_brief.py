from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput, VlanObservation, VlanStatus
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import (
    IOSShowVlanBriefParser,
    ParseStatus,
    UnsupportedPlatformError,
    build_parser_registry,
)
from cisco_assessment.parsers.errors import UnrecognizedFormatError

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "ios" / "show_vlan_brief"
FIXTURE = FIXTURE_DIR / "c9300_iosxe_real_sanitized.raw"
FIXTURE_METADATA = FIXTURE_DIR / "c9300_iosxe_real_sanitized.json"

ORIGINAL_SHA256 = "16bb1794ce7faa112f65ea20b01a8410fce789c0e7b12090eca7836d929f2bd7"
FIXTURE_SHA256 = "2e6d3d49fe2618a0b72a4d69c05704422cde736bf29d5a9cfe6982617905efd1"

_EXPECTED_VLAN_IDS = [
    1,
    2,
    20,
    23,
    24,
    27,
    28,
    29,
    30,
    34,
    36,
    41,
    301,
    1002,
    1003,
    1004,
    1005,
]

_EXPECTED_NAMES = [
    "default",
    "LAB_Users",
    "VoIP",
    "WIFI_LABclients",
    "WIFI_LAB-any",
    "WIFI_LAB-zone1",
    "Mgmt",
    "LAB1_Servers",
    "LAB",
    "CAM_LAB",
    "TEST_Server",
    "MGMT_Tool1",
    "Native_VLAN",
    "fddi-default",
    "trcrf-default",
    "fddinet-default",
    "trbrf-default",
]


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.VLANS_BRIEF.value,
        command="show vlan brief",
        sequence=1,
    )


def _parse_bytes(
    payload: bytes,
    *,
    platform: PlatformFamily = PlatformFamily.IOS_XE,
):
    execution = _execution()
    content = payload.decode("utf-8")
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=content,
        encoding="utf-8",
    )
    result = IOSShowVlanBriefParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=platform,
    )
    return execution, raw, result


def _row(vlan_id: int, name: str, status: str, ports: str = "") -> str:
    return f"{vlan_id:<5}{name:<33}{status:<10}{ports}"


def _table(*rows: str) -> bytes:
    return (
        "show vlan brief\r\n"
        "\r\n"
        "VLAN Name                             Status    Ports\r\n"
        "---- -------------------------------- --------- -------------------------------\r\n"
        + "\r\n".join(rows)
        + "\r\nLAB_SWITCH01#"
    ).encode("utf-8")


def test_real_fixture_integrity_metadata_and_terminal_artifacts() -> None:
    payload = FIXTURE.read_bytes()
    metadata = json.loads(FIXTURE_METADATA.read_text(encoding="utf-8"))

    assert len(payload) == 2522
    assert hashlib.sha256(payload).hexdigest() == FIXTURE_SHA256
    assert payload.count(b"--More--") == 1
    assert payload.count(b"\x08") == 18
    assert payload.count(b"\r") == 41
    assert payload.count(b"\n") == 41

    assert metadata["command_id"] == CommandId.VLANS_BRIEF.value
    assert metadata["cli"] == "show vlan brief"
    assert metadata["platform"] == PlatformFamily.IOS_XE.value
    assert metadata["original"]["byte_length"] == 2522
    assert metadata["original"]["sha256"] == ORIGINAL_SHA256
    assert metadata["sanitized_fixture"]["byte_length"] == 2522
    assert metadata["sanitized_fixture"]["sha256"] == FIXTURE_SHA256
    assert metadata["sanitized_fixture"]["terminal_artifacts"] == {
        "--More--": 1,
        "backspace": 18,
        "cr": 41,
        "lf": 41,
    }


@pytest.mark.parametrize("platform", [PlatformFamily.IOS, PlatformFamily.IOS_XE])
def test_parser_normalizes_real_paginated_fixture_without_mutating_raw(
    platform: PlatformFamily,
) -> None:
    payload = FIXTURE.read_bytes()
    independent_sha = hashlib.sha256(payload).hexdigest()
    execution, raw, result = _parse_bytes(payload, platform=platform)

    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert isinstance(result.data, VlanObservation)
    assert result.data.platform is platform
    assert [record.ordinal for record in result.data.vlans] == list(range(1, 18))
    assert [record.vlan_id for record in result.data.vlans] == _EXPECTED_VLAN_IDS
    assert [record.name for record in result.data.vlans] == _EXPECTED_NAMES

    assert [record.status for record in result.data.vlans[:13]] == [
        VlanStatus.ACTIVE
    ] * 13
    assert [record.status for record in result.data.vlans[13:]] == [
        VlanStatus.ACTIVE_UNSUPPORTED
    ] * 4

    vlan1 = result.data.vlans[0]
    assert vlan1.vlan_id == 1
    assert vlan1.ports is not None
    assert len(vlan1.ports) == 54
    assert vlan1.ports[:3] == ("Gi1/0/2", "Gi1/0/3", "Gi1/0/4")
    assert vlan1.ports[-3:] == ("Gi2/1/2", "Gi2/1/3", "Gi2/1/4")
    assert all(record.ports == () for record in result.data.vlans[1:])

    evidence = {item.field: item for item in result.evidence}
    assert evidence["vlans"].line_start == 5
    assert evidence["vlans"].line_end == 41
    assert evidence["vlans[0].vlan_id"].line_start == 5
    assert evidence["vlans[0].name"].line_start == 5
    assert evidence["vlans[0].status"].line_start == 5
    assert evidence["vlans[0].ports"].line_start == 5
    assert evidence["vlans[0].ports"].line_end == 22
    assert evidence["vlans[1].ports"].line_start == 23
    assert evidence["vlans[1].ports"].line_end == 23
    assert evidence["vlans[13].status"].line_start == 38
    assert evidence["vlans[16].status"].line_start == 41

    assert result.trace.parser_id is ParserId.IOS_SHOW_VLAN_BRIEF_V1
    assert result.trace.parser_version == "0.1.0"
    assert result.trace.command_id is CommandId.VLANS_BRIEF
    assert result.trace.normalized_model is NormalizedModelId.VLAN_OBSERVATION
    assert result.trace.raw_sha256 == independent_sha == FIXTURE_SHA256
    assert raw.sha256 == FIXTURE_SHA256
    assert raw.byte_length == 2522
    assert raw.content.encode(raw.encoding) == payload
    assert raw.command_execution_id == execution.id


def test_genie_26_6_offline_characterization_loses_real_port_continuations() -> None:
    from genie.libs.parser.iosxe.show_vlan import ShowVlanBrief

    payload = FIXTURE.read_bytes()
    _, _, framework_result = _parse_bytes(payload)

    content = payload.decode("utf-8")
    clean_view = "\n".join(
        item.text for item in IOSShowVlanBriefParser._build_parsing_lines(content)
    )
    genie = ShowVlanBrief(device=None)
    parsed = genie.cli(output=clean_view)

    assert isinstance(parsed, dict)
    assert list(parsed["vlan"]) == [f"vlan{vlan_id}" for vlan_id in _EXPECTED_VLAN_IDS]
    assert parsed["vlan"]["vlan1"]["vlan_name"] == "default"
    assert parsed["vlan"]["vlan1002"]["vlan_status"] == "act/unsup"

    genie_ports = parsed["vlan"]["vlan1"]["vlan_port"]
    framework_ports = framework_result.data.vlans[0].ports
    assert genie_ports == ["Gi1/0/2", "Gi1/0/3", "Gi1/0/4"]
    assert framework_ports is not None
    assert len(genie_ports) == 3
    assert len(framework_ports) == 54
    assert genie_ports == list(framework_ports[:3])


def test_unrecognized_status_is_unknown_with_partial_warning_and_evidence() -> None:
    payload = _table(
        _row(10, "USERS", "active"),
        _row(20, "OTHER", "newstate"),
    )

    _, _, result = _parse_bytes(payload)

    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == ["vlan_status_unrecognized"]
    assert result.data.vlans[0].status is VlanStatus.ACTIVE
    assert result.data.vlans[1].status is VlanStatus.UNKNOWN

    evidence = {item.field: item for item in result.evidence}
    assert evidence["vlans[1].status"].line_start == 6
    assert evidence["vlans[1].status"].line_end == 6


def test_missing_status_is_unknown_without_fabricated_status_evidence() -> None:
    payload = _table(
        _row(10, "USERS", ""),
        _row(20, "OTHER", "active"),
    )

    _, _, result = _parse_bytes(payload)

    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == ["vlan_status_missing"]
    assert result.data.vlans[0].status is VlanStatus.UNKNOWN
    evidence_fields = {item.field for item in result.evidence}
    assert "vlans[0].status" not in evidence_fields
    assert "vlans[0].vlan_id" in evidence_fields
    assert "vlans[0].ports" in evidence_fields


def test_orphan_ports_continuation_is_partial_and_not_attached_to_later_vlan() -> None:
    payload = _table(
        " " * 48 + "Gi1/0/1, Gi1/0/2",
        _row(10, "USERS", "active"),
    )

    _, _, result = _parse_bytes(payload)

    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == [
        "orphan_vlan_ports_continuation"
    ]
    assert result.data.vlans[0].ports == ()


def test_duplicate_vlan_row_is_partial_and_first_observation_is_retained() -> None:
    payload = _table(
        _row(10, "FIRST", "active", "Gi1/0/1"),
        _row(10, "SECOND", "active", "Gi1/0/2"),
        _row(20, "THIRD", "active"),
    )

    _, _, result = _parse_bytes(payload)

    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == ["duplicate_vlan_row"]
    assert [record.vlan_id for record in result.data.vlans] == [10, 20]
    assert result.data.vlans[0].name == "FIRST"
    assert result.data.vlans[0].ports == ("Gi1/0/1",)


def test_missing_vlan_table_is_typed_unrecognized_format() -> None:
    execution = _execution()
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content="show vlan brief\r\nunexpected output\r\nLAB_SWITCH01#",
    )

    with pytest.raises(UnrecognizedFormatError):
        IOSShowVlanBriefParser().parse(
            raw_output=raw,
            command_execution=execution,
            platform=PlatformFamily.IOS_XE,
        )


def test_productive_registry_resolves_ios_and_iosxe_and_rejects_nxos() -> None:
    registry = build_parser_registry()

    ios = registry.resolve(ParserId.IOS_SHOW_VLAN_BRIEF_V1, PlatformFamily.IOS)
    iosxe = registry.resolve(ParserId.IOS_SHOW_VLAN_BRIEF_V1, PlatformFamily.IOS_XE)
    assert isinstance(ios, IOSShowVlanBriefParser)
    assert isinstance(iosxe, IOSShowVlanBriefParser)

    with pytest.raises(UnsupportedPlatformError):
        registry.resolve(ParserId.IOS_SHOW_VLAN_BRIEF_V1, PlatformFamily.NX_OS)
