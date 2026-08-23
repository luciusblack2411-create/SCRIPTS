from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    INTERFACE_OBSERVATION_SCHEMA_VERSION,
    InterfaceObservation,
    InterfaceStatusRecord,
    PlatformFamily,
)


def _record(
    ordinal: int,
    *,
    interface: str,
    description: str | None = "Observed interface",
    status: str = "connected",
    vlan: str = "10",
    duplex: str = "a-full",
    speed: str = "a-1000",
    media_type: str | None = "10/100/1000BaseTX",
) -> InterfaceStatusRecord:
    return InterfaceStatusRecord(
        ordinal=ordinal,
        interface=interface,
        description=description,
        status=status,
        vlan=vlan,
        duplex=duplex,
        speed=speed,
        media_type=media_type,
    )


def test_observation_supports_physical_stack_members_and_port_channel() -> None:
    member_1 = _record(
        1,
        interface="GigabitEthernet1/0/1",
        description="USER-ACCESS",
        status="connected",
        vlan="10",
        duplex="a-full",
        speed="a-1000",
    )
    member_2 = _record(
        2,
        interface="GigabitEthernet2/0/1",
        description=None,
        status="notconnect",
        vlan="20",
        duplex="auto",
        speed="auto",
    )
    port_channel = _record(
        3,
        interface="Port-channel10",
        description="SERVER-LAG",
        status="connected",
        vlan="trunk",
        duplex="a-full",
        speed="a-10G",
        media_type=None,
    )

    observation = InterfaceObservation(
        platform=PlatformFamily.IOS_XE,
        interfaces=(member_1, member_2, port_channel),
    )

    assert observation.schema_version == INTERFACE_OBSERVATION_SCHEMA_VERSION == "0.1"
    assert observation.vendor == "Cisco"
    assert [record.ordinal for record in observation.interfaces] == [1, 2, 3]
    assert [record.interface for record in observation.interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet2/0/1",
        "Port-channel10",
    ]
    assert observation.interfaces[1].description is None
    assert observation.interfaces[2].media_type is None


def test_observed_cli_tokens_remain_open_strings_and_preserve_unknown_values() -> None:
    record = _record(
        1,
        interface="  TwentyFiveGigE1/0/1  ",
        status="  future-valid-state  ",
        vlan="  fabric-overlay  ",
        duplex="  adaptive  ",
        speed="  a-25G  ",
        media_type="  future-optic-type  ",
    )

    assert record.interface == "TwentyFiveGigE1/0/1"
    assert record.status == "future-valid-state"
    assert record.vlan == "fabric-overlay"
    assert record.duplex == "adaptive"
    assert record.speed == "a-25G"
    assert record.media_type == "future-optic-type"


def test_optional_description_and_media_normalize_blank_to_none() -> None:
    record = _record(
        1,
        interface="GigabitEthernet1/0/2",
        description="   ",
        media_type="   ",
    )

    assert record.description is None
    assert record.media_type is None


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
    records: tuple[InterfaceStatusRecord, ...],
) -> None:
    with pytest.raises(ValidationError, match="ordinals must be contiguous"):
        InterfaceObservation(platform=PlatformFamily.IOS_XE, interfaces=records)


def test_observation_rejects_duplicate_canonical_interface_names() -> None:
    with pytest.raises(ValidationError, match="interface names must be unique"):
        InterfaceObservation(
            platform=PlatformFamily.IOS_XE,
            interfaces=(
                _record(1, interface="GigabitEthernet1/0/1"),
                _record(2, interface="GigabitEthernet1/0/1"),
            ),
        )


@pytest.mark.parametrize("field", ("interface", "status", "vlan", "duplex", "speed"))
def test_record_rejects_blank_required_text(field: str) -> None:
    values: dict[str, object] = {
        "ordinal": 1,
        "interface": "GigabitEthernet1/0/1",
        "status": "connected",
        "vlan": "10",
        "duplex": "a-full",
        "speed": "a-1000",
    }
    values[field] = "   "

    with pytest.raises(ValidationError, match="value must not be blank"):
        InterfaceStatusRecord.model_validate(values)


def test_models_are_immutable_and_forbid_extra_fields() -> None:
    record = _record(1, interface="GigabitEthernet1/0/1")
    observation = InterfaceObservation(
        platform=PlatformFamily.IOS_XE,
        interfaces=(record,),
    )

    with pytest.raises(ValidationError):
        record.status = "disabled"

    with pytest.raises(ValidationError):
        observation.interfaces = ()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InterfaceStatusRecord.model_validate(
            {
                **record.model_dump(),
                "raw_line": "Gi1/0/1 ...",
            }
        )


def test_interface_observation_json_round_trip_is_canonical() -> None:
    observation = InterfaceObservation(
        platform=PlatformFamily.IOS_XE,
        interfaces=(
            _record(
                1,
                interface="GigabitEthernet1/0/47",
                description="CORE-TRUNK",
                vlan="trunk",
                media_type="1000BaseLX SFP",
            ),
            _record(
                2,
                interface="TenGigabitEthernet1/1/1",
                description="DIST-UPLINK",
                vlan="routed",
                duplex="full",
                speed="a-10G",
                media_type="10GBase-SR",
            ),
        ),
    )

    payload = observation.model_dump(mode="json")
    assert set(payload) == {"schema_version", "vendor", "platform", "interfaces"}
    assert set(payload["interfaces"][0]) == {
        "ordinal",
        "interface",
        "description",
        "status",
        "vlan",
        "duplex",
        "speed",
        "media_type",
    }
    assert payload["platform"] == "ios_xe"
    assert payload["interfaces"][0]["interface"] == "GigabitEthernet1/0/47"
    assert payload["interfaces"][1]["vlan"] == "routed"

    restored = InterfaceObservation.model_validate_json(observation.model_dump_json())
    assert restored == observation
