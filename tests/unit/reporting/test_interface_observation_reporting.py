from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from cisco_assessment.assessment import (
    AssessmentResult,
    AssessmentStatus,
    Finding,
    FindingEvidence,
    FindingSeverity,
    RuleOutcome,
    SourceTrace,
)
from cisco_assessment.models import (
    AssessmentRun,
    AssessmentRunStatus,
    DeviceInfo,
    DeviceSnapshot,
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
    InterfaceObservation,
    InterfaceStatusRecord,
    PlatformFamily,
)
from cisco_assessment.reporting import AssessmentReportBuilder, JsonReportRenderer

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
DEVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
INTERFACE_COMMAND_EXECUTION_ID = UUID("33333333-3333-3333-3333-333333333333")
INTERFACE_RAW_OUTPUT_ID = UUID("44444444-4444-4444-4444-444444444444")
INTERFACE_FINDING_ID = UUID("55555555-5555-5555-5555-555555555555")
GENERATED_AT = datetime(2026, 8, 22, 18, 30, tzinfo=UTC)


def _base_inputs() -> tuple[AssessmentRun, AssessmentResult, DeviceInfo]:
    run = AssessmentRun(
        id=RUN_ID,
        device_id=DEVICE_ID,
        framework_version="0.1.0",
        started_at=datetime(2026, 8, 22, 18, 20, tzinfo=UTC),
        finished_at=datetime(2026, 8, 22, 18, 21, tzinfo=UTC),
        status=AssessmentRunStatus.COMPLETED,
        target_snapshot=DeviceSnapshot(
            management_address="192.0.2.10",
            hostname="SW-CORE-01",
            platform_family=PlatformFamily.IOS_XE,
        ),
        command_catalog_version="0.1.0",
        ruleset_version="0.1.0",
    )
    result = AssessmentResult(
        assessment_run_id=RUN_ID,
        device_id=DEVICE_ID,
        platform=PlatformFamily.IOS_XE,
        normalized_model="DeviceInfo",
        outcomes=(),
        findings=(),
    )
    device_info = DeviceInfo(
        platform=PlatformFamily.IOS_XE,
        hostname="SW-CORE-01",
        software_version="17.18.01",
        model="C9300-48P",
        serial_number="FCW00000001",
    )
    return run, result, device_info


def _hardware_inventory() -> HardwareInventory:
    return HardwareInventory(
        platform=PlatformFamily.IOS_XE,
        records=(
            HardwareInventoryRecord(
                ordinal=1,
                name="Switch 1",
                description="Cisco Catalyst 9300 48 Port PoE+ Switch",
                pid="C9300-48P",
                vid="V02",
                serial_number="FOC0000AAAA",
                component_type=HardwareComponentType.CHASSIS_MEMBER,
            ),
        ),
    )


def _interface_observation() -> InterfaceObservation:
    return InterfaceObservation(
        platform=PlatformFamily.IOS_XE,
        interfaces=(
            InterfaceStatusRecord(
                ordinal=1,
                interface="GigabitEthernet1/0/1",
                description="USER-ACCESS",
                status="connected",
                vlan="10",
                duplex="a-full",
                speed="a-1000",
                media_type="10/100/1000BaseTX",
            ),
            InterfaceStatusRecord(
                ordinal=2,
                interface="GigabitEthernet2/0/3",
                description=None,
                status="notconnect",
                vlan="20",
                duplex="auto",
                speed="auto",
                media_type="10/100/1000BaseTX",
            ),
            InterfaceStatusRecord(
                ordinal=3,
                interface="GigabitEthernet1/0/47",
                description="CORE-TRUNK",
                status="connected",
                vlan="trunk",
                duplex="a-full",
                speed="a-1000",
                media_type="1000BaseLX SFP",
            ),
            InterfaceStatusRecord(
                ordinal=4,
                interface="TenGigabitEthernet1/1/1",
                description="DIST-UPLINK",
                status="connected",
                vlan="routed",
                duplex="full",
                speed="a-10G",
                media_type="10GBase-SR",
            ),
            InterfaceStatusRecord(
                ordinal=5,
                interface="Port-channel10",
                description="SERVER-LAG",
                status="connected",
                vlan="trunk",
                duplex="a-full",
                speed="a-10G",
                media_type=None,
            ),
        ),
    )


def test_interface_observation_report_preserves_canonical_values_order_and_optionals() -> None:
    run, result, device_info = _base_inputs()
    observation = _interface_observation()

    report = AssessmentReportBuilder().build(
        run=run,
        result=result,
        device_info=device_info,
        interface_observation=observation,
        generated_at=GENERATED_AT,
    )

    assert report.interface_observation is not None
    assert report.interface_observation.normalized_model == "InterfaceObservation"
    assert report.interface_observation.schema_version == "0.1"
    records = report.interface_observation.interfaces
    assert [record.ordinal for record in records] == [1, 2, 3, 4, 5]
    assert [record.interface for record in records] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet2/0/3",
        "GigabitEthernet1/0/47",
        "TenGigabitEthernet1/1/1",
        "Port-channel10",
    ]
    assert records[0].description == "USER-ACCESS"
    assert records[0].status == "connected"
    assert records[0].vlan == "10"
    assert records[0].duplex == "a-full"
    assert records[0].speed == "a-1000"
    assert records[0].media_type == "10/100/1000BaseTX"
    assert records[1].description is None
    assert records[1].interface == "GigabitEthernet2/0/3"
    assert records[2].vlan == "trunk"
    assert records[3].vlan == "routed"
    assert records[4].interface == "Port-channel10"
    assert records[4].media_type is None

    payload = json.loads(JsonReportRenderer().render(report).content)
    interface_payload = payload["interface_observation"]
    assert set(interface_payload) == {
        "interfaces",
        "normalized_model",
        "platform",
        "schema_version",
        "vendor",
    }
    assert interface_payload["interfaces"][0] == {
        "description": "USER-ACCESS",
        "duplex": "a-full",
        "interface": "GigabitEthernet1/0/1",
        "media_type": "10/100/1000BaseTX",
        "ordinal": 1,
        "speed": "a-1000",
        "status": "connected",
        "vlan": "10",
    }
    assert interface_payload["interfaces"][1]["description"] is None
    assert interface_payload["interfaces"][4]["media_type"] is None


def test_interface_observation_coexists_with_device_info_and_hardware_inventory() -> None:
    run, result, device_info = _base_inputs()

    report = AssessmentReportBuilder().build(
        run=run,
        result=result,
        device_info=device_info,
        hardware_inventory=_hardware_inventory(),
        interface_observation=_interface_observation(),
        generated_at=GENERATED_AT,
    )

    assert report.device_info.hostname == "SW-CORE-01"
    assert report.device_info.software_version == "17.18.01"
    assert report.hardware_inventory is not None
    assert report.hardware_inventory.records[0].id == "hw:0001"
    assert report.hardware_inventory.records[0].pid == "C9300-48P"
    assert report.interface_observation is not None
    assert report.interface_observation.interfaces[0].interface == "GigabitEthernet1/0/1"

    payload = json.loads(JsonReportRenderer().render(report).content)
    assert payload["device_info"]["hostname"] == "SW-CORE-01"
    assert payload["hardware_inventory"]["records"][0]["id"] == "hw:0001"
    assert payload["interface_observation"]["interfaces"][4]["interface"] == "Port-channel10"


def test_interface_field_path_and_source_trace_are_preserved_without_reinterpretation() -> None:
    run, result, device_info = _base_inputs()
    source = SourceTrace(
        assessment_run_id=RUN_ID,
        command_execution_id=INTERFACE_COMMAND_EXECUTION_ID,
        raw_output_id=INTERFACE_RAW_OUTPUT_ID,
        raw_sha256="c" * 64,
        parser_id="ios.show_interfaces_status.v1",
        parser_version="0.1.0",
        platform=PlatformFamily.IOS_XE,
        extractor="interfaces_status_raw_line",
        line_start=3,
        line_end=3,
    )
    evidence = FindingEvidence(
        normalized_model="InterfaceObservation",
        field_path="interfaces[1].vlan",
        observed_value="20",
        sources=(source,),
    )
    outcome = RuleOutcome(
        rule_id="INT-TRACE-001",
        rule_version="0.1.0",
        title="Interface field trace",
        category="interfaces",
        normalized_model="InterfaceObservation",
        status=AssessmentStatus.INFO,
        severity=FindingSeverity.INFO,
        message="Interface evidence is traceable.",
        evidence=(evidence,),
    )
    finding = Finding(
        finding_id=INTERFACE_FINDING_ID,
        rule_id="INT-TRACE-001",
        rule_version="0.1.0",
        title="Interface field trace",
        description="Reporting regression for InterfaceObservation field paths.",
        category="interfaces",
        normalized_model="InterfaceObservation",
        status=AssessmentStatus.INFO,
        severity=FindingSeverity.INFO,
        evidence=(evidence,),
    )
    traced_result = result.model_copy(
        update={"outcomes": (outcome,), "findings": (finding,)}
    )

    report = AssessmentReportBuilder().build(
        run=run,
        result=traced_result,
        device_info=device_info,
        interface_observation=_interface_observation(),
        generated_at=GENERATED_AT,
    )

    reported_finding = report.findings[0]
    reported_evidence = reported_finding.evidence[0]
    assert reported_evidence.normalized_model == "InterfaceObservation"
    assert reported_evidence.field_path == "interfaces[1].vlan"
    assert reported_evidence.observed_value == "20"
    reported_source = reported_evidence.sources[0]
    assert reported_source.command_execution_id == INTERFACE_COMMAND_EXECUTION_ID
    assert reported_source.raw_output_id == INTERFACE_RAW_OUTPUT_ID
    assert reported_source.raw_sha256 == "c" * 64
    assert reported_source.parser_id == "ios.show_interfaces_status.v1"
    assert reported_source.parser_version == "0.1.0"
    assert reported_source.line_start == 3
    assert reported_source.line_end == 3

    payload = json.loads(JsonReportRenderer().render(report).content)
    payload_evidence = payload["findings"][0]["evidence"][0]
    assert payload_evidence["field_path"] == "interfaces[1].vlan"
    assert payload_evidence["observed_value"] == "20"
    assert payload_evidence["sources"][0]["command_execution_id"] == str(
        INTERFACE_COMMAND_EXECUTION_ID
    )
    assert payload_evidence["sources"][0]["raw_output_id"] == str(INTERFACE_RAW_OUTPUT_ID)
    assert payload_evidence["sources"][0]["raw_sha256"] == "c" * 64
    assert payload_evidence["sources"][0]["line_start"] == 3
    assert payload_evidence["sources"][0]["line_end"] == 3
