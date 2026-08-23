from __future__ import annotations

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    VLAN_OBSERVATION_SCHEMA_VERSION,
    PlatformFamily,
    VlanObservation,
    VlanRecord,
    VlanStatus,
)


def _record(
    ordinal: int,
    *,
    vlan_id: int,
    name: str | None = "USERS",
    status: VlanStatus = VlanStatus.ACTIVE,
    ports: tuple[str, ...] | None = ("Gi1/0/1",),
) -> VlanRecord:
    return VlanRecord(
        ordinal=ordinal,
        vlan_id=vlan_id,
        name=name,
        status=status,
        ports=ports,
    )


def test_observation_preserves_vlan_order_and_explicit_port_states() -> None:
    observation = VlanObservation(
        platform=PlatformFamily.IOS_XE,
        vlans=(
            _record(
                1,
                vlan_id=1,
                name="default",
                ports=("Gi1/0/2", "Gi1/0/3", "Gi2/0/1"),
            ),
            _record(2, vlan_id=40, name="vlan-40", ports=()),
            _record(
                3,
                vlan_id=1002,
                name="fddi-default",
                status=VlanStatus.ACTIVE_UNSUPPORTED,
                ports=None,
            ),
        ),
    )

    assert observation.schema_version == VLAN_OBSERVATION_SCHEMA_VERSION == "0.1"
    assert observation.vendor == "Cisco"
    assert [record.ordinal for record in observation.vlans] == [1, 2, 3]
    assert [record.vlan_id for record in observation.vlans] == [1, 40, 1002]
    assert observation.vlans[0].ports == ("Gi1/0/2", "Gi1/0/3", "Gi2/0/1")
    assert observation.vlans[1].ports == ()
    assert observation.vlans[2].ports is None


def test_unknown_or_missing_vlan_facts_are_explicit() -> None:
    record = _record(
        1,
        vlan_id=300,
        name=None,
        status=VlanStatus.UNKNOWN,
        ports=None,
    )

    assert record.name is None
    assert record.status is VlanStatus.UNKNOWN
    assert record.ports is None


def test_vlan_status_contract_contains_only_v0_1_states() -> None:
    assert {status.value for status in VlanStatus} == {
        "active",
        "suspend",
        "act/unsup",
        "unknown",
    }


@pytest.mark.parametrize("vlan_id", (1, 4094))
def test_vlan_id_accepts_documented_range_boundaries(vlan_id: int) -> None:
    assert _record(1, vlan_id=vlan_id).vlan_id == vlan_id


@pytest.mark.parametrize("vlan_id", (0, 4095, -1))
def test_vlan_id_rejects_values_outside_documented_range(vlan_id: int) -> None:
    with pytest.raises(ValidationError):
        _record(1, vlan_id=vlan_id)


def test_vlan_id_is_strict_and_does_not_coerce_text() -> None:
    with pytest.raises(ValidationError):
        VlanRecord.model_validate(
            {
                "ordinal": 1,
                "vlan_id": "40",
                "name": "vlan-40",
                "status": "active",
                "ports": [],
            }
        )


def test_vlan_name_rejects_more_than_32_characters() -> None:
    with pytest.raises(ValidationError):
        _record(1, vlan_id=40, name="x" * 33)


@pytest.mark.parametrize(
    "records",
    (
        (
            _record(1, vlan_id=10),
            _record(3, vlan_id=20),
        ),
        (
            _record(2, vlan_id=10),
            _record(1, vlan_id=20),
        ),
    ),
)
def test_observation_rejects_missing_or_reordered_ordinals(
    records: tuple[VlanRecord, ...],
) -> None:
    with pytest.raises(ValidationError, match="ordinals must be contiguous"):
        VlanObservation(platform=PlatformFamily.IOS_XE, vlans=records)


def test_observation_rejects_duplicate_vlan_ids() -> None:
    with pytest.raises(ValidationError, match="VLAN IDs must be unique"):
        VlanObservation(
            platform=PlatformFamily.IOS_XE,
            vlans=(
                _record(1, vlan_id=10),
                _record(2, vlan_id=10, name="duplicate"),
            ),
        )


def test_record_normalizes_optional_name_and_port_whitespace() -> None:
    named = _record(
        1,
        vlan_id=10,
        name="  USERS  ",
        ports=("  Gi1/0/1  ", "Gi2/0/1"),
    )
    unnamed = _record(1, vlan_id=20, name="   ", ports=())

    assert named.name == "USERS"
    assert named.ports == ("Gi1/0/1", "Gi2/0/1")
    assert unnamed.name is None


def test_record_rejects_blank_or_duplicate_ports() -> None:
    with pytest.raises(ValidationError, match="blank values"):
        _record(1, vlan_id=10, ports=("Gi1/0/1", "   "))

    with pytest.raises(ValidationError, match="ports must be unique"):
        _record(1, vlan_id=10, ports=("Gi1/0/1", " Gi1/0/1 "))


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    record = _record(1, vlan_id=10)
    observation = VlanObservation(
        platform=PlatformFamily.IOS,
        vlans=(record,),
    )

    with pytest.raises(ValidationError):
        record.name = "CHANGED"

    with pytest.raises(ValidationError):
        observation.vlans = ()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VlanRecord.model_validate(
            {
                **record.model_dump(),
                "raw_line": "10 USERS active Gi1/0/1",
            }
        )


def test_vlan_observation_json_round_trip_is_canonical() -> None:
    observation = VlanObservation(
        platform=PlatformFamily.IOS_XE,
        vlans=(
            _record(1, vlan_id=10, name="USERS", ports=("Gi1/0/1", "Gi2/0/1")),
            _record(2, vlan_id=20, name="SERVERS", ports=()),
            _record(
                3,
                vlan_id=30,
                name=None,
                status=VlanStatus.UNKNOWN,
                ports=None,
            ),
        ),
    )

    payload = observation.model_dump(mode="json")
    assert set(payload) == {"schema_version", "vendor", "platform", "vlans"}
    assert set(payload["vlans"][0]) == {
        "ordinal",
        "vlan_id",
        "name",
        "status",
        "ports",
    }
    assert payload["platform"] == "ios_xe"
    assert payload["vlans"][0]["ports"] == ["Gi1/0/1", "Gi2/0/1"]
    assert payload["vlans"][1]["ports"] == []
    assert payload["vlans"][2]["ports"] is None
    assert payload["vlans"][2]["status"] == "unknown"

    restored = VlanObservation.model_validate_json(observation.model_dump_json())
    assert restored == observation


def test_contract_contains_no_evidence_or_parser_fields() -> None:
    assert set(VlanRecord.model_fields) == {
        "ordinal",
        "vlan_id",
        "name",
        "status",
        "ports",
    }
    assert set(VlanObservation.model_fields) == {
        "schema_version",
        "vendor",
        "platform",
        "vlans",
    }
