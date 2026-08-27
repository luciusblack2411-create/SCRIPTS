from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pytest

from cisco_assessment.catalog.enums import CommandId, NormalizedModelId, ParserId
from cisco_assessment.models import CommandExecution, RawCommandOutput, SwitchportObservation
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.parsers import IOSShowInterfacesSwitchportParser, ParseStatus, UnsupportedPlatformError, build_parser_registry
from cisco_assessment.parsers.errors import UnrecognizedFormatError

FIXTURE = Path(__file__).parents[2] / "fixtures" / "ios" / "show_interfaces_switchport" / "c9300_iosxe_real_sanitized.raw"
FIXTURE_SHA256 = "901b9a1a3aed745e4f228c0c5332bf956293078654d4f15c5f086cc051cce422"


def _execution() -> CommandExecution:
    return CommandExecution(assessment_run_id=uuid4(), command_key=CommandId.INTERFACES_SWITCHPORT.value, command="show interfaces switchport", sequence=1)


def _parse(payload: bytes, platform: PlatformFamily = PlatformFamily.IOS_XE):
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=payload.decode("utf-8"), encoding="utf-8")
    result = IOSShowInterfacesSwitchportParser().parse(raw_output=raw, command_execution=execution, platform=platform)
    return raw, result


def _blocks(*blocks: str) -> bytes:
    return ("show interfaces switchport\r\n" + "\r\n".join(blocks) + "\r\nSW#").encode()


def test_real_fixture_contract_and_evidence() -> None:
    payload = FIXTURE.read_bytes()
    assert len(payload) == 183529
    assert hashlib.sha256(payload).hexdigest() == FIXTURE_SHA256
    raw, result = _parse(payload)
    assert result.status is ParseStatus.SUCCESS
    assert result.warnings == ()
    assert isinstance(result.data, SwitchportObservation)
    records = result.data.interfaces
    assert len(records) == 310
    assert len({record.interface for record in records}) == 310
    assert [record.ordinal for record in records] == list(range(1, 311))
    assert all(record.switchport_enabled is True for record in records)
    assert Counter(record.administrative_mode for record in records) == {"dynamic auto": 281, "trunk": 24, "static access": 5}
    optional = ("operational_mode", "access_vlan", "native_vlan", "allowed_vlans", "voice_vlan", "negotiation_of_trunking")
    for name in optional:
        assert sum(getattr(record, name) is not None for record in records) == 156
    assert {r.allowed_vlans for r in records if r.allowed_vlans is not None} == {"ALL"}
    assert {r.voice_vlan for r in records if r.voice_vlan is not None} == {"none"}
    assert Counter(r.negotiation_of_trunking for r in records) == {True: 151, False: 5, None: 154}
    assert len([r for r in records if r.operational_mode and "(" in r.operational_mode]) == 12
    evidence = {item.field: item for item in result.evidence}
    raw_lines = raw.content.replace("\r\n", "\n").split("\n")
    labels = {"interface": "Name:", "switchport_enabled": "Switchport:", "administrative_mode": "Administrative Mode:", "operational_mode": "Operational Mode:", "access_vlan": "Access Mode VLAN:", "native_vlan": "Trunking Native Mode VLAN:", "allowed_vlans": "Trunking VLANs Enabled:", "voice_vlan": "Voice VLAN:", "negotiation_of_trunking": "Negotiation of Trunking:"}
    for index, record in enumerate(records):
        for name, label in labels.items():
            value = getattr(record, name)
            key = f"interfaces[{index}].{name}"
            if value is None:
                assert key not in evidence
            else:
                item = evidence[key]
                assert label in raw_lines[item.line_start - 1]
                if name in {"operational_mode", "access_vlan", "native_vlan"}:
                    assert str(value) in raw_lines[item.line_start - 1]
    assert result.trace.parser_id is ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1
    assert result.trace.parser_version == "0.1.0"
    assert result.trace.command_id is CommandId.INTERFACES_SWITCHPORT
    assert result.trace.normalized_model is NormalizedModelId.SWITCHPORT_OBSERVATION
    assert result.trace.raw_sha256 == raw.sha256 == FIXTURE_SHA256


def test_boolean_mappings_missing_fields_and_continuation() -> None:
    payload = _blocks(
        "Name: Gi1/0/1\r\nSwitchport: Disabled\r\nNegotiation of Trunking: Off",
        "Name: Gi1/0/2\r\nSwitchport: Future\r\nNegotiation of Trunking: Maybe",
        "Name: Gi1/0/3\r\nSwitchport: Enabled\r\nNegotiation of Trunking: On\r\nTrunking VLANs Enabled: 1,2-4,\r\n  10-12",
        "Name: Gi1/0/4\r\nSwitchport: Enabled",
    )
    _, result = _parse(payload)
    assert result.status is ParseStatus.PARTIAL
    assert [warning.code for warning in result.warnings] == ["switchport_state_unrecognized", "trunk_negotiation_unrecognized"]
    first, second, third, fourth = result.data.interfaces
    assert (first.switchport_enabled, first.negotiation_of_trunking) == (False, False)
    assert (second.switchport_enabled, second.negotiation_of_trunking) == (None, None)
    assert (third.switchport_enabled, third.negotiation_of_trunking) == (True, True)
    assert third.allowed_vlans == "1,2-4,10-12"
    assert fourth.administrative_mode is None
    fields = {item.field: item for item in result.evidence}
    assert fields["interfaces[2].allowed_vlans"].line_end == fields["interfaces[2].allowed_vlans"].line_start + 1
    assert "interfaces[1].switchport_enabled" not in fields
    assert "interfaces[3].administrative_mode" not in fields


def test_ambiguous_continuation_is_not_joined() -> None:
    _, result = _parse(_blocks("Name: Gi1/0/1\r\nTrunking VLANs Enabled: 1-10\r\nambiguous text"))
    assert result.data.interfaces[0].allowed_vlans == "1-10"
    item = {e.field: e for e in result.evidence}["interfaces[0].allowed_vlans"]
    assert item.line_start == item.line_end


@pytest.mark.parametrize("payload", [_blocks("Name: Gi1/0/1", "Name: Gi1/0/1"), b"show interfaces switchport\r\nunexpected\r\nSW#"])
def test_invalid_structure_is_typed(payload: bytes) -> None:
    execution = _execution()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=payload.decode())
    with pytest.raises(UnrecognizedFormatError):
        IOSShowInterfacesSwitchportParser().parse(raw_output=raw, command_execution=execution, platform=PlatformFamily.IOS_XE)


def test_productive_registry_scope() -> None:
    registry = build_parser_registry()
    assert isinstance(registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.IOS), IOSShowInterfacesSwitchportParser)
    assert isinstance(registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.IOS_XE), IOSShowInterfacesSwitchportParser)
    with pytest.raises(UnsupportedPlatformError):
        registry.resolve(ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1, PlatformFamily.NX_OS)


def test_genie_26_6_offline_characterization_is_not_productive_contract() -> None:
    from genie.libs.parser.iosxe.show_interface import ShowInterfacesSwitchport

    content = FIXTURE.read_text(encoding="utf-8")
    clean = "\n".join(line.text for line in IOSShowInterfacesSwitchportParser._build_parsing_lines(content))
    framework = _parse(FIXTURE.read_bytes())[1]
    parsed = ShowInterfacesSwitchport(device=None).cli(output=clean)
    assert isinstance(parsed, dict)
    framework_records = {record.interface: record for record in framework.data.interfaces}
    assert any(framework_records[name].voice_vlan == "none" and values.get("voice_vlan") != "none" for name, values in parsed.items() if name in framework_records)
    assert any(framework_records[name].allowed_vlans == "ALL" and values.get("trunking_vlans") != "ALL" for name, values in parsed.items() if name in framework_records)
    assert any(record.operational_mode and "(" in record.operational_mode for record in framework.data.interfaces)
    assert all("(" not in str(values.get("operational_mode", "")) for values in parsed.values())
