import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

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
from cisco_assessment.models import AssessmentRun, AssessmentRunStatus, DeviceInfo, DeviceSnapshot
from cisco_assessment.models.enums import PlatformFamily
from cisco_assessment.reporting import (
    AssessmentReportBuilder,
    JsonReportRenderer,
    ReportBuildError,
)

RUN_ID = UUID("11111111-1111-1111-1111-111111111111")
DEVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
COMMAND_EXECUTION_ID = UUID("33333333-3333-3333-3333-333333333333")
RAW_OUTPUT_ID = UUID("44444444-4444-4444-4444-444444444444")
FINDING_ID = UUID("55555555-5555-5555-5555-555555555555")
GENERATED_AT = datetime(2026, 8, 22, 0, 50, tzinfo=UTC)


def _inputs() -> tuple[AssessmentRun, AssessmentResult, DeviceInfo]:
    source = SourceTrace(
        assessment_run_id=RUN_ID,
        command_execution_id=COMMAND_EXECUTION_ID,
        raw_output_id=RAW_OUTPUT_ID,
        raw_sha256="a" * 64,
        parser_id="ios_show_version_v1",
        parser_version="0.1.0",
        platform=PlatformFamily.IOS_XE,
        extractor="version_header",
        line_start=1,
        line_end=4,
    )
    evidence = FindingEvidence(
        normalized_model="DeviceInfo",
        field_path="software_version",
        observed_value="17.09.04a",
        sources=(source,),
    )
    outcomes = (
        RuleOutcome(
            rule_id="SYS-001",
            rule_version="0.1.0",
            title="Hostname",
            category="system",
            normalized_model="DeviceInfo",
            status=AssessmentStatus.PASS,
            severity=FindingSeverity.LOW,
            message="Hostname is acceptable.",
        ),
        RuleOutcome(
            rule_id="SYS-003",
            rule_version="0.1.0",
            title="Software version observed",
            category="system",
            normalized_model="DeviceInfo",
            status=AssessmentStatus.INFO,
            severity=FindingSeverity.INFO,
            message="Software version was recorded.",
            evidence=(evidence,),
            recommendation="Review the observed version against lifecycle policy.",
        ),
    )
    finding = Finding(
        finding_id=FINDING_ID,
        rule_id="SYS-003",
        rule_version="0.1.0",
        title="Software version observed",
        description="Records the normalized software release.",
        category="system",
        normalized_model="DeviceInfo",
        status=AssessmentStatus.INFO,
        severity=FindingSeverity.INFO,
        evidence=(evidence,),
        recommendation="Review the observed version against lifecycle policy.",
    )
    result = AssessmentResult(
        assessment_run_id=RUN_ID,
        device_id=DEVICE_ID,
        platform=PlatformFamily.IOS_XE,
        normalized_model="DeviceInfo",
        outcomes=outcomes,
        findings=(finding,),
    )
    run = AssessmentRun(
        id=RUN_ID,
        device_id=DEVICE_ID,
        framework_version="0.1.0",
        started_at=datetime(2026, 8, 22, 0, 45, tzinfo=UTC),
        finished_at=datetime(2026, 8, 22, 0, 46, tzinfo=UTC),
        status=AssessmentRunStatus.COMPLETED,
        target_snapshot=DeviceSnapshot(
            management_address="192.0.2.10",
            hostname="SW-CORE-01",
            platform_family=PlatformFamily.IOS_XE,
        ),
        command_catalog_version="0.1.0",
        ruleset_version="0.1.0",
    )
    device_info = DeviceInfo(
        platform=PlatformFamily.IOS_XE,
        hostname="SW-CORE-01",
        software_version="17.09.04a",
        model="C9300-48P",
        serial_number="FCW00000001",
        system_image="flash:packages.conf",
        uptime_text="2 weeks, 1 day",
        boot_mode="INSTALL",
    )
    return run, result, device_info


def test_builder_preserves_run_device_rule_normalized_and_raw_traceability() -> None:
    run, result, device_info = _inputs()

    report = AssessmentReportBuilder().build(
        run=run,
        result=result,
        device_info=device_info,
        generated_at=GENERATED_AT,
    )

    assert report.schema_version == "0.1"
    assert report.run.assessment_run_id == RUN_ID
    assert report.run.device_id == DEVICE_ID
    assert report.run.ruleset_version == "0.1.0"
    assert report.target.management_address == "192.0.2.10"
    assert report.device_info.normalized_model == "DeviceInfo"
    assert report.device_info.software_version == "17.09.04a"

    assert report.summary.rules_evaluated == 2
    assert report.summary.findings_total == 1
    assert report.summary.outcome_status_counts[AssessmentStatus.PASS] == 1
    assert report.summary.outcome_status_counts[AssessmentStatus.INFO] == 1
    assert report.summary.outcome_status_counts[AssessmentStatus.FAIL] == 0
    assert report.summary.finding_severity_counts[FindingSeverity.INFO] == 1
    assert report.summary.finding_severity_counts[FindingSeverity.HIGH] == 0

    reported_finding = report.findings[0]
    assert reported_finding.device_id == DEVICE_ID
    assert reported_finding.rule.rule_id == "SYS-003"
    assert reported_finding.rule.rule_version == "0.1.0"
    assert reported_finding.evidence[0].normalized_model == "DeviceInfo"
    assert reported_finding.evidence[0].field_path == "software_version"

    source = reported_finding.evidence[0].sources[0]
    assert source.command_execution_id == COMMAND_EXECUTION_ID
    assert source.raw_output_id == RAW_OUTPUT_ID
    assert source.raw_sha256 == "a" * 64
    assert source.parser_id == "ios_show_version_v1"
    assert source.line_start == 1
    assert source.line_end == 4


def test_json_renderer_serializes_canonical_report_without_domain_lookups() -> None:
    run, result, device_info = _inputs()
    report = AssessmentReportBuilder().build(
        run=run,
        result=result,
        device_info=device_info,
        generated_at=GENERATED_AT,
    )

    rendered = JsonReportRenderer().render(report)
    payload = json.loads(rendered.content.decode("utf-8"))

    assert rendered.media_type == "application/json"
    assert rendered.extension == ".json"
    assert payload["schema_version"] == "0.1"
    assert payload["run"]["assessment_run_id"] == str(RUN_ID)
    assert payload["summary"]["outcome_status_counts"]["PASS"] == 1
    assert payload["summary"]["finding_severity_counts"]["INFO"] == 1
    assert payload["findings"][0]["rule"]["rule_id"] == "SYS-003"
    assert payload["findings"][0]["evidence"][0]["sources"][0]["raw_output_id"] == str(
        RAW_OUTPUT_ID
    )
    assert payload["findings"][0]["evidence"][0]["sources"][0][
        "command_execution_id"
    ] == str(COMMAND_EXECUTION_ID)


def test_builder_rejects_cross_run_result() -> None:
    run, result, device_info = _inputs()
    mismatched_result = result.model_copy(update={"assessment_run_id": uuid4()})

    with pytest.raises(ReportBuildError, match="assessment_run_id"):
        AssessmentReportBuilder().build(
            run=run,
            result=mismatched_result,
            device_info=device_info,
            generated_at=GENERATED_AT,
        )


def test_builder_rejects_source_trace_from_another_run() -> None:
    run, result, device_info = _inputs()
    bad_source = result.findings[0].evidence[0].sources[0].model_copy(
        update={"assessment_run_id": uuid4()}
    )
    bad_evidence = result.findings[0].evidence[0].model_copy(update={"sources": (bad_source,)})
    bad_finding = result.findings[0].model_copy(update={"evidence": (bad_evidence,)})
    mismatched_result = result.model_copy(update={"findings": (bad_finding,)})

    with pytest.raises(ReportBuildError, match="SourceTrace"):
        AssessmentReportBuilder().build(
            run=run,
            result=mismatched_result,
            device_info=device_info,
            generated_at=GENERATED_AT,
        )
