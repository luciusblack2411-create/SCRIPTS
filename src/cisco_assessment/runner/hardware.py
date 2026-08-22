"""Hardware-inventory extension of the v0.2 assessment runner."""

from __future__ import annotations

from typing import cast

from cisco_assessment.assessment import AssessmentEngine, AssessmentResult, AssessmentStatus
from cisco_assessment.catalog import CommandId
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import AssessmentRunStatus, Device, HardwareInventory
from cisco_assessment.parsers import ParseResult

from .models import AssessmentRunnerResult
from .plan import AssessmentPlan
from .service import AssessmentRunner


class HardwareInventoryAssessmentRunner(AssessmentRunner):
    """Run the established pipeline, then evaluate the HardwareInventory slice.

    Collection and parsing remain owned by ``AssessmentRunner`` so CommandExecution,
    RawCommandOutput and parser traceability remain independent per command.
    """

    def __init__(
        self,
        *,
        hardware_inventory_engine: AssessmentEngine[HardwareInventory],
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._hardware_inventory_engine = hardware_inventory_engine

    def run(
        self,
        *,
        device: Device,
        credentials: SSHCredentials,
        plan: AssessmentPlan | None = None,
    ) -> AssessmentRunnerResult:
        base_result = super().run(device=device, credentials=credentials, plan=plan)

        hardware_parse: ParseResult[HardwareInventory] | None = None
        for command_result in base_result.command_results:
            if command_result.command_id != CommandId.SYSTEM_INVENTORY:
                continue
            parse_result = command_result.parse_result
            if parse_result is not None and isinstance(parse_result.data, HardwareInventory):
                hardware_parse = cast(ParseResult[HardwareInventory], parse_result)
                break

        if hardware_parse is None:
            return base_result

        context = self._build_context(
            run=base_result.run,
            device=device,
            command_results=base_result.command_results,
        )
        hardware_result = self._hardware_inventory_engine.evaluate(hardware_parse.data, context)
        assessment_result = self._merge_results(base_result.assessment_result, hardware_result)

        if any(outcome.status == AssessmentStatus.ERROR for outcome in hardware_result.outcomes):
            base_result.run.status = AssessmentRunStatus.PARTIAL

        report = self._report_builder.build(
            run=base_result.run,
            result=assessment_result,
            device_info=base_result.device_info_parse_result.data,
            hardware_inventory=hardware_parse.data,
        )
        rendered_report = self._report_renderer.render(report)
        report_path = self._persist_report(
            run=base_result.run,
            content=rendered_report.content,
            extension=rendered_report.extension,
        )

        return AssessmentRunnerResult(
            run=base_result.run,
            plan=base_result.plan,
            collection=base_result.collection,
            command_results=base_result.command_results,
            device_info_parse_result=base_result.device_info_parse_result,
            assessment_result=assessment_result,
            report=report,
            rendered_report=rendered_report,
            report_path=report_path,
            hardware_inventory_parse_result=hardware_parse,
        )

    @staticmethod
    def _merge_results(primary: AssessmentResult, secondary: AssessmentResult) -> AssessmentResult:
        if primary.assessment_run_id != secondary.assessment_run_id:
            raise ValueError("Assessment result run IDs do not match")
        if primary.device_id != secondary.device_id or primary.platform != secondary.platform:
            raise ValueError("Assessment result device identity does not match")
        return AssessmentResult(
            assessment_run_id=primary.assessment_run_id,
            device_id=primary.device_id,
            platform=primary.platform,
            normalized_model=primary.normalized_model,
            outcomes=primary.outcomes + secondary.outcomes,
            findings=primary.findings + secondary.findings,
        )
