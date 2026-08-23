"""Result contracts for assessment-plan orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from cisco_assessment.assessment import AssessmentResult
from cisco_assessment.catalog import CommandId, CommandRequirement
from cisco_assessment.collector import CommandCollectionResult, DeviceCollectionResult
from cisco_assessment.models import (
    AssessmentRun,
    CommandExecution,
    DeviceInfo,
    HardwareInventory,
    InterfaceObservation,
    RawCommandOutput,
)
from cisco_assessment.parsers import ParseResult
from cisco_assessment.reporting import AssessmentReport, RenderedReport

from .errors import RunnerFailure
from .plan import AssessmentPlan


@dataclass(frozen=True, slots=True)
class AssessmentCommandResult:
    """Collection/parse outcome for one command in an AssessmentPlan."""

    command_id: CommandId
    requirement: CommandRequirement
    collection: CommandCollectionResult | None
    parse_result: ParseResult[Any] | None = None
    failure: RunnerFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None and self.parse_result is not None

    @property
    def normalized_model(self) -> BaseModel | None:
        if self.parse_result is None:
            return None
        return cast(BaseModel, self.parse_result.data)


@dataclass(frozen=True, slots=True)
class AssessmentRunnerResult:
    """Successful orchestration result retaining every cross-layer artifact."""

    run: AssessmentRun
    plan: AssessmentPlan
    collection: DeviceCollectionResult
    command_results: tuple[AssessmentCommandResult, ...]
    device_info_parse_result: ParseResult[DeviceInfo]
    assessment_result: AssessmentResult
    report: AssessmentReport
    rendered_report: RenderedReport
    report_path: Path
    hardware_inventory_parse_result: ParseResult[HardwareInventory] | None = None
    interface_observation_parse_result: ParseResult[InterfaceObservation] | None = None

    @property
    def parse_result(self) -> ParseResult[DeviceInfo]:
        """Backward-compatible alias for the productive DeviceInfo parse result."""
        return self.device_info_parse_result

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
    def normalized_models(self) -> tuple[BaseModel, ...]:
        return tuple(
            model
            for item in self.command_results
            if (model := item.normalized_model) is not None
        )
