"""Canonical, renderer-agnostic reporting contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, NonNegativeInt, field_validator

from cisco_assessment.assessment.enums import AssessmentStatus, FindingSeverity
from cisco_assessment.models.base import normalize_utc
from cisco_assessment.models.enums import AssessmentRunStatus, PlatformFamily

REPORT_SCHEMA_VERSION = "0.1"


class ReportModel(BaseModel):
    """Strict immutable base model for canonical report data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportMetadata(ReportModel):
    """Metadata about one generated report artifact."""

    report_id: UUID
    generated_at: datetime
    generator_name: str = Field(default="cisco-switch-assessment", min_length=1, max_length=128)
    generator_version: str = Field(min_length=1, max_length=64)

    @field_validator("generated_at")
    @classmethod
    def generated_at_is_utc(cls, value: datetime) -> datetime:
        return normalize_utc(value)


class AssessmentRunReport(ReportModel):
    """AssessmentRun metadata copied into the canonical report."""

    assessment_run_id: UUID
    device_id: UUID
    framework_version: str
    started_at: datetime
    finished_at: datetime | None
    status: AssessmentRunStatus
    command_catalog_version: str | None = None
    ruleset_version: str | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return normalize_utc(value)


class TargetSnapshotReport(ReportModel):
    """Assessment-time target identity, independent from normalized observations."""

    management_address: str
    hostname: str | None
    platform_family: PlatformFamily


class DeviceInfoReport(ReportModel):
    """Canonical snapshot of the normalized DeviceInfo evaluated by the engine."""

    normalized_model: Literal["DeviceInfo"] = "DeviceInfo"
    schema_version: str
    vendor: str
    platform: PlatformFamily
    hostname: str | None
    software_version: str
    model: str | None
    serial_number: str | None
    system_image: str | None
    uptime_text: str | None
    boot_mode: str | None


class RuleReferenceReport(ReportModel):
    """Stable reference to the rule responsible for an outcome or finding."""

    rule_id: str
    rule_version: str


class SourceTraceReport(ReportModel):
    """Reference chain from normalized evidence back to execution and immutable RAW."""

    assessment_run_id: UUID
    command_execution_id: UUID
    raw_output_id: UUID
    raw_sha256: str
    parser_id: str
    parser_version: str
    platform: PlatformFamily
    extractor: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class EvidenceReport(ReportModel):
    """One normalized field observation and the RAW sources that produced it."""

    normalized_model: str
    field_path: str
    observed_value: JsonValue = None
    sources: tuple[SourceTraceReport, ...] = ()


class RuleOutcomeReport(ReportModel):
    """Complete rule outcome, including PASS and NOT_APPLICABLE results."""

    rule: RuleReferenceReport
    title: str
    category: str
    normalized_model: str
    status: AssessmentStatus
    severity: FindingSeverity
    message: str
    evidence: tuple[EvidenceReport, ...] = ()
    recommendation: str | None = None
    reason_code: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class FindingReport(ReportModel):
    """Reportable finding with stable rule and evidence traceability."""

    finding_id: UUID
    device_id: UUID
    rule: RuleReferenceReport
    title: str
    description: str
    category: str
    normalized_model: str
    status: AssessmentStatus
    severity: FindingSeverity
    evidence: tuple[EvidenceReport, ...] = ()
    recommendation: str | None = None
    error_type: str | None = None
    error_message: str | None = None


class AssessmentSummary(ReportModel):
    """Pure aggregations over engine outcomes and reportable findings."""

    rules_evaluated: NonNegativeInt
    findings_total: NonNegativeInt
    outcome_status_counts: dict[AssessmentStatus, NonNegativeInt]
    finding_severity_counts: dict[FindingSeverity, NonNegativeInt]


class AssessmentReport(ReportModel):
    """Canonical report consumed by all current and future renderers."""

    schema_version: Literal["0.1"] = REPORT_SCHEMA_VERSION
    metadata: ReportMetadata
    run: AssessmentRunReport
    target: TargetSnapshotReport
    device_info: DeviceInfoReport
    summary: AssessmentSummary
    outcomes: tuple[RuleOutcomeReport, ...]
    findings: tuple[FindingReport, ...]


class RenderedReport(ReportModel):
    """Format-specific bytes returned by a renderer."""

    content: bytes
    media_type: str = Field(min_length=1, max_length=128)
    extension: str = Field(min_length=2, max_length=32, pattern=r"^\.[A-Za-z0-9]+$")
