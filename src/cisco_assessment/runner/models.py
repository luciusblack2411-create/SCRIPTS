"""Result contracts for the first end-to-end assessment runner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cisco_assessment.assessment import AssessmentResult
from cisco_assessment.collector import DeviceCollectionResult
from cisco_assessment.models import AssessmentRun, CommandExecution, DeviceInfo, RawCommandOutput
from cisco_assessment.parsers import ParseResult
from cisco_assessment.reporting import AssessmentReport, RenderedReport


@dataclass(frozen=True, slots=True)
class AssessmentRunnerResult:
    """Successful orchestration result retaining every cross-layer artifact."""

    run: AssessmentRun
    collection: DeviceCollectionResult
    parse_result: ParseResult[DeviceInfo]
    assessment_result: AssessmentResult
    report: AssessmentReport
    rendered_report: RenderedReport
    report_path: Path

    @property
    def command_executions(self) -> tuple[CommandExecution, ...]:
        return tuple(item.execution for item in self.collection.commands)

    @property
    def raw_outputs(self) -> tuple[RawCommandOutput, ...]:
        return tuple(
            item.raw_output
            for item in self.collection.commands
            if item.raw_output is not None
        )

    @property
    def normalized_models(self) -> tuple[DeviceInfo, ...]:
        return (self.parse_result.data,)
