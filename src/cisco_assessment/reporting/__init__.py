"""Canonical reports and output renderers."""

from .builder import AssessmentReportBuilder
from .errors import ReportBuildError
from .models import (
    AssessmentReport,
    AssessmentRunReport,
    AssessmentSummary,
    DeviceInfoReport,
    EvidenceReport,
    FindingReport,
    HardwareInventoryRecordReport,
    HardwareInventoryReport,
    InterfaceObservationReport,
    InterfaceStatusRecordReport,
    RenderedReport,
    ReportMetadata,
    RuleOutcomeReport,
    RuleReferenceReport,
    SourceTraceReport,
    TargetSnapshotReport,
)
from .renderers import JsonReportRenderer, ReportRenderer

__all__ = [
    "AssessmentReport",
    "AssessmentReportBuilder",
    "AssessmentRunReport",
    "AssessmentSummary",
    "DeviceInfoReport",
    "EvidenceReport",
    "FindingReport",
    "HardwareInventoryRecordReport",
    "HardwareInventoryReport",
    "InterfaceObservationReport",
    "InterfaceStatusRecordReport",
    "JsonReportRenderer",
    "RenderedReport",
    "ReportBuildError",
    "ReportMetadata",
    "ReportRenderer",
    "RuleOutcomeReport",
    "RuleReferenceReport",
    "SourceTraceReport",
    "TargetSnapshotReport",
]
