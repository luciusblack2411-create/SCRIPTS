"""Build canonical reports from assessment-domain results without re-evaluating rules."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from cisco_assessment.assessment.enums import AssessmentStatus, FindingSeverity
from cisco_assessment.assessment.evidence import FindingEvidence, SourceTrace
from cisco_assessment.assessment.models import AssessmentResult, Finding, RuleOutcome
from cisco_assessment.models import (
    AssessmentRun,
    DeviceInfo,
    HardwareInventory,
    HardwareInventoryRecord,
    InterfaceObservation,
    InterfaceStatusRecord,
    VlanObservation,
    VlanRecord,
)
from cisco_assessment.models.base import utc_now

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
    ReportMetadata,
    RuleOutcomeReport,
    RuleReferenceReport,
    SourceTraceReport,
    TargetSnapshotReport,
    VlanObservationReport,
    VlanRecordReport,
)


class AssessmentReportBuilder:
    """Map assessment-domain artifacts into the renderer-agnostic report contract."""

    def build(
        self,
        *,
        run: AssessmentRun,
        result: AssessmentResult,
        device_info: DeviceInfo,
        hardware_inventory: HardwareInventory | None = None,
        interface_observation: InterfaceObservation | None = None,
        vlan_observation: VlanObservation | None = None,
        generated_at: datetime | None = None,
        report_id: UUID | None = None,
    ) -> AssessmentReport:
        self._validate_inputs(
            run=run,
            result=result,
            device_info=device_info,
            hardware_inventory=hardware_inventory,
            interface_observation=interface_observation,
            vlan_observation=vlan_observation,
        )

        status_counts = {status: 0 for status in AssessmentStatus}
        for outcome in result.outcomes:
            status_counts[outcome.status] += 1

        severity_counts = {severity: 0 for severity in FindingSeverity}
        for finding in result.findings:
            severity_counts[finding.severity] += 1

        return AssessmentReport(
            metadata=ReportMetadata(
                report_id=report_id or uuid5(NAMESPACE_URL, f"cisco-assessment-report:{run.id}"),
                generated_at=generated_at or run.finished_at or utc_now(),
                generator_version=run.framework_version,
            ),
            run=AssessmentRunReport(
                assessment_run_id=run.id,
                device_id=run.device_id,
                framework_version=run.framework_version,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
                command_catalog_version=run.command_catalog_version,
                ruleset_version=run.ruleset_version,
            ),
            target=TargetSnapshotReport(
                management_address=run.target_snapshot.management_address,
                hostname=run.target_snapshot.hostname,
                platform_family=run.target_snapshot.platform_family,
            ),
            device_info=DeviceInfoReport(
                schema_version=device_info.schema_version,
                vendor=device_info.vendor,
                platform=device_info.platform,
                hostname=device_info.hostname,
                software_version=device_info.software_version,
                model=device_info.model,
                serial_number=device_info.serial_number,
                system_image=device_info.system_image,
                uptime_text=device_info.uptime_text,
                boot_mode=device_info.boot_mode,
            ),
            hardware_inventory=(
                None
                if hardware_inventory is None
                else HardwareInventoryReport(
                    schema_version=hardware_inventory.schema_version,
                    vendor=hardware_inventory.vendor,
                    platform=hardware_inventory.platform,
                    records=tuple(
                        self._map_hardware_inventory_record(item)
                        for item in hardware_inventory.records
                    ),
                )
            ),
            interface_observation=(
                None
                if interface_observation is None
                else InterfaceObservationReport(
                    schema_version=interface_observation.schema_version,
                    vendor=interface_observation.vendor,
                    platform=interface_observation.platform,
                    interfaces=tuple(
                        self._map_interface_status_record(item)
                        for item in interface_observation.interfaces
                    ),
                )
            ),
            vlan_observation=(
                None
                if vlan_observation is None
                else VlanObservationReport(
                    schema_version=vlan_observation.schema_version,
                    vendor=vlan_observation.vendor,
                    platform=vlan_observation.platform,
                    vlans=tuple(self._map_vlan_record(item) for item in vlan_observation.vlans),
                )
            ),
            summary=AssessmentSummary(
                rules_evaluated=len(result.outcomes),
                findings_total=len(result.findings),
                outcome_status_counts=status_counts,
                finding_severity_counts=severity_counts,
            ),
            outcomes=tuple(self._map_outcome(outcome) for outcome in result.outcomes),
            findings=tuple(
                self._map_finding(finding=finding, device_id=result.device_id)
                for finding in result.findings
            ),
        )

    @staticmethod
    def _validate_inputs(
        *,
        run: AssessmentRun,
        result: AssessmentResult,
        device_info: DeviceInfo,
        hardware_inventory: HardwareInventory | None,
        interface_observation: InterfaceObservation | None,
        vlan_observation: VlanObservation | None,
    ) -> None:
        if result.assessment_run_id != run.id:
            raise ReportBuildError("AssessmentResult assessment_run_id does not match AssessmentRun")
        if result.device_id != run.device_id:
            raise ReportBuildError("AssessmentResult device_id does not match AssessmentRun")
        if result.platform != device_info.platform:
            raise ReportBuildError("AssessmentResult platform does not match DeviceInfo platform")
        if result.normalized_model != type(device_info).__name__:
            raise ReportBuildError("AssessmentResult normalized_model does not match DeviceInfo")
        if hardware_inventory is not None and hardware_inventory.platform != device_info.platform:
            raise ReportBuildError("HardwareInventory platform does not match DeviceInfo platform")
        if interface_observation is not None and interface_observation.platform != device_info.platform:
            raise ReportBuildError("InterfaceObservation platform does not match DeviceInfo platform")
        if vlan_observation is not None and vlan_observation.platform != device_info.platform:
            raise ReportBuildError("VlanObservation platform does not match DeviceInfo platform")

        for evidence in AssessmentReportBuilder._all_evidence(result):
            for source in evidence.sources:
                if source.assessment_run_id != run.id:
                    raise ReportBuildError(
                        "Evidence SourceTrace assessment_run_id does not match AssessmentRun"
                    )

    @staticmethod
    def _all_evidence(result: AssessmentResult) -> tuple[FindingEvidence, ...]:
        return tuple(
            evidence for outcome in result.outcomes for evidence in outcome.evidence
        ) + tuple(evidence for finding in result.findings for evidence in finding.evidence)

    @staticmethod
    def _map_hardware_inventory_record(
        record: HardwareInventoryRecord,
    ) -> HardwareInventoryRecordReport:
        return HardwareInventoryRecordReport(
            ordinal=record.ordinal,
            id=record.id,
            name=record.name,
            description=record.description,
            pid=record.pid,
            vid=record.vid,
            serial_number=record.serial_number,
            component_type=record.component_type,
            parent_id=record.parent_id,
        )

    @staticmethod
    def _map_interface_status_record(
        record: InterfaceStatusRecord,
    ) -> InterfaceStatusRecordReport:
        return InterfaceStatusRecordReport(
            ordinal=record.ordinal,
            interface=record.interface,
            description=record.description,
            status=record.status,
            vlan=record.vlan,
            duplex=record.duplex,
            speed=record.speed,
            media_type=record.media_type,
        )

    @staticmethod
    def _map_vlan_record(record: VlanRecord) -> VlanRecordReport:
        return VlanRecordReport(
            ordinal=record.ordinal,
            vlan_id=record.vlan_id,
            name=record.name,
            status=record.status,
            ports=record.ports,
        )

    @staticmethod
    def _map_source(source: SourceTrace) -> SourceTraceReport:
        return SourceTraceReport(
            assessment_run_id=source.assessment_run_id,
            command_execution_id=source.command_execution_id,
            raw_output_id=source.raw_output_id,
            raw_sha256=source.raw_sha256,
            parser_id=source.parser_id,
            parser_version=source.parser_version,
            platform=source.platform,
            extractor=source.extractor,
            line_start=source.line_start,
            line_end=source.line_end,
        )

    @classmethod
    def _map_evidence(cls, evidence: FindingEvidence) -> EvidenceReport:
        return EvidenceReport(
            normalized_model=evidence.normalized_model,
            field_path=evidence.field_path,
            observed_value=evidence.observed_value,
            sources=tuple(cls._map_source(source) for source in evidence.sources),
        )

    @classmethod
    def _map_outcome(cls, outcome: RuleOutcome) -> RuleOutcomeReport:
        return RuleOutcomeReport(
            rule=RuleReferenceReport(rule_id=outcome.rule_id, rule_version=outcome.rule_version),
            title=outcome.title,
            category=outcome.category,
            normalized_model=outcome.normalized_model,
            status=outcome.status,
            severity=outcome.severity,
            message=outcome.message,
            evidence=tuple(cls._map_evidence(evidence) for evidence in outcome.evidence),
            recommendation=outcome.recommendation,
            reason_code=outcome.reason_code,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
        )

    @classmethod
    def _map_finding(cls, *, finding: Finding, device_id: UUID) -> FindingReport:
        return FindingReport(
            finding_id=finding.finding_id,
            device_id=device_id,
            rule=RuleReferenceReport(rule_id=finding.rule_id, rule_version=finding.rule_version),
            title=finding.title,
            description=finding.description,
            category=finding.category,
            normalized_model=finding.normalized_model,
            status=finding.status,
            severity=finding.severity,
            evidence=tuple(cls._map_evidence(evidence) for evidence in finding.evidence),
            recommendation=finding.recommendation,
            error_type=finding.error_type,
            error_message=finding.error_message,
        )
