from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pytest

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput, SwitchportObservation
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import (
    IOSShowInterfacesSwitchportParser,
    ParseStatus,
    UnsupportedPlatformError,
    build_parser_registry,
)
from cisco_assessment.parsers.errors import UnrecognizedFormatError

FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "ios"
    / "show_interfaces_switchport"
    / "c9300_iosxe_real_sanitized.raw"
)
FIXTURE_SHA256 = "901b9a1a3aed745e4f228c0c5332bf956293078654d4f15c5f086cc051cce422"


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.INTERFACES_SWITCHPORT.value,
        command="show interfaces switchport",
        sequence=1,
    )


def _parse(content: str, platform: PlatformFamily = PlatformFamily.IOS_XE):
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    result = IOSShowInterfacesSwitchportParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=platform,
    )
    return raw, result


def test_descriptor_and_productive_registry_scope() -> None:
    parser = IOSShowInterfacesSwitchportParser()
    assert parser.descriptor.parser_id is ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1
    assert parser.descriptor.parser_version == "0.1.0"
    assert parser.descriptor.command_id is CommandId.INTERFACES_SWITCHPORT
    assert parser.descriptor.normalized_model is NormalizedModelId.SWITCHPORT_OBSERVATION
    assert parser.descriptor.supported_platforms == frozenset(
        {PlatformFamily.IOS, PlatformFamily.IOS_XE}
    )

    registry = build_parser_registry()
    assert isinstance(
        registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.IOS),
        IOSShowInterfacesSwitchportParser,
    )
    assert isinstance(
        registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.IOS_XE),
        IOSShowInterfacesSwitchportParser,
    )
    with pytest.raises(UnsupportedPlatformError):
        registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.NX_OS)


def test_real_fixture_contract_and_raw_integrity() -> None:
    payload = FIXTURE.read_bytes()
    assert len(payload) == 183529
    assert hashlib.sha256(payload).hexdigest() == FIXTURE_SHA256

    content = payload.decode("utf-8")
    raw, result = _parse(content)
    records = result.data.interfaces

    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert isinstance(result.data, SwitchportObservation)
    assert len(records) == 310
    assert [record.ordinal for record in records] == list(range(1, 311))
    assert len({record.interface for record in records}) == 310
    assert Counter(record.switchport_enabled for record in records) == {True: 310}
    assert Counter(record.administrative_mode for record in records) == {
        "dynamic auto": 281,
        "trunk": 24,
        "static access": 5,
    }

    optional_fields = (
        "operational_mode",
        "access_vlan",
        "native_vlan",
        "allowed_vlans",
        "voice_vlan",
        "negotiation_of_trunking",
    )
    for field_name in optional_fields:
        values = [getattr(record, field_name) for record in records]
        assert sum(value is not None for value in values) == 156
        assert sum(value is None for value in values) == 154

    assert {record.allowed_vlans for record in records if record.allowed_vlans is not None} == {
        "ALL"
    }
    assert {record.voice_vlan for record in records if record.voice_vlan is not None} == {"none"}
    assert Counter(record.negotiation_of_trunking for record in records) == {
        True: 151,
        False: 5,
        None: 154,
    }
    annotated = [
        record.operational_mode
        for record in records
        if record.operational_mode is not None and "(" in record.operational_mode
    ]
    assert len(annotated) == 12
    assert all(value.endswith(")") for value in annotated)
    assert all("(" in value for value in annotated)
    assert all(
        value is None or ("(" not in value or value.endswith(")"))
        for record in records
        for value in (record.access_vlan, record.native_vlan)
    )

    assert raw.content == content
    assert raw.content.encode(raw.encoding) == payload
    assert raw.sha256 == result.trace.raw_sha256 == FIXTURE_SHA256


def test_every_demonstrated_real_field_maps_to_original_raw_logical_lines() -> None:
    payload = FIXTURE.read_bytes()
    content = payload.decode("utf-8")
    _, result = _parse(content)
    raw_lines = content.replace("\r\n", "\n").split("\n")
    evidence = {item.field: item for item in result.evidence}
    labels = {
        "interface": "Name:",
        "switchport_enabled": "Switchport:",
        "administrative_mode": "Administrative Mode:",
        "operational_mode": "Operational Mode:",
        "access_vlan": "Access Mode VLAN:",
        "native_vlan": "Trunking Native Mode VLAN:",
        "allowed_vlans": "Trunking VLANs Enabled:",
        "voice_vlan": "Voice VLAN:",
        "negotiation_of_trunking": "Negotiation of Trunking:",
    }

    for index, record in enumerate(result.data.interfaces):
        prefix = f"interfaces[{index}]"
        assert f"{prefix}.ordinal" in evidence
        for field_name, label in labels.items():
            field_path = f"{prefix}.{field_name}"
            value = getattr(record, field_name)
            if value is None:
                assert field_path not in evidence
                continue
            source = evidence[field_path]
            assert 1 <= source.line_start <= source.line_end <= len(raw_lines)
            contributing = raw_lines[source.line_start - 1 : source.line_end]
            assert label in contributing[0]

    pager_record = next(
        (index, record)
        for index, record in enumerate(result.data.interfaces)
        if record.interface == "Gi1/1/0/18"
    )
    index, _ = pager_record
    source = evidence[f"interfaces[{index}].interface"]
    original_line = raw_lines[source.line_start - 1]
    assert "--More--" in original_line
    assert "\x08" in original_line
    assert "Name: Gi1/1/0/18" in original_line
    assert not original_line.startswith("Name:")


def test_boolean_tokens_missing_fields_and_complete_text() -> None:
    content = (
        "Name: Gi1/0/1\n"
        "Switchport: Disabled\n"
        "Administrative Mode: trunk\n"
        "Operational Mode: trunk (members Gi1/0/1, Gi1/0/2)\n"
        "Access Mode VLAN: 10 (USERS WEST)\n"
        "Trunking Native Mode VLAN: 99 (NATIVE CORE)\n"
        "Negotiation of Trunking: On\n"
        "Name: Gi1/0/2\n"
        "Switchport: Enabled\n"
        "Negotiation of Trunking: Off\n"
        "Name: Gi1/0/3\n"
    )
    _, result = _parse(content)
    first, second, third = result.data.interfaces

    assert result.status is ParseStatus.SUCCESS
    assert first.switchport_enabled is False
    assert first.negotiation_of_trunking is True
    assert first.operational_mode == "trunk (members Gi1/0/1, Gi1/0/2)"
    assert first.access_vlan == "10 (USERS WEST)"
    assert first.native_vlan == "99 (NATIVE CORE)"
    assert second.switchport_enabled is True
    assert second.negotiation_of_trunking is False
    assert third.switchport_enabled is None
    assert third.administrative_mode is None
    assert third.operational_mode is None
    assert third.access_vlan is None
    assert third.native_vlan is None
    assert third.allowed_vlans is None
    assert third.voice_vlan is None
    assert third.negotiation_of_trunking is None
    assert result.warnings == ()

    fields = {item.field for item in result.evidence}
    assert "interfaces[2].interface" in fields
    assert "interfaces[2].switchport_enabled" not in fields
    assert "interfaces[2].administrative_mode" not in fields


@pytest.mark.parametrize(
    ("line", "field_name", "warning_code"),
    (
        ("Switchport: Maybe", "switchport_enabled", "switchport_state_unrecognized"),
        (
            "Negotiation of Trunking: Automatic",
            "negotiation_of_trunking",
            "trunk_negotiation_unrecognized",
        ),
    ),
)
def test_unknown_boolean_token_is_partial(
    line: str,
    field_name: str,
    warning_code: str,
) -> None:
    _, result = _parse(f"Name: Gi1/0/1\n{line}\n")
    assert result.status is ParseStatus.PARTIAL
    assert getattr(result.data.interfaces[0], field_name) is None
    assert [warning.code for warning in result.warnings] == [warning_code]


def test_numeric_vlan_continuation_is_conservative_and_traceable() -> None:
    content = (
        "Name: Gi1/0/1\n"
        "Trunking VLANs Enabled: 1-10,\n"
        "  20,30-40\n"
        "Name: Gi1/0/2\n"
        "Trunking VLANs Enabled: ALL\n"
        "ambiguous prose must not be joined\n"
    )
    _, result = _parse(content)
    assert result.data.interfaces[0].allowed_vlans == "1-10,20,30-40"
    assert result.data.interfaces[1].allowed_vlans == "ALL"
    evidence = {item.field: item for item in result.evidence}
    assert evidence["interfaces[0].allowed_vlans"].line_start == 2
    assert evidence["interfaces[0].allowed_vlans"].line_end == 3
    assert evidence["interfaces[1].allowed_vlans"].line_start == 5
    assert evidence["interfaces[1].allowed_vlans"].line_end == 5


def test_duplicate_and_missing_name_blocks_are_typed_failures() -> None:
    with pytest.raises(UnrecognizedFormatError, match="Duplicate interface"):
        _parse("Name: Gi1/0/1\nSwitchport: Enabled\nName: Gi1/0/1\n")
    with pytest.raises(UnrecognizedFormatError, match="Name blocks"):
        _parse("show interfaces switchport\nSwitchport: Enabled\nSW1#\n")


def test_genie_26_6_offline_is_characterization_not_productive_contract() -> None:
    from genie.libs.parser.iosxe.show_interface import ShowInterfacesSwitchport

    content = FIXTURE.read_bytes().decode("utf-8")
    _, framework = _parse(content)
    rendered = "\n".join(
        line.text for line in IOSShowInterfacesSwitchportParser._build_parsing_lines(content)
    )
    parsed = ShowInterfacesSwitchport(device=None).cli(output=rendered)

    assert isinstance(parsed, dict)
    assert len(framework.data.interfaces) == 310
    framework_voice = [
        record.voice_vlan
        for record in framework.data.interfaces
        if record.voice_vlan is not None
    ]
    framework_allowed = [
        record.allowed_vlans
        for record in framework.data.interfaces
        if record.allowed_vlans is not None
    ]
    framework_annotated = [
        record.operational_mode
        for record in framework.data.interfaces
        if record.operational_mode is not None and "(" in record.operational_mode
    ]
    assert framework_voice == ["none"] * 156
    assert framework_allowed == ["ALL"] * 156
    assert len(framework_annotated) == 12

    genie_interfaces = parsed.get("interfaces", parsed)
    genie_values = list(genie_interfaces.values())
    assert not all(item.get("voice_vlan") == "none" for item in genie_values)
    assert not all(item.get("trunk_vlans") == "ALL" for item in genie_values)
    assert not all(
        any(
            isinstance(value, str) and value == expected
            for value in item.values()
        )
        for expected in framework_annotated
        for item in genie_values
    )
