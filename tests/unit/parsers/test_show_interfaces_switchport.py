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

FIXTURE_SHA256 = "901b9a1a3aed745e4f228c0c5332bf956293078654d4f15c5f086cc051cce422"
FIXTURE_SIZE = 183529
FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "ios" / "show_interfaces_switchport"


def _fixture() -> Path:
    matches = [
        path
        for path in FIXTURE_DIR.glob("*.raw")
        if hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256
    ]
    assert len(matches) == 1
    return matches[0]


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


def _block(
    name: str = "GigabitEthernet1/0/1",
    switchport: str = "Enabled",
    negotiation: str | None = "On",
) -> str:
    lines = [
        f"Name: {name}",
        f"Switchport: {switchport}",
        "Administrative Mode: static access",
        "Operational Mode: static access (member of bundle Po10)",
        "Access Mode VLAN: 10 (USERS)",
        "Trunking Native Mode VLAN: 99 (NATIVE)",
        "Trunking VLANs Enabled: ALL",
        "Voice VLAN: none",
    ]
    if negotiation is not None:
        lines.append(f"Negotiation of Trunking: {negotiation}")
    return "\r\n".join(lines)


def test_real_fixture_integrity_and_complete_contract() -> None:
    payload = _fixture().read_bytes()
    assert len(payload) == FIXTURE_SIZE
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
    assert Counter(record.switchport_enabled for record in records) == Counter({True: 310})
    assert Counter(record.administrative_mode for record in records) == Counter(
        {"dynamic auto": 281, "trunk": 24, "static access": 5}
    )

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

    assert Counter(record.allowed_vlans for record in records) == Counter({"ALL": 156, None: 154})
    assert Counter(record.voice_vlan for record in records) == Counter({"none": 156, None: 154})
    assert Counter(record.negotiation_of_trunking for record in records) == Counter(
        {True: 151, False: 5, None: 154}
    )
    bundled = [
        record.operational_mode
        for record in records
        if record.operational_mode is not None and "(" in record.operational_mode
    ]
    assert len(bundled) == 12
    assert all(value.endswith(")") for value in bundled)
    assert all("(" in value and ")" in value for value in bundled)
    assert all(
        value is None or "(" not in value or value.endswith(")")
        for value in (record.access_vlan for record in records)
    )
    assert all(
        value is None or "(" not in value or value.endswith(")")
        for value in (record.native_vlan for record in records)
    )

    assert result.trace.parser_id is ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1
    assert result.trace.parser_version == "0.1.0"
    assert result.trace.command_id is CommandId.INTERFACES_SWITCHPORT
    assert result.trace.normalized_model is NormalizedModelId.SWITCHPORT_OBSERVATION
    assert result.trace.raw_sha256 == raw.sha256 == FIXTURE_SHA256
    assert raw.content.encode(raw.encoding) == payload

    raw_lines = content.replace("\r\n", "\n").split("\n")
    evidence = {item.field: item for item in result.evidence}
    for index, record in enumerate(records):
        prefix = f"interfaces[{index}]"
        assert raw_lines[evidence[f"{prefix}.interface"].line_start - 1].lstrip().startswith("Name:")
        fields = {
            "switchport_enabled": "Switchport:",
            "administrative_mode": "Administrative Mode:",
            "operational_mode": "Operational Mode:",
            "access_vlan": "Access Mode VLAN:",
            "native_vlan": "Trunking Native Mode VLAN:",
            "allowed_vlans": "Trunking VLANs Enabled:",
            "voice_vlan": "Voice VLAN:",
            "negotiation_of_trunking": "Negotiation of Trunking:",
        }
        for field_name, label in fields.items():
            key = f"{prefix}.{field_name}"
            value = getattr(record, field_name)
            if value is None:
                assert key not in evidence
            else:
                assert key in evidence
                source = evidence[key]
                assert label in raw_lines[source.line_start - 1]
                assert source.line_end >= source.line_start


@pytest.mark.parametrize("platform", [PlatformFamily.IOS, PlatformFamily.IOS_XE])
def test_descriptor_and_supported_platforms(platform: PlatformFamily) -> None:
    parser = IOSShowInterfacesSwitchportParser()
    assert parser.descriptor.parser_id is ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1
    assert parser.descriptor.parser_version == "0.1.0"
    assert parser.descriptor.command_id is CommandId.INTERFACES_SWITCHPORT
    assert parser.descriptor.normalized_model is NormalizedModelId.SWITCHPORT_OBSERVATION
    assert parser.descriptor.supported_platforms == frozenset(
        {PlatformFamily.IOS, PlatformFamily.IOS_XE}
    )
    _, result = _parse(_block(), platform)
    assert result.data.platform is platform


def test_productive_registry_resolves_ios_and_iosxe_and_rejects_nxos() -> None:
    registry = build_parser_registry()
    for platform in (PlatformFamily.IOS, PlatformFamily.IOS_XE):
        assert isinstance(
            registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, platform),
            IOSShowInterfacesSwitchportParser,
        )
    with pytest.raises(UnsupportedPlatformError):
        registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.NX_OS)


def test_exact_boolean_tokens_and_unknown_warnings() -> None:
    _, disabled = _parse(_block(switchport="Disabled", negotiation="Off"))
    assert disabled.status is ParseStatus.SUCCESS
    assert disabled.data.interfaces[0].switchport_enabled is False
    assert disabled.data.interfaces[0].negotiation_of_trunking is False

    _, on = _parse(_block(negotiation="On"))
    assert on.data.interfaces[0].negotiation_of_trunking is True

    _, unknown_switchport = _parse(_block(switchport="Maybe"))
    assert unknown_switchport.status is ParseStatus.PARTIAL
    assert unknown_switchport.data.interfaces[0].switchport_enabled is None
    assert [warning.code for warning in unknown_switchport.warnings] == [
        "switchport_state_unrecognized"
    ]

    _, unknown_negotiation = _parse(_block(negotiation="Auto"))
    assert unknown_negotiation.status is ParseStatus.PARTIAL
    assert unknown_negotiation.data.interfaces[0].negotiation_of_trunking is None
    assert [warning.code for warning in unknown_negotiation.warnings] == [
        "trunk_negotiation_unrecognized"
    ]


def test_structurally_valid_missing_fields_are_none_without_warning_or_evidence() -> None:
    _, result = _parse("Name: GigabitEthernet1/0/1\nSwitchport: Enabled\n")
    record = result.data.interfaces[0]
    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert record.administrative_mode is None
    assert record.operational_mode is None
    assert record.access_vlan is None
    assert record.native_vlan is None
    assert record.allowed_vlans is None
    assert record.voice_vlan is None
    assert record.negotiation_of_trunking is None
    fields = {item.field for item in result.evidence}
    assert "interfaces[0].switchport_enabled" in fields
    assert "interfaces[0].administrative_mode" not in fields
    assert "interfaces[0].negotiation_of_trunking" not in fields


def test_duplicate_and_missing_name_blocks_are_typed_failures() -> None:
    with pytest.raises(UnrecognizedFormatError, match="Duplicate interface Name block"):
        _parse(_block() + "\n" + _block())
    with pytest.raises(UnrecognizedFormatError, match="Name blocks"):
        _parse("Switchport: Enabled\nAdministrative Mode: trunk\n")


def test_allowed_vlan_numeric_continuation_is_conservative_and_spans_raw_lines() -> None:
    content = (
        "Name: GigabitEthernet1/0/1\n"
        "Switchport: Enabled\n"
        "Trunking VLANs Enabled: 1-10,\n"
        "  20,30-40\n"
        "Voice VLAN: none\n"
    )
    _, result = _parse(content)
    assert result.data.interfaces[0].allowed_vlans == "1-10,20,30-40"
    evidence = {item.field: item for item in result.evidence}
    allowed = evidence["interfaces[0].allowed_vlans"]
    assert (allowed.line_start, allowed.line_end) == (3, 4)

    _, ambiguous = _parse(
        "Name: GigabitEthernet1/0/1\n"
        "Switchport: Enabled\n"
        "Trunking VLANs Enabled: 1-10,\n"
        "not a vlan continuation\n"
    )
    assert ambiguous.data.interfaces[0].allowed_vlans == "1-10,"
    ambiguous_evidence = {item.field: item for item in ambiguous.evidence}
    assert ambiguous_evidence["interfaces[0].allowed_vlans"].line_end == 3


def test_genie_26_6_offline_characterization_is_not_productive_contract() -> None:
    from genie.libs.parser.iosxe.show_interface import ShowInterfacesSwitchport

    payload = _fixture().read_bytes()
    content = payload.decode("utf-8")
    _, framework = _parse(content)
    clean_view = "\n".join(
        line.text for line in IOSShowInterfacesSwitchportParser._build_parsing_lines(content)
    )
    genie = ShowInterfacesSwitchport(device=None).cli(output=clean_view)

    def leaves(value: object):
        if isinstance(value, dict):
            for child in value.values():
                yield from leaves(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from leaves(child)
        else:
            yield value

    genie_strings = [value for value in leaves(genie) if isinstance(value, str)]
    framework_records = framework.data.interfaces
    assert any(record.voice_vlan == "none" for record in framework_records)
    assert any(record.allowed_vlans == "ALL" for record in framework_records)
    assert any(
        record.operational_mode is not None and "(" in record.operational_mode
        for record in framework_records
    )
    assert "none" not in genie_strings
    assert "ALL" not in genie_strings
    assert not any("(" in value and ")" in value for value in genie_strings)
