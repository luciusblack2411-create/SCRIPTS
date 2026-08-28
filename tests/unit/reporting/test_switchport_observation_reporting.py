from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

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
    SwitchportObservation,
    SwitchportRecord,
    VlanObservation,
    VlanRecord,
    VlanStatus,
)
from cisco_assessment.reporting import (
    AssessmentReportBuilder,
    JsonReportRenderer,
    ReportBuildError,
    SwitchportObservationReport,
    SwitchportRecordReport,
)

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
DEVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
SWITCHPORT_COMMAND_EXECUTION_ID = UUID("33333333-3333-3333-3333-333333333333")
SWITCHPORT_RAW_OUTPUT_ID = UUID("44444444-4444-4444-4444-444444444444")
SWITCHPORT_FINDING_ID = UUID("55555555-5555-5555-5555-555555555555")
GENERATED_AT = datetime(2026, 8, 27, 17, 0, tzinfo=UTC)
SWITCHPORT_RAW_SHA256 = "901b9a1a3aed745e4f228c0c5332bf956293078654d4f15c5f086cc051cce422"


def _base_inputs() -> tuple[AssessmentRun, AssessmentResult, DeviceInfo]:
    run = AssessmentRun(
        id=RUN_ID,
        device_id=DEVICE_ID,
        framework_version="0.1.0",
        started_at=datetime(2026, 8, 27, 16, 55, tzinfo=UTC),
        finished_at=datetime(2026, 8, 27, 16, 56, tzinfo=UTC),
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


def _switchport_observation(
    platform: PlatformFamily = PlatformFamily.IOS_XE,
) -> SwitchportObservation:
    return SwitchportObservation(
        platform=platform,
        interfaces=(
            SwitchportRecord(
                ordinal=1,
                interface="GigabitEthernet1/0/1",
                switchport_enabled=True,
                administrative_mode="static access",
                operational_mode="static access",
                access_vlan="10",
                native_vlan="1",
                allowed_vlans="ALL",
                voice_vlan="none",
                negotiation_of_trunking=True,
            ),
            SwitchportRecord(
                ordinal=2,
                interface="GigabitEthernet2/0/3",
                switchport_enabled=False,
                administrative_mode=None,
                operational_mode=None,
                access_vlan=None,
                native_vlan=None,
                allowed_vlans=None,
                voice_vlan=None,
                negotiation_of_trunking=False,
            ),
            SwitchportRecord(
                ordinal=3,
                interface="Port-channel10",
                switchport_enabled=None,
                administrative_mode="trunk",
                operational_mode="trunk",
                access_vlan="none",
                native_vlan="99",
                allowed_vlans="10,20,99",
                voice_vlan="none",
                negotiation_of_trunking=None,
            ),
        ),
    )


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
        ),
    )


def _vlan_observation() -> VlanObservation:
    return VlanObservation(
        platform=PlatformFamily.IOS_XE,
        vlans=(
            VlanRecord(
                ordinal=1,
                vlan_id=10,
                name="USERS",
                status=VlanStatus.ACTIVE,
                ports=("Gi1/0/1",),
            ),
        ),
    )


def test_switchport_observation_report_preserves_contract_order_values_and_none() -> None:
    run, result, device_info = _base_inputs()

    report = AssessmentReportBuilder().build(
        run=run,
        result=result,
        device_info=device_info,
        switchport_observation=_switchport_observation(),
        generated_at=GENERATED_AT,
    )

    assert report.schema_version == "0.1"
    assert report.switchport_observation is not None
    assert isinstance(report.switchport_observation, SwitchportObservationReport)
    assert report.switchport_observation.normalized_model == "SwitchportObservation"
    assert report.switchport_observation.schema_version == "0.1"
    assert report.switchport_observation.vendor == "Cisco"
    assert report.switchport_observation.platform is PlatformFamily.IOS_XE

    records = report.switchport_observation.interfaces
    assert all(isinstance(record, SwitchportRecordReport) for record in records)
    assert [record.ordinal for record in records] == [1, 2, 3]
    assert [record.interface for record in records] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet2/0/3",
        "Port-channel10",
    ]

    assert records[0].switchport_enabled is True
    assert records[1].switchport_enabled is False
    assert records[2].switchport_enabled is None
    assert records[0].negotiation_of_trunking is True
    assert records[1].negotiation_of_trunking is False
    assert records[2].negotiation_of_trunking is None

    assert records[0].administrative_mode == "static access"
    assert records[0].operational_mode == "static access"
    assert records[0].access_vlan == "10"
    assert records[0].native_vlan == "1"
    assert records[0].allowed_vlans == "ALL"
    assert records[0].voice_vlan == "none"

    assert records[1].administrative_mode is None
    assert records[1].operational_mode is None
    assert records[1].access_vlan is None
    assert records[1].native_vlan is None
    assert records[1].allowed_vlans is None
    assert records[1].voice_vlan is None

    assert records[2].administrative_mode == "trunk"
    assert records[2].operational_mode == "trunk"
    assert records[2].access_vlan == "none"
    assert records[2].native_vlan == "99"
    assert records[2].allowed_vlans == "10,20,99"
    assert records[2].voice_vlan == "none"


def test_switchport_observation_absence_is_clean_and_json_renderer_is_deterministic() -> None:
    run, result, device_info = _base_inputs()
    builder = AssessmentReportBuilder()

    without_switchport = builder.build(
        run=run,
        result=result,
        device_info=device_info,
        generated_at=GENERATED_AT,
    )
    assert without_switchport.switchport_observation is None

    with_switchport = builder.build(
        run=run,
        result=result,
        device_info=device_info,
        switchport_observation=_switchport_observation(),
        generated_at=GENERATED_AT,
    )
    renderer = JsonReportRenderer()
    rendered_once = renderer.render(with_switchport)
    rendered_twice = renderer.render(with_switchport)
    assert rendered_once.content == rendered_twice.content

    payload = json.loads(rendered_once.content)
    assert payload["switchport_observation"] == {
        "interfaces": [
            {
                "access_vlan": "10",
                "administrative_mode": "static access",
                "allowed_vlans": "ALL",
                "interface": "GigabitEthernet1/0/1",
                "native_vlan": "1",
                "negotiation_of_trunking": True,
                "operational_mode": "static access",
                "ordinal": 1,
                "switchport_enabled": True,
                "voice_vlan": "none",
            },
            {
                "access_vlan": None,
                "administrative_mode": None,
                "allowed_vlans": None,
                "interface": "GigabitEthernet2/0/3",
                "native_vlan": None,
                "negotiation_of_trunking": False,
                "operational_mode": None,
                "ordinal": 2,
                "switchport_enabled": False,
                "voice_vlan": None,
            },
            {
                "access_vlan": "none",
                "administrative_mode": "trunk",
                "allowed_vlans": "10,20,99",
                "interface": "Port-channel10",
                "native_vlan": "99",
                "negotiation_of_trunking": None,
                "operational_mode": "trunk",
                "ordinal": 3,
                "switchport_enabled": None,
                "voice_vlan": "none",
            },
        ],
        "normalized_model": "SwitchportObservation",
        "platform": "ios_xe",
        "schema_version": "0.1",
        "vendor": "Cisco",
    }


def test_switchport_observation_platform_mismatch_raises_report_build_error() -> None:
    run, result, device_info = _base_inputs()

    with pytest.raises(
        ReportBuildError,
        match="SwitchportObservation platform does not match DeviceInfo platform",
    ):
        AssessmentReportBuilder().build(
            run=run,
            result=result,
            device_info=device_info,
            switchport_observation=_switchport_observation(PlatformFamily.IOS),
            generated_at=GENERATED_AT,
        )


def test_switchport_observation_coexists_with_existing_report_domains() -> None:
    run, result, device_info = _base_inputs()

    report = AssessmentReportBuilder().build(
        run=run,
        result=result,
        device_info=device_info,
        hardware_inventory=_hardware_inventory(),
        interface_observation=_interface_observation(),
        vlan_observation=_vlan_observation(),
        switchport_observation=_switchport_observation(),
        generated_at=GENERATED_AT,
    )

    assert report.device_info.hostname == "SW-CORE-01"
    assert report.hardware_inventory is not None
    assert report.hardware_inventory.records[0].id == "hw:0001"
    assert report.interface_observation is not None
    assert report.interface_observation.interfaces[0].interface == "GigabitEthernet1/0/1"
    assert report.vlan_observation is not None
    assert report.vlan_observation.vlans[0].vlan_id == 10
    assert report.switchport_observation is not None
    assert report.switchport_observation.interfaces[2].interface == "Port-channel10"


def test_switchport_findings_outcomes_and_source_trace_are_preserved() -> None:
    run, result, device_info = _base_inputs()
    source = SourceTrace(
        assessment_run_id=RUN_ID,
        command_execution_id=SWITCHPORT_COMMAND_EXECUTION_ID,
        raw_output_id=SWITCHPORT_RAW_OUTPUT_ID,
        raw_sha256=SWITCHPORT_RAW_SHA256,
        parser_id="ios.show_interfaces_switchport.v1",
        parser_version="0.1.0",
        platform=PlatformFamily.IOS_XE,
        extractor="switchport_block",
        line_start=100,
        line_end=112,
    )
    evidence = (
        FindingEvidence(
            normalized_model="SwitchportObservation",
            field_path="interfaces[0].interface",
            observed_value="GigabitEthernet1/0/1",
            sources=(source,),
        ),
        FindingEvidence(
            normalized_model="SwitchportObservation",
            field_path="interfaces[0].administrative_mode",
            observed_value="static access",
            sources=(source,),
        ),
        FindingEvidence(
            normalized_model="SwitchportObservation",
            field_path="interfaces[0].operational_mode",
            observed_value="static access",
            sources=(source,),
        ),
        FindingEvidence(
            normalized_model="SwitchportObservation",
            field_path="interfaces[0].negotiation_of_trunking",
            observed_value=True,
            sources=(source,),
        ),
    )
    outcome = RuleOutcome(
        rule_id="SWP-002",
        rule_version="0.1.0",
        title="Administrative switchport modes observed",
        category="interfaces",
        normalized_model="SwitchportObservation",
        status=AssessmentStatus.INFO,
        severity=FindingSeverity.INFO,
        message="Observed demonstrated administrative switchport mode values.",
        evidence=evidence,
        recommendation=(
            "Compare observed modes with design intent only when authoritative intent exists."
        ),
    )
    finding = Finding(
        finding_id=SWITCHPORT_FINDING_ID,
        rule_id="SWP-002",
        rule_version="0.1.0",
        title="Administrative switchport modes observed",
        description="Reporting preserves evaluated SWP evidence without rebuilding it.",
        category="interfaces",
        normalized_model="SwitchportObservation",
        status=AssessmentStatus.INFO,
        severity=FindingSeverity.INFO,
        evidence=evidence,
        recommendation=(
            "Compare observed modes with design intent only when authoritative intent exists."
        ),
    )
    traced_result = result.model_copy(
        update={"outcomes": (outcome,), "findings": (finding,)}
    )

    report = AssessmentReportBuilder().build(
        run=run,
        result=traced_result,
        device_info=device_info,
        switchport_observation=_switchport_observation(),
        generated_at=GENERATED_AT,
    )

    assert report.outcomes[0].rule.rule_id == "SWP-002"
    assert report.findings[0].rule.rule_id == "SWP-002"
    assert [item.field_path for item in report.findings[0].evidence] == [
        "interfaces[0].interface",
        "interfaces[0].administrative_mode",
        "interfaces[0].operational_mode",
        "interfaces[0].negotiation_of_trunking",
    ]

    reported_source = report.findings[0].evidence[-1].sources[0]
    assert reported_source.command_execution_id == SWITCHPORT_COMMAND_EXECUTION_ID
    assert reported_source.raw_output_id == SWITCHPORT_RAW_OUTPUT_ID
    assert reported_source.raw_sha256 == SWITCHPORT_RAW_SHA256
    assert reported_source.parser_id == "ios.show_interfaces_switchport.v1"
    assert reported_source.parser_version == "0.1.0"
    assert reported_source.extractor == "switchport_block"
    assert reported_source.line_start == 100
    assert reported_source.line_end == 112

    payload = json.loads(JsonReportRenderer().render(report).content)
    payload_evidence = payload["findings"][0]["evidence"][-1]
    assert payload_evidence["field_path"] == "interfaces[0].negotiation_of_trunking"
    assert payload_evidence["observed_value"] is True
    assert payload_evidence["sources"][0] == {
        "assessment_run_id": str(RUN_ID),
        "command_execution_id": str(SWITCHPORT_COMMAND_EXECUTION_ID),
        "extractor": "switchport_block",
        "line_end": 112,
        "line_start": 100,
        "parser_id": "ios.show_interfaces_switchport.v1",
        "parser_version": "0.1.0",
        "platform": "ios_xe",
        "raw_output_id": str(SWITCHPORT_RAW_OUTPUT_ID),
        "raw_sha256": SWITCHPORT_RAW_SHA256,
    }


def test_reporting_productive_source_has_no_collector_parser_genie_or_pyats_dependency() -> None:
    reporting_root = Path(__file__).parents[3] / "src" / "cisco_assessment" / "reporting"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(reporting_root.rglob("*.py"))
    ).lower()

    assert "cisco_assessment.collector" not in source
    assert "cisco_assessment.parsers" not in source
    assert "genie" not in source
    assert "pyats" not in source
