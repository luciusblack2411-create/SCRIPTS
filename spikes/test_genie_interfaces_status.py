import hashlib
from pathlib import Path
from uuid import uuid4

from cisco_assessment.catalog.enums import CommandId
from cisco_assessment.models import CommandExecution, RawCommandOutput
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.models.interface import InterfaceObservation
from cisco_assessment.parsers.ios.show_interfaces_status import IOSShowInterfacesStatusParser
from cisco_assessment.parsers.models import ParseStatus

FIXTURE = (
    Path(__file__).parents[1]
    / "tests"
    / "fixtures"
    / "ios"
    / "show_interfaces_status"
    / "c9300_iosxe_genie_spike.txt"
)

EXPECTED_GENIE = {
    "interfaces": {
        "GigabitEthernet1/0/1": {
            "name": "USER-ACCESS",
            "status": "connected",
            "vlan": "10",
            "duplex_code": "a-full",
            "port_speed": "a-1000",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/2": {
            "status": "notconnect",
            "vlan": "20",
            "duplex_code": "auto",
            "port_speed": "auto",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/3": {
            "name": "ADMIN-DOWN",
            "status": "disabled",
            "vlan": "30",
            "duplex_code": "auto",
            "port_speed": "auto",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/4": {
            "name": "BPDU-GUARD",
            "status": "err-disabled",
            "vlan": "40",
            "duplex_code": "auto",
            "port_speed": "auto",
            "type": "10/100/1000BaseTX",
        },
        "GigabitEthernet1/0/47": {
            "name": "CORE-TRUNK",
            "status": "connected",
            "vlan": "trunk",
            "duplex_code": "a-full",
            "port_speed": "a-1000",
            "type": "1000BaseLX SFP",
        },
        "TenGigabitEthernet1/1/1": {
            "name": "DIST-UPLINK",
            "status": "connected",
            "vlan": "routed",
            "duplex_code": "full",
            "port_speed": "a-10G",
            "type": "10GBase-SR",
        },
        "Port-channel10": {
            "name": "SERVER-LAG",
            "status": "connected",
            "vlan": "trunk",
            "duplex_code": "a-full",
            "port_speed": "a-10G",
        },
    }
}


def _execution() -> CommandExecution:
    return CommandExecution(
        assessment_run_id=uuid4(),
        command_key=CommandId.INTERFACES_STATUS.value,
        command="show interfaces status",
        sequence=1,
    )


def test_genie_cli_accepts_precollected_output_with_no_device() -> None:
    from genie.libs.parser.iosxe.show_interface import ShowInterfacesStatus

    content = FIXTURE.read_text(encoding="utf-8")
    parsed = ShowInterfacesStatus(device=None).cli(output=content)

    assert parsed == EXPECTED_GENIE


def test_framework_genie_extraction_returns_all_ports_exactly_once() -> None:
    content = FIXTURE.read_text(encoding="utf-8")
    parsed = IOSShowInterfacesStatusParser().extract_genie_structure(content)
    interfaces = parsed["interfaces"]

    assert parsed == EXPECTED_GENIE
    assert len(interfaces) == 7
    assert len(set(interfaces)) == 7
    assert list(interfaces) == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/3",
        "GigabitEthernet1/0/4",
        "GigabitEthernet1/0/47",
        "TenGigabitEthernet1/1/1",
        "Port-channel10",
    ]

    assert interfaces["GigabitEthernet1/0/1"]["status"] == "connected"
    assert interfaces["GigabitEthernet1/0/2"]["status"] == "notconnect"
    assert interfaces["GigabitEthernet1/0/3"]["status"] == "disabled"
    assert interfaces["GigabitEthernet1/0/4"]["status"] == "err-disabled"

    assert interfaces["GigabitEthernet1/0/1"]["vlan"] == "10"
    assert interfaces["GigabitEthernet1/0/47"]["vlan"] == "trunk"
    assert interfaces["TenGigabitEthernet1/1/1"]["vlan"] == "routed"

    assert interfaces["GigabitEthernet1/0/2"]["duplex_code"] == "auto"
    assert interfaces["GigabitEthernet1/0/47"]["duplex_code"] == "a-full"
    assert interfaces["GigabitEthernet1/0/2"]["port_speed"] == "auto"
    assert interfaces["GigabitEthernet1/0/47"]["port_speed"] == "a-1000"
    assert interfaces["TenGigabitEthernet1/1/1"]["port_speed"] == "a-10G"

    assert interfaces["GigabitEthernet1/0/47"]["type"] == "1000BaseLX SFP"
    assert interfaces["TenGigabitEthernet1/1/1"]["type"] == "10GBase-SR"
    assert "type" not in interfaces["Port-channel10"]


def test_adapter_preserves_raw_and_builds_framework_model_and_evidence() -> None:
    execution = _execution()
    content = FIXTURE.read_text(encoding="utf-8")
    original_bytes = content.encode("utf-8")
    independent_sha256 = hashlib.sha256(original_bytes).hexdigest()
    raw = RawCommandOutput.from_text(command_execution_id=execution.id, content=content)
    original_sha256 = raw.sha256

    result = IOSShowInterfacesStatusParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )

    assert result.status is ParseStatus.SUCCESS
    assert isinstance(result.data, InterfaceObservation)
    assert [item.interface for item in result.data.interfaces] == list(EXPECTED_GENIE["interfaces"])
    assert [item.status for item in result.data.interfaces] == [
        "connected",
        "notconnect",
        "disabled",
        "err-disabled",
        "connected",
        "connected",
        "connected",
    ]
    assert result.data.interfaces[0].vlan == "10"
    assert result.data.interfaces[1].description is None
    assert result.data.interfaces[4].vlan == "trunk"
    assert result.data.interfaces[5].vlan == "routed"
    assert result.data.interfaces[1].duplex == "auto"
    assert result.data.interfaces[4].duplex == "a-full"
    assert result.data.interfaces[1].speed == "auto"
    assert result.data.interfaces[4].speed == "a-1000"
    assert result.data.interfaces[5].speed == "a-10G"
    assert result.data.interfaces[4].media_type == "1000BaseLX SFP"
    assert result.data.interfaces[5].media_type == "10GBase-SR"
    assert result.data.interfaces[6].media_type is None

    evidence_by_field = {item.field: item for item in result.evidence}
    assert [
        evidence_by_field[f"interfaces[{index}].status"].line_start for index in range(7)
    ] == [2, 3, 4, 5, 6, 7, 8]
    assert evidence_by_field["interfaces[0].interface"].line_start == 2
    assert evidence_by_field["interfaces[4].vlan"].line_start == 6
    assert evidence_by_field["interfaces[5].media_type"].line_start == 7
    assert "interfaces[1].description" not in evidence_by_field
    assert "interfaces[6].media_type" not in evidence_by_field

    assert result.warnings == ()
    assert raw.sha256 == independent_sha256
    assert result.trace.raw_sha256 == independent_sha256
    assert original_sha256 == independent_sha256
    assert raw.content == content
    assert raw.content.encode(raw.encoding) == original_bytes
