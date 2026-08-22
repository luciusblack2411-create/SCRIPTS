"""End-to-end orchestration for the first single-device assessment slice."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import cast

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    NormalizedFieldSource,
    SourceTrace,
)
from cisco_assessment.catalog import CommandCatalog, CommandId, NormalizedModelId
from cisco_assessment.collector import DeviceCollectionResult, DeviceCollector
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import (
    AssessmentRun,
    AssessmentRunStatus,
    CommandExecutionStatus,
    Device,
    DeviceInfo,
    PlatformFamily,
)
from cisco_assessment.models.base import utc_now
from cisco_assessment.parsers import BaseParser, ParseResult, ParseStatus, ParserRegistry
from cisco_assessment.reporting import AssessmentReportBuilder, ReportRenderer

from .errors import AssessmentRunnerError, RunnerFailure, RunnerStage
from .models import AssessmentRunnerResult

_SUPPORTED_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


class AssessmentRunner:
    """Connect existing collection, parsing, assessment, and reporting components."""

    def __init__(
        self,
        *,
        framework_version: str,
        collector: DeviceCollector,
        parser_registry: ParserRegistry,
        command_catalog: CommandCatalog,
        assessment_engine: AssessmentEngine[DeviceInfo],
        report_builder: AssessmentReportBuilder,
        report_renderer: ReportRenderer,
        report_root: Path,
        ruleset_version: str,
    ) -> None:
        if not framework_version.strip():
            raise ValueError("framework_version must not be blank")
        if not ruleset_version.strip():
            raise ValueError("ruleset_version must not be blank")
        self._framework_version = framework_version.strip()
        self._collector = collector
        self._parser_registry = parser_registry
        self._command_catalog = command_catalog
        self._assessment_engine = assessment_engine
        self._report_builder = report_builder
        self._report_renderer = report_renderer
        self._report_root = Path(report_root)
        self._ruleset_version = ruleset_version.strip()

    def run(
        self,
        *,
        device: Device,
        credentials: SSHCredentials,
    ) -> AssessmentRunnerResult:
        """Run the v0.1 ``show version`` assessment for exactly one device."""
        run = AssessmentRun(
            device_id=device.id,
            framework_version=self._framework_version,
            target_snapshot=device.snapshot(),
            command_catalog_version=self._command_catalog.catalog_version,
            ruleset_version=self._ruleset_version,
        )
        run.status = AssessmentRunStatus.RUNNING

        if device.platform_family not in _SUPPORTED_PLATFORMS:
            self._fail(
                run=run,
                stage=RunnerStage.VALIDATION,
                error_type="unsupported_platform",
                message=(
                    "Runner v0.1 supports only Cisco IOS and IOS-XE for the show version slice."
                ),
            )

        variant = self._command_catalog.resolve(CommandId.SYSTEM_VERSION, device.platform_family)
        if variant is None:
            self._fail(
                run=run,
                stage=RunnerStage.VALIDATION,
                error_type="command_variant_missing",
                message=(
                    "The command catalog does not define system.version for "
                    f"{device.platform_family.value}."
                ),
            )

        try:
            collection = self._collector.collect(
                assessment_run_id=run.id,
                device=device,
                credentials=credentials,
                catalog=self._command_catalog,
                command_ids=(CommandId.SYSTEM_VERSION,),
            )
        except Exception as exc:  # noqa: BLE001 - runner must close the run deterministically.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.COLLECTION,
                exc=exc,
            )

        collected = next(
            (
                item
                for item in collection.commands
                if item.execution.command_key == CommandId.SYSTEM_VERSION.value
            ),
            None,
        )
        if collected is None:
            self._fail(
                run=run,
                stage=RunnerStage.COLLECTION,
                error_type="command_result_missing",
                message="Collector did not return a result for system.version.",
                collection=collection,
            )

        execution = collected.execution
        if execution.status != CommandExecutionStatus.SUCCESS:
            self._fail(
                run=run,
                stage=RunnerStage.COLLECTION,
                error_type=execution.error_type or execution.status.value,
                message=(
                    execution.error_message
                    or f"show version collection ended with status {execution.status.value}."
                ),
                command_execution_id=execution.id,
                collection=collection,
            )
        if collected.raw_output is None:
            self._fail(
                run=run,
                stage=RunnerStage.COLLECTION,
                error_type="raw_output_missing",
                message="Successful show version execution did not preserve RAW output.",
                command_execution_id=execution.id,
                collection=collection,
            )

        try:
            parser = cast(
                BaseParser[DeviceInfo],
                self._parser_registry.resolve(variant.parser_id, device.platform_family),
            )
            parse_result = parser.parse(
                raw_output=collected.raw_output,
                command_execution=execution,
                platform=device.platform_family,
            )
        except Exception as exc:  # noqa: BLE001 - parser failures must close the run.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.PARSING,
                exc=exc,
                command_execution_id=execution.id,
                collection=collection,
            )

        if not isinstance(parse_result.data, DeviceInfo):
            self._fail(
                run=run,
                stage=RunnerStage.PARSING,
                error_type="normalized_model_mismatch",
                message="show version parser did not produce DeviceInfo.",
                command_execution_id=execution.id,
                collection=collection,
            )
        if parse_result.trace.normalized_model != NormalizedModelId.DEVICE_INFO:
            self._fail(
                run=run,
                stage=RunnerStage.PARSING,
                error_type="parse_trace_model_mismatch",
                message="show version parse trace does not identify DeviceInfo.",
                command_execution_id=execution.id,
                collection=collection,
            )
        if parse_result.data.platform != parse_result.trace.platform:
            self._fail(
                run=run,
                stage=RunnerStage.PARSING,
                error_type="platform_trace_mismatch",
                message=(
                    "Normalized DeviceInfo platform differs from the platform recorded in parser "
                    "traceability."
                ),
                command_execution_id=execution.id,
                collection=collection,
            )

        try:
            context = self._build_context(
                run=run,
                device=device,
                parse_result=parse_result,
            )
            assessment_result = self._assessment_engine.evaluate(parse_result.data, context)
        except Exception as exc:  # noqa: BLE001 - assessment failures must close the run.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.ASSESSMENT,
                exc=exc,
                command_execution_id=execution.id,
                collection=collection,
            )

        partial = parse_result.status == ParseStatus.PARTIAL or any(
            outcome.status == AssessmentStatus.ERROR for outcome in assessment_result.outcomes
        )
        run.status = AssessmentRunStatus.PARTIAL if partial else AssessmentRunStatus.COMPLETED
        run.finished_at = utc_now()

        try:
            report = self._report_builder.build(
                run=run,
                result=assessment_result,
                device_info=parse_result.data,
            )
            rendered_report = self._report_renderer.render(report)
        except Exception as exc:  # noqa: BLE001 - reporting failures must close the run.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.REPORTING,
                exc=exc,
                command_execution_id=execution.id,
                collection=collection,
            )

        try:
            report_path = self._persist_report(
                run=run,
                content=rendered_report.content,
                extension=rendered_report.extension,
            )
        except Exception as exc:  # noqa: BLE001 - persistence failures must close the run.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.PERSISTENCE,
                exc=exc,
                command_execution_id=execution.id,
                collection=collection,
            )

        return AssessmentRunnerResult(
            run=run,
            collection=collection,
            parse_result=parse_result,
            assessment_result=assessment_result,
            report=report,
            rendered_report=rendered_report,
            report_path=report_path,
        )

    @staticmethod
    def _build_context(
        *,
        run: AssessmentRun,
        device: Device,
        parse_result: ParseResult[DeviceInfo],
    ) -> AssessmentContext:
        trace = parse_result.trace
        source_evidence = tuple(
            NormalizedFieldSource(
                normalized_model=trace.normalized_model.value,
                field_path=item.field,
                source=SourceTrace(
                    assessment_run_id=trace.assessment_run_id,
                    command_execution_id=trace.command_execution_id,
                    raw_output_id=trace.raw_output_id,
                    raw_sha256=trace.raw_sha256,
                    parser_id=trace.parser_id.value,
                    parser_version=trace.parser_version,
                    platform=trace.platform,
                    extractor=item.extractor,
                    line_start=item.line_start,
                    line_end=item.line_end,
                ),
            )
            for item in parse_result.evidence
        )
        return AssessmentContext(
            assessment_run_id=run.id,
            device_id=device.id,
            platform=parse_result.data.platform,
            source_evidence=source_evidence,
        )

    def _persist_report(
        self,
        *,
        run: AssessmentRun,
        content: bytes,
        extension: str,
    ) -> Path:
        directory = self._report_root / str(run.id) / "report"
        filename = f"assessment{extension}"
        final_path = directory / filename
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{filename}.", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, final_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return final_path

    @staticmethod
    def _fail_from_exception(
        *,
        run: AssessmentRun,
        stage: RunnerStage,
        exc: Exception,
        command_execution_id: object | None = None,
        collection: DeviceCollectionResult | None = None,
    ) -> None:
        from uuid import UUID

        execution_id = command_execution_id if isinstance(command_execution_id, UUID) else None
        AssessmentRunner._fail(
            run=run,
            stage=stage,
            error_type=type(exc).__name__,
            message=str(exc).strip() or "Unexpected orchestration error.",
            command_execution_id=execution_id,
            collection=collection,
        )

    @staticmethod
    def _fail(
        *,
        run: AssessmentRun,
        stage: RunnerStage,
        error_type: str,
        message: str,
        command_execution_id: object | None = None,
        collection: DeviceCollectionResult | None = None,
    ) -> None:
        from uuid import UUID

        execution_id = command_execution_id if isinstance(command_execution_id, UUID) else None
        failure = RunnerFailure(
            stage=stage,
            error_type=error_type,
            message=message,
            command_execution_id=execution_id,
        )
        run.status = AssessmentRunStatus.FAILED
        run.finished_at = utc_now()
        run.error_message = f"{stage.value}:{error_type}:{message}"[:4096]
        raise AssessmentRunnerError(run=run, failure=failure, collection=collection)
