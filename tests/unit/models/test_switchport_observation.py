from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    SWITCHPORT_OBSERVATION_SCHEMA_VERSION,
    PlatformFamily,
    SwitchportObservation,
    SwitchportRecord,
)


def _record(
    ordinal: int,
    *,
    interface: str = "GigabitEthernet1/0/1",
    switchport_enabled: bool | None = True,
    administrative_mode: str | None = "static access",
    operational_mode: str | None = "static access",
    access_vlan: str | None = "10 (USERS)",
    native_vlan: str | None = "1 (default)",
    allowed_vlans: str | None = "ALL",
    voice_vlan: str | None = "20 (VOICE)",
    negotiation_of_trunking: bool | None = True,
) -> SwitchportRecord:
    return SwitchportRecord(
        ordinal=ordinal,
        interface=interface,
        switchport_enabled=switchport_enabled,
        administrative_mode=administrative_mode,
        operational_mode=operational_mode,
        access_vlan=access_vlan,
        native_vlan=native_vlan,
        allowed_vlans=allowed_vlans,
        voice_vlan=voice_vlan,
        negotiation_of_trunking=negotiation_of_trunking,
    )


def test_observation_preserves_stack_member_and_port_channel_order() -> None:
    observation = SwitchportObservation(
        platform=PlatformFamily.IOS_XE,
        interfaces=(
            _record(1, interface="GigabitEthernet1/0/1"),
            _record(
                2,
                interface="GigabitEthernet2/0/48",
                administrative_mode="trunk",
                operational_mode="trunk",
                access_vlan="1 (default)",
                native_vlan="99 (NATIVE)",
                allowed_vlans="10,20,30-40",
                voice_vlan="none",
                negotiation_of_trunking=False,
            ),
            _record(
                3,
                interface="Port-channel10",
                administrative_mode="trunk",
                operational_mode="trunk",
                allowed_vlans="ALL",
                voice_vlan="none",
            ),
        ),
    )

    assert observation.schema_version == SWITCHPORT_OBSERVATION_SCHEMA_VERSION == "0.1"
    assert observation.vendor == "Cisco"
    assert [record.ordinal for record in observation.interfaces] == [1, 2, 3]
    assert [record.interface for record in observation.interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet2/0/48",
        "Port-channel10",
    ]
    assert observation.interfaces[1].allowed_vlans == "10,20,30-40"
    assert observation.interfaces[1].negotiation_of_trunking is False


def test_disabled_switchport_can_leave_other_facts_unknown() -> None:
    record = _record(
        1,
        switchport_enabled=False,
        administrative_mode=None,
        operational_mode=None,
        access_vlan=None,
        native_vlan=None,
        allowed_vlans=None,
        voice_vlan=None,
        negotiation_of_trunking=None,
    )

    assert record.switchport_enabled is False
    assert record.administrative_mode is None
    assert record.operational_mode is None
    assert record.access_vlan is None
    assert record.native_vlan is None
    assert record.allowed_vlans is None
    assert record.voice_vlan is None
    assert record.negotiation_of_trunking is None


def test_open_text_fields_preserve_unrecognized_valid_tokens() -> None:
    record = _record(
        1,
        administrative_mode="future-dynamic-mode",
        operational_mode="future-operational-mode",
        access_vlan="unassigned",
        native_vlan="future-native-value",
        allowed_vlans="future-vlan-expression",
        voice_vlan="dot1p",
    )

    assert record.administrative_mode == "future-dynamic-mode"
    assert record.operational_mode == "future-operational-mode"
    assert record.access_vlan == "unassigned"
    assert record.native_vlan == "future-native-value"
    assert record.allowed_vlans == "future-vlan-expression"
    assert record.voice_vlan == "dot1p"



def test_allowed_vlans_preserves_expression_longer_than_4096_characters() -> None:
    allowed_vlans = ",".join(str(vlan) for vlan in range(1, 1201))

    assert len(allowed_vlans) > 4096

    record = _record(1, allowed_vlans=allowed_vlans)

    assert record.allowed_vlans == allowed_vlans


def test_optional_text_normalizes_blank_to_none_but_preserves_explicit_none_token() -> None:
    record = _record(
        1,
        administrative_mode="  trunk  ",
        operational_mode="   ",
        access_vlan="  1 (default)  ",
        native_vlan="   ",
        allowed_vlans="  ALL  ",
        voice_vlan="  none  ",
    )

    assert record.administrative_mode == "trunk"
    assert record.operational_mode is None
    assert record.access_vlan == "1 (default)"
    assert record.native_vlan is None
    assert record.allowed_vlans == "ALL"
    assert record.voice_vlan == "none"


@pytest.mark.parametrize("field", ("switchport_enabled", "negotiation_of_trunking"))
def test_boolean_fields_are_strict(field: str) -> None:
    payload = _record(1).model_dump()
    payload[field] = "true"

    with pytest.raises(ValidationError):
        SwitchportRecord.model_validate(payload)


def test_unknown_boolean_facts_require_explicit_none() -> None:
    payload = _record(1).model_dump()
    del payload["switchport_enabled"]

    with pytest.raises(ValidationError):
        SwitchportRecord.model_validate(payload)


@pytest.mark.parametrize(
    "records",
    (
        (
            _record(1, interface="GigabitEthernet1/0/1"),
            _record(3, interface="GigabitEthernet1/0/2"),
        ),
        (
            _record(2, interface="GigabitEthernet1/0/1"),
            _record(1, interface="GigabitEthernet1/0/2"),
        ),
    ),
)
def test_observation_rejects_missing_or_reordered_ordinals(
    records: tuple[SwitchportRecord, ...],
) -> None:
    with pytest.raises(ValidationError, match="ordinals must be contiguous"):
        SwitchportObservation(platform=PlatformFamily.IOS_XE, interfaces=records)


def test_observation_rejects_duplicate_interface_names() -> None:
    with pytest.raises(ValidationError, match="interface names must be unique"):
        SwitchportObservation(
            platform=PlatformFamily.IOS_XE,
            interfaces=(
                _record(1, interface="GigabitEthernet1/0/1"),
                _record(2, interface="GigabitEthernet1/0/1"),
            ),
        )


def test_interface_must_not_be_blank() -> None:
    with pytest.raises(ValidationError, match="interface must not be blank"):
        _record(1, interface="   ")


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    record = _record(1)
    observation = SwitchportObservation(
        platform=PlatformFamily.IOS,
        interfaces=(record,),
    )

    with pytest.raises(ValidationError):
        record.interface = "GigabitEthernet1/0/2"

    with pytest.raises(ValidationError):
        observation.interfaces = ()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SwitchportRecord.model_validate(
            {
                **record.model_dump(),
                "raw_line": "Switchport: Enabled",
            }
        )


def test_switchport_observation_json_round_trip_is_canonical() -> None:
    observation = SwitchportObservation(
        platform=PlatformFamily.IOS_XE,
        interfaces=(
            _record(1),
            _record(
                2,
                interface="GigabitEthernet2/0/1",
                switchport_enabled=None,
                administrative_mode=None,
                operational_mode=None,
                access_vlan=None,
                native_vlan=None,
                allowed_vlans=None,
                voice_vlan="none",
                negotiation_of_trunking=None,
            ),
        ),
    )

    payload = observation.model_dump(mode="json")
    assert set(payload) == {"schema_version", "vendor", "platform", "interfaces"}
    assert set(payload["interfaces"][0]) == {
        "ordinal",
        "interface",
        "switchport_enabled",
        "administrative_mode",
        "operational_mode",
        "access_vlan",
        "native_vlan",
        "allowed_vlans",
        "voice_vlan",
        "negotiation_of_trunking",
    }
    assert payload["platform"] == "ios_xe"
    assert payload["interfaces"][1]["switchport_enabled"] is None
    assert payload["interfaces"][1]["voice_vlan"] == "none"

    restored = SwitchportObservation.model_validate_json(observation.model_dump_json())
    assert restored == observation


def test_contract_contains_no_raw_evidence_parser_or_assessment_fields() -> None:
    assert set(SwitchportRecord.model_fields) == {
        "ordinal",
        "interface",
        "switchport_enabled",
        "administrative_mode",
        "operational_mode",
        "access_vlan",
        "native_vlan",
        "allowed_vlans",
        "voice_vlan",
        "negotiation_of_trunking",
    }
    assert set(SwitchportObservation.model_fields) == {
        "schema_version",
        "vendor",
        "platform",
        "interfaces",
    }
