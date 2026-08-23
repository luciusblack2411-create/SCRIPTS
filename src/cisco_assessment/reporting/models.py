"""Canonical, renderer-agnostic reporting contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    PositiveInt,
    field_validator,
)

from cisco_assessment.assessment.enums import AssessmentStatus, FindingSeverity
from cisco_assessment.models.base import normalize_utc
from cisco_assessment.models.enums import AssessmentRunStatus, PlatformFamily
from cisco_assessment.models.normalized import HardwareComponentType

REPORT_SCHEMA_VERSION: Literal["0.1"] = "0.1"


class ReportModel(BaseModel):
    """Strict immutable base model for canonical report data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportMetadata(ReportModel):
    report_id: UUID
    generated_at: datetime
    generator_name: str = Field(default="cisco-switch-assessment", min_length=1, max_length=128)
    generator_version: str = Field(min_length=1, max_length=64)

    @field_validator("generated_at")
    @classmethod
    def generated_at_is_utc(cls, value: datetime) -> datetime:
        return normalize_utc(value)


class AssessmentRunReport(ReportModel):
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
    management_address: str
    hostname: str | None
    platform_family: PlatformFamily


class DeviceInfoReport(ReportModel):
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


class HardwareInventoryRecordReport(ReportModel):
    """Canonical report representation of one HardwareInventory v0.2 record."""

    ordinal: PositiveInt
    id: str = Field(pattern=r"^hw:\d{4,}$")
    name: str
    description: str | None
    pid: str | None
    vid: str | None
    serial_number: str | None
    component_type: HardwareComponentType
    parent_id: str | None = Field(default=None, pattern=r"^hw:\d{4,}$")


class HardwareInventoryReport(ReportModel):
    """Canonical HardwareInventory v0.2 report view in physical RAW order."""

    normalized_model: Literal["HardwareInventory"] = "HardwareInventory"
    schema_version: str
    vendor: str
    platform: PlatformFamily
    records: tuple[HardwareInventoryRecordReport, ...]


class InterfaceStatusRecordReport(ReportModel):
    """Canonical report representation of one InterfaceObservation v0.1 record."""

    ordinal: PositiveInt
    interface: str
    description: str | None
    status: str
    vlan: str
    duplex: str
    speed: str
    media_type: str | None


class InterfaceObservationReport(ReportModel):
    """Canonical InterfaceObservation v0.1 report view in observation/RAW order."""

    normalized_model: Literal["InterfaceObservation"] = "InterfaceObservation"
    schema_version: str
    vendor: str
    platform: PlatformFamily
    interfaces: tuple[InterfaceStatusRecordReport, ...]


class RuleReferenceReport(ReportModel):
    rule_id: str
    rule_version: str


class SourceTraceReport(ReportModel):
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
    normalized_model: str
    field_path: str
    observed_value: JsonValue = None
    sources: tuple[SourceTraceReport, ...] = ()


class RuleOutcomeReport(ReportModel):
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
    rules_evaluated: NonNegativeInt
    findings_total: NonNegativeInt
    outcome_status_counts: dict[AssessmentStatus, NonNegativeInt]
    finding_severity_counts: dict[FindingSeverity, NonNegativeInt]


class AssessmentReport(ReportModel):
    schema_version: Literal["0.1"] = REPORT_SCHEMA_VERSION
    metadata: ReportMetadata
    run: AssessmentRunReport
    target: TargetSnapshotReport
    device_info: DeviceInfoReport
    hardware_inventory: HardwareInventoryReport | None = None
    interface_observation: InterfaceObservationReport | None = None
    summary: AssessmentSummary
    outcomes: tuple[RuleOutcomeReport, ...]
    findings: tuple[FindingReport, ...]


class RenderedReport(ReportModel):
    content: bytes
    media_type: str = Field(min_length=1, max_length=128)
    extension: str = Field(min_length=2, max_length=32, pattern=r"^\.[A-Za-z0-9]+$")
