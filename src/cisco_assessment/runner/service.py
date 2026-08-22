"""End-to-end orchestration for typed assessment plans."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import UUID

from cisco_assessment.assessment import (
    AssessmentContext,
    AssessmentEngine,
    AssessmentStatus,
    NormalizedFieldSource,
    SourceTrace,
)
from cisco_assessment.catalog import (
    CommandCatalog,
    CommandDefinition,
    CommandRequirement,
    NormalizedModelId,
)
from cisco_assessment.collector import (
    CommandCollectionResult,
    DeviceCollectionResult,
    DeviceCollector,
)
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
from cisco_assessment.parsers import ParseResult, ParserRegistry, ParseStatus
from cisco_assessment.reporting import AssessmentReportBuilder, ReportRenderer

from .errors import AssessmentRunnerError, RunnerFailure, RunnerStage
from .models import AssessmentCommandResult, AssessmentRunnerResult
from .plan import AssessmentPlan

_SUPPORTED_PLATFORMS = frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE})


class AssessmentRunner:
    """Connect collection, parsing, assessment, and reporting through a plan."""

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
        default_plan: AssessmentPlan,
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
        self._default_plan = default_plan

    def run(
        self,
        *,
        device: Device,
        credentials: SSHCredentials,
        plan: AssessmentPlan | None = None,
    ) -> AssessmentRunnerResult:
        """Run one ordered AssessmentPlan against exactly one IOS/IOS-XE device."""
        selected_plan = plan or self._default_plan
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
                message="Runner v0.2 supports only Cisco IOS and IOS-XE.",
            )

        definitions = self._resolve_plan_definitions(run=run, plan=selected_plan)
        if not any(
            definition.normalized_model == NormalizedModelId.DEVICE_INFO
            for definition in definitions
        ):
            self._fail(
                run=run,
                stage=RunnerStage.VALIDATION,
                error_type="device_info_input_missing",
                message=(
                    "Runner v0.2 requires a plan command that produces DeviceInfo because the "
                    "current Assessment Rules and Reporting slice evaluate DeviceInfo only."
                ),
            )

        try:
            collection = self._collector.collect(
                assessment_run_id=run.id,
                device=device,
                credentials=credentials,
                catalog=self._command_catalog,
                command_ids=selected_plan.command_ids,
            )
        except Exception as exc:  # noqa: BLE001 - runner must close the run deterministically.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.COLLECTION,
                exc=exc,
            )

        collected_by_key = {
            item.execution.command_key: item
            for item in collection.commands
        }
        command_results: list[AssessmentCommandResult] = []
        optional_failure = False
        partial_parse = False
        device_info_parse_result: ParseResult[DeviceInfo] | None = None

        for definition in definitions:
            collected = collected_by_key.get(definition.command_id.value)
            if collected is None:
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.COLLECTION,
                    error_type="command_result_missing",
                    message=(
                        "Collector did not return a result for "
                        f"{definition.command_id.value}."
                    ),
                    collection=collection,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            execution = collected.execution
            if execution.status != CommandExecutionStatus.SUCCESS:
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.COLLECTION,
                    error_type=execution.error_type or execution.status.value,
                    message=(
                        execution.error_message
                        or (
                            f"{definition.command_id.value} collection ended with status "
                            f"{execution.status.value}."
                        )
                    ),
                    command_execution_id=execution.id,
                    collection=collection,
                    collected=collected,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            if collected.raw_output is None:
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.COLLECTION,
                    error_type="raw_output_missing",
                    message=(
                        f"Successful {definition.command_id.value} execution did not preserve RAW "
                        "output."
                    ),
                    command_execution_id=execution.id,
                    collection=collection,
                    collected=collected,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            variant = self._command_catalog.resolve(
                definition.command_id,
                device.platform_family,
            )
            if variant is None:
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.PARSING,
                    error_type="command_variant_missing",
                    message=(
                        f"No {device.platform_family.value} command variant is defined for "
                        f"{definition.command_id.value}."
                    ),
                    command_execution_id=execution.id,
                    collection=collection,
                    collected=collected,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            try:
                parser = self._parser_registry.resolve(
                    variant.parser_id,
                    device.platform_family,
                )
                parse_result = parser.parse(
                    raw_output=collected.raw_output,
                    command_execution=execution,
                    platform=device.platform_family,
                )
            except Exception as exc:  # noqa: BLE001 - optional parser failures may continue.
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.PARSING,
                    error_type=type(exc).__name__,
                    message=str(exc).strip() or "Unexpected parser error.",
                    command_execution_id=execution.id,
                    collection=collection,
                    collected=collected,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            if parse_result.trace.normalized_model != definition.normalized_model:
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.PARSING,
                    error_type="parse_trace_model_mismatch",
                    message=(
                        f"Parser {parse_result.trace.parser_id.value} produced trace model "
                        f"{parse_result.trace.normalized_model.value}; catalog expects "
                        f"{definition.normalized_model.value}."
                    ),
                    command_execution_id=execution.id,
                    collection=collection,
                    collected=collected,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            if parse_result.trace.platform != device.platform_family:
                command_result = self._command_failure(
                    run=run,
                    definition=definition,
                    stage=RunnerStage.PARSING,
                    error_type="platform_trace_mismatch",
                    message=(
                        f"Parser trace platform {parse_result.trace.platform.value} differs from "
                        f"target platform {device.platform_family.value}."
                    ),
                    command_execution_id=execution.id,
                    collection=collection,
                    collected=collected,
                )
                command_results.append(command_result)
                optional_failure = True
                continue

            if definition.normalized_model == NormalizedModelId.DEVICE_INFO:
                if not isinstance(parse_result.data, DeviceInfo):
                    command_result = self._command_failure(
                        run=run,
                        definition=definition,
                        stage=RunnerStage.PARSING,
                        error_type="normalized_model_mismatch",
                        message=(
                            f"{definition.command_id.value} is cataloged as DeviceInfo but its "
                            "parser returned another model type."
                        ),
                        command_execution_id=execution.id,
                        collection=collection,
                        collected=collected,
                    )
                    command_results.append(command_result)
                    optional_failure = True
                    continue
                if parse_result.data.platform != parse_result.trace.platform:
                    command_result = self._command_failure(
                        run=run,
                        definition=definition,
                        stage=RunnerStage.PARSING,
                        error_type="platform_trace_mismatch",
                        message=(
                            "Normalized DeviceInfo platform differs from the platform recorded in "
                            "parser traceability."
                        ),
                        command_execution_id=execution.id,
                        collection=collection,
                        collected=collected,
                    )
                    command_results.append(command_result)
                    optional_failure = True
                    continue
                device_info_parse_result = cast(ParseResult[DeviceInfo], parse_result)

            command_results.append(
                AssessmentCommandResult(
                    command_id=definition.command_id,
                    requirement=definition.requirement,
                    collection=collected,
                    parse_result=parse_result,
                )
            )
            partial_parse = partial_parse or parse_result.status == ParseStatus.PARTIAL

        if device_info_parse_result is None:
            self._fail(
                run=run,
                stage=RunnerStage.ASSESSMENT,
                error_type="device_info_unavailable",
                message=(
                    "No successful DeviceInfo parse is available for the current Assessment Rules "
                    "and Reporting slice."
                ),
                collection=collection,
            )

        try:
            context = self._build_context(
                run=run,
                device=device,
                command_results=tuple(command_results),
            )
            assessment_result = self._assessment_engine.evaluate(
                device_info_parse_result.data,
                context,
            )
        except Exception as exc:  # noqa: BLE001 - assessment failures must close the run.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.ASSESSMENT,
                exc=exc,
                command_execution_id=device_info_parse_result.trace.command_execution_id,
                collection=collection,
            )

        partial = optional_failure or partial_parse or any(
            outcome.status == AssessmentStatus.ERROR for outcome in assessment_result.outcomes
        )
        run.status = AssessmentRunStatus.PARTIAL if partial else AssessmentRunStatus.COMPLETED
        run.finished_at = utc_now()

        try:
            report = self._report_builder.build(
                run=run,
                result=assessment_result,
                device_info=device_info_parse_result.data,
            )
            rendered_report = self._report_renderer.render(report)
        except Exception as exc:  # noqa: BLE001 - reporting failures must close the run.
            self._fail_from_exception(
                run=run,
                stage=RunnerStage.REPORTING,
                exc=exc,
                command_execution_id=device_info_parse_result.trace.command_execution_id,
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
                command_execution_id=device_info_parse_result.trace.command_execution_id,
                collection=collection,
            )

        return AssessmentRunnerResult(
            run=run,
            plan=selected_plan,
            collection=collection,
            command_results=tuple(command_results),
            device_info_parse_result=device_info_parse_result,
            assessment_result=assessment_result,
            report=report,
            rendered_report=rendered_report,
            report_path=report_path,
        )

    def _resolve_plan_definitions(
        self,
        *,
        run: AssessmentRun,
        plan: AssessmentPlan,
    ) -> tuple[CommandDefinition, ...]:
        definitions: list[CommandDefinition] = []
        for item in plan.commands:
            try:
                definitions.append(self._command_catalog.get(item.command_id))
            except KeyError:
                self._fail(
                    run=run,
                    stage=RunnerStage.VALIDATION,
                    error_type="plan_command_not_in_catalog",
                    message=(
                        f"AssessmentPlan {plan.plan_id}@{plan.version} references unknown command "
                        f"{item.command_id.value}."
                    ),
                )
        return tuple(definitions)

    def _command_failure(
        self,
        *,
        run: AssessmentRun,
        definition: CommandDefinition,
        stage: RunnerStage,
        error_type: str,
        message: str,
        collection: DeviceCollectionResult,
        command_execution_id: UUID | None = None,
        collected: CommandCollectionResult | None = None,
    ) -> AssessmentCommandResult:
        if definition.requirement == CommandRequirement.REQUIRED:
            self._fail(
                run=run,
                stage=stage,
                error_type=error_type,
                message=message,
                command_execution_id=command_execution_id,
                collection=collection,
            )
        return AssessmentCommandResult(
            command_id=definition.command_id,
            requirement=definition.requirement,
            collection=collected,
            failure=RunnerFailure(
                stage=stage,
                error_type=error_type,
                message=message,
                command_execution_id=command_execution_id,
            ),
        )

    @staticmethod
    def _build_context(
        *,
        run: AssessmentRun,
        device: Device,
        command_results: tuple[AssessmentCommandResult, ...],
    ) -> AssessmentContext:
        source_evidence = tuple(
            NormalizedFieldSource(
                normalized_model=parse_result.trace.normalized_model.value,
                field_path=item.field,
                source=SourceTrace(
                    assessment_run_id=parse_result.trace.assessment_run_id,
                    command_execution_id=parse_result.trace.command_execution_id,
                    raw_output_id=parse_result.trace.raw_output_id,
                    raw_sha256=parse_result.trace.raw_sha256,
                    parser_id=parse_result.trace.parser_id.value,
                    parser_version=parse_result.trace.parser_version,
                    platform=parse_result.trace.platform,
                    extractor=item.extractor,
                    line_start=item.line_start,
                    line_end=item.line_end,
                ),
            )
            for command_result in command_results
            if command_result.parse_result is not None
            for parse_result in (command_result.parse_result,)
            for item in parse_result.evidence
        )
        return AssessmentContext(
            assessment_run_id=run.id,
            device_id=device.id,
            platform=device.platform_family,
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
        command_execution_id: UUID | None = None,
        collection: DeviceCollectionResult | None = None,
    ) -> NoReturn:
        AssessmentRunner._fail(
            run=run,
            stage=stage,
            error_type=type(exc).__name__,
            message=str(exc).strip() or "Unexpected orchestration error.",
            command_execution_id=command_execution_id,
            collection=collection,
        )

    @staticmethod
    def _fail(
        *,
        run: AssessmentRun,
        stage: RunnerStage,
        error_type: str,
        message: str,
        command_execution_id: UUID | None = None,
        collection: DeviceCollectionResult | None = None,
    ) -> NoReturn:
        failure = RunnerFailure(
            stage=stage,
            error_type=error_type,
            message=message,
            command_execution_id=command_execution_id,
        )
        run.status = AssessmentRunStatus.FAILED
        run.finished_at = utc_now()
        run.error_message = f"{stage.value}:{error_type}:{message}"[:4096]
        raise AssessmentRunnerError(run=run, failure=failure, collection=collection)
