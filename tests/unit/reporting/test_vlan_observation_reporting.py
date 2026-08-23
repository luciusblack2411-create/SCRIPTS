from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentResult,
    AssessmentStatus,
    NormalizedFieldSource,
    SourceTrace,
    vlan_observation_rule_catalog,
)
from cisco_assessment.catalog import CommandId, ParserId
from cisco_assessment.models import (
    AssessmentRun,
    AssessmentRunStatus,
    CommandExecution,
    DeviceInfo,
    DeviceSnapshot,
    HardwareComponentType,
    HardwareInventory,
    HardwareInventoryRecord,
    InterfaceObservation,
    InterfaceStatusRecord,
    PlatformFamily,
    RawCommandOutput,
    VlanObservation,
    VlanRecord,
    VlanStatus,
)
from cisco_assessment.parsers import IOSShowVlanBriefParser, ParseResult, ParseStatus
from cisco_assessment.reporting import AssessmentReportBuilder, JsonReportRenderer

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
DEVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
GENERATED_AT = datetime(2026, 8, 22, 23, 0, tzinfo=UTC)
FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "ios" / "show_vlan_brief"
FIXTURE = FIXTURE_DIR / "c9300_iosxe_real_sanitized.raw"
FIXTURE_SHA256 = "2e6d3d49fe2618a0b72a4d69c05704422cde736bf29d5a9cfe6982617905efd1"


def _run() -> AssessmentRun:
    return AssessmentRun(
        id=RUN_ID,
        device_id=DEVICE_ID,
        framework_version="0.1.0",
        started_at=datetime(2026, 8, 22, 22, 55, tzinfo=UTC),
        finished_at=datetime(2026, 8, 22, 22, 56, tzinfo=UTC),
        status=AssessmentRunStatus.COMPLETED,
        target_snapshot=DeviceSnapshot(
            management_address="192.0.2.10",
            hostname="SW-CORE-01",
            platform_family=PlatformFamily.IOS_XE,
        ),
        command_catalog_version="0.1.0",
        ruleset_version="0.1.0",
    )


def _device_info() -> DeviceInfo:
    return DeviceInfo(
        platform=PlatformFamily.IOS_XE,
        hostname="SW-CORE-01",
        software_version="17.18.01",
        model="C9300-48P",
        serial_number="FCW00000001",
    )


def _empty_device_result() -> AssessmentResult:
    return AssessmentResult(
        assessment_run_id=RUN_ID,
        device_id=DEVICE_ID,
        platform=PlatformFamily.IOS_XE,
        normalized_model="DeviceInfo",
        outcomes=(),
        findings=(),
    )


def _parse_real_fixture() -> tuple[RawCommandOutput, ParseResult[VlanObservation]]:
    execution = CommandExecution(
        assessment_run_id=RUN_ID,
        command_key=CommandId.VLANS_BRIEF.value,
        command="show vlan brief",
        sequence=1,
    )
    payload = FIXTURE.read_bytes()
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=payload.decode("utf-8"),
        encoding="utf-8",
    )
    result = IOSShowVlanBriefParser().parse(
        raw_output=raw,
        command_execution=execution,
        platform=PlatformFamily.IOS_XE,
    )
    assert result.status is ParseStatus.SUCCESS
    assert isinstance(result.data, VlanObservation)
    assert raw.sha256 == FIXTURE_SHA256
    return raw, result


def _context_from_parse(result: ParseResult[VlanObservation]) -> AssessmentContext:
    trace = result.trace
    source_evidence = tuple(
        NormalizedFieldSource(
            normalized_model="VlanObservation",
            field_path=evidence.field,
            source=SourceTrace(
                assessment_run_id=trace.assessment_run_id,
                command_execution_id=trace.command_execution_id,
                raw_output_id=trace.raw_output_id,
                raw_sha256=trace.raw_sha256,
                parser_id=trace.parser_id.value,
                parser_version=trace.parser_version,
                platform=trace.platform,
                extractor=evidence.extractor,
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            ),
        )
        for evidence in result.evidence
    )
    return AssessmentContext(
        assessment_run_id=RUN_ID,
        device_id=DEVICE_ID,
        platform=PlatformFamily.IOS_XE,
        source_evidence=source_evidence,
    )


def _evaluated_device_result(result: ParseResult[VlanObservation]) -> AssessmentResult:
    vlan_result = AssessmentEngine[VlanObservation](vlan_observation_rule_catalog()).evaluate(
        result.data,
        _context_from_parse(result),
    )
    return AssessmentResult(
        assessment_run_id=RUN_ID,
        device_id=DEVICE_ID,
        platform=PlatformFamily.IOS_XE,
        normalized_model="DeviceInfo",
        outcomes=vlan_result.outcomes,
        findings=vlan_result.findings,
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
                vlan="20",
                duplex="a-full",
                speed="a-1000",
                media_type="10/100/1000BaseTX",
            ),
        ),
    )


def test_real_vlan_fixture_is_serialized_in_canonical_raw_order() -> None:
    _raw, parsed = _parse_real_fixture()
    report = AssessmentReportBuilder().build(
        run=_run(),
        result=_evaluated_device_result(parsed),
        device_info=_device_info(),
        vlan_observation=parsed.data,
        generated_at=GENERATED_AT,
    )

    assert report.vlan_observation is not None
    assert report.vlan_observation.normalized_model == "VlanObservation"
    records = report.vlan_observation.vlans
    assert len(records) == 17
    assert [record.ordinal for record in records] == list(range(1, 18))
    assert [record.vlan_id for record in records] == [
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

    vlan1 = records[0]
    assert vlan1.vlan_id == 1
    assert vlan1.status is VlanStatus.ACTIVE
    assert vlan1.ports is not None
    assert len(vlan1.ports) == 54
    assert vlan1.ports[:3] == ("Gi1/0/2", "Gi1/0/3", "Gi1/0/4")
    assert vlan1.ports[-3:] == ("Gi2/1/2", "Gi2/1/3", "Gi2/1/4")
    assert all(record.ports == () for record in records[1:])
    assert [record.status for record in records[13:]] == [
        VlanStatus.ACTIVE_UNSUPPORTED,
        VlanStatus.ACTIVE_UNSUPPORTED,
        VlanStatus.ACTIVE_UNSUPPORTED,
        VlanStatus.ACTIVE_UNSUPPORTED,
    ]

    payload = json.loads(JsonReportRenderer().render(report).content)
    vlan_payload = payload["vlan_observation"]
    assert set(vlan_payload) == {
        "normalized_model",
        "platform",
        "schema_version",
        "vendor",
        "vlans",
    }
    assert len(vlan_payload["vlans"][0]["ports"]) == 54
    assert vlan_payload["vlans"][1]["ports"] == []
    assert [item["status"] for item in vlan_payload["vlans"][13:]] == ["act/unsup"] * 4


def test_vlan_ports_none_remains_distinct_from_empty_tuple() -> None:
    observation = VlanObservation(
        platform=PlatformFamily.IOS_XE,
        vlans=(
            VlanRecord(
                ordinal=1,
                vlan_id=200,
                name="UNKNOWN-ASSOCIATION",
                status=VlanStatus.ACTIVE,
                ports=None,
            ),
            VlanRecord(
                ordinal=2,
                vlan_id=201,
                name="NO-PORTS-LISTED",
                status=VlanStatus.ACTIVE,
                ports=(),
            ),
        ),
    )
    report = AssessmentReportBuilder().build(
        run=_run(),
        result=_empty_device_result(),
        device_info=_device_info(),
        vlan_observation=observation,
        generated_at=GENERATED_AT,
    )

    assert report.vlan_observation is not None
    assert report.vlan_observation.vlans[0].ports is None
    assert report.vlan_observation.vlans[1].ports == ()
    payload = json.loads(JsonReportRenderer().render(report).content)
    assert payload["vlan_observation"]["vlans"][0]["ports"] is None
    assert payload["vlan_observation"]["vlans"][1]["ports"] == []


def test_vlan_outcomes_findings_and_source_trace_are_preserved() -> None:
    raw, parsed = _parse_real_fixture()
    report = AssessmentReportBuilder().build(
        run=_run(),
        result=_evaluated_device_result(parsed),
        device_info=_device_info(),
        vlan_observation=parsed.data,
        generated_at=GENERATED_AT,
    )

    outcomes = {outcome.rule.rule_id: outcome for outcome in report.outcomes}
    assert set(outcomes) == {"VLAN-001", "VLAN-002", "VLAN-003", "VLAN-004"}
    assert outcomes["VLAN-001"].status is AssessmentStatus.INFO
    assert outcomes["VLAN-002"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-003"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-004"].status is AssessmentStatus.INFO
    assert {finding.rule.rule_id for finding in report.findings} == {"VLAN-001", "VLAN-004"}

    vlan004 = outcomes["VLAN-004"]
    assert {evidence.field_path for evidence in vlan004.evidence} == {
        "vlans[13].vlan_id",
        "vlans[13].status",
        "vlans[14].vlan_id",
        "vlans[14].status",
        "vlans[15].vlan_id",
        "vlans[15].status",
        "vlans[16].vlan_id",
        "vlans[16].status",
    }
    status_evidence = next(
        evidence for evidence in vlan004.evidence if evidence.field_path == "vlans[13].status"
    )
    assert status_evidence.observed_value == "act/unsup"
    assert len(status_evidence.sources) == 1
    source = status_evidence.sources[0]
    assert source.assessment_run_id == RUN_ID
    assert source.command_execution_id == parsed.trace.command_execution_id
    assert source.raw_output_id == raw.id
    assert source.raw_sha256 == FIXTURE_SHA256
    assert source.parser_id == ParserId.IOS_SHOW_VLAN_BRIEF_V1.value
    assert source.parser_version == "0.1.0"
    assert source.extractor is not None
    assert source.line_start == 38
    assert source.line_end == 38

    payload = json.loads(JsonReportRenderer().render(report).content)
    payload_vlan004 = next(
        item for item in payload["outcomes"] if item["rule"]["rule_id"] == "VLAN-004"
    )
    payload_source = next(
        item
        for item in payload_vlan004["evidence"]
        if item["field_path"] == "vlans[13].status"
    )["sources"][0]
    assert payload_source["command_execution_id"] == str(parsed.trace.command_execution_id)
    assert payload_source["raw_output_id"] == str(raw.id)
    assert payload_source["raw_sha256"] == FIXTURE_SHA256
    assert payload_source["parser_id"] == ParserId.IOS_SHOW_VLAN_BRIEF_V1.value
    assert payload_source["parser_version"] == "0.1.0"
    assert payload_source["line_start"] == 38
    assert payload_source["line_end"] == 38


def test_vlan_observation_coexists_with_existing_report_domains() -> None:
    _raw, parsed = _parse_real_fixture()
    report = AssessmentReportBuilder().build(
        run=_run(),
        result=_evaluated_device_result(parsed),
        device_info=_device_info(),
        hardware_inventory=_hardware_inventory(),
        interface_observation=_interface_observation(),
        vlan_observation=parsed.data,
        generated_at=GENERATED_AT,
    )

    assert report.device_info.hostname == "SW-CORE-01"
    assert report.hardware_inventory is not None
    assert report.hardware_inventory.records[0].id == "hw:0001"
    assert report.interface_observation is not None
    assert report.interface_observation.interfaces[0].interface == "GigabitEthernet1/0/1"
    assert report.vlan_observation is not None
    assert report.vlan_observation.vlans[0].vlan_id == 1

    payload = json.loads(JsonReportRenderer().render(report).content)
    assert payload["device_info"]["hostname"] == "SW-CORE-01"
    assert payload["hardware_inventory"]["records"][0]["id"] == "hw:0001"
    assert payload["interface_observation"]["interfaces"][0]["vlan"] == "20"
    assert payload["vlan_observation"]["vlans"][0]["vlan_id"] == 1


def test_reporting_source_has_no_collector_parser_or_genie_dependency() -> None:
    reporting_root = Path(__file__).parents[3] / "src" / "cisco_assessment" / "reporting"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(reporting_root.rglob("*.py"))
    ).lower()

    assert "cisco_assessment.collector" not in source
    assert "cisco_assessment.parsers" not in source
    assert "genie" not in source
    assert "pyats" not in source
