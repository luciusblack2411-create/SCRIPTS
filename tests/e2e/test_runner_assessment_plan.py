from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from cisco_assessment.catalog import (
    CommandId,
    CommandRequirement,
    NormalizedModelId,
    ParserId,
)
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import AssessmentRunStatus, CommandExecutionStatus, Device, PlatformFamily
from cisco_assessment.parsers import (
    BaseParser,
    FieldEvidence,
    ParsedPayload,
    ParserDescriptor,
    build_parser_registry,
)
from cisco_assessment.runner import (
    AssessmentPlan,
    AssessmentPlanItem,
    AssessmentRunnerError,
    RunnerStage,
    build_runner,
)

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "ios" / "show_version" / "c9300_iosxe.txt"
_PROMPT = b"SW-CORE-01#"


class FakeStackInfo(BaseModel):
    member_count: int


class FakeStackParser(BaseParser[FakeStackInfo]):
    @property
    def descriptor(self) -> ParserDescriptor:
        return ParserDescriptor(
            parser_id=ParserId.IOS_SHOW_SWITCH_DETAIL_V1,
            parser_version="test-1",
            command_id=CommandId.SYSTEM_STACK,
            normalized_model=NormalizedModelId.STACK_INFO,
            supported_platforms=frozenset({PlatformFamily.IOS, PlatformFamily.IOS_XE}),
        )

    def _parse_content(
        self,
        content: str,
        platform: PlatformFamily,
    ) -> ParsedPayload[FakeStackInfo]:
        del content, platform
        return ParsedPayload(
            data=FakeStackInfo(member_count=2),
            evidence=(
                FieldEvidence(
                    field="member_count",
                    extractor="fake.stack.member_count",
                    line_start=1,
                    line_end=1,
                ),
            ),
        )


class MultiCommandTransport:
    def __init__(self, responses: tuple[tuple[str, bytes], ...]) -> None:
        self._chunks = [_PROMPT]
        self._chunks.extend(
            command.encode("ascii") + b"\r\n" + output + b"\r\n" + _PROMPT
            for command, output in responses
        )
        self.sent: list[bytes] = []
        self.closed = False

    def connect(self, **kwargs: object) -> None:
        del kwargs

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return self._chunks.pop(0)

    def receive_ready(self) -> bool:
        return bool(self._chunks)

    def close(self) -> None:
        self.closed = True


def _device() -> Device:
    return Device(
        management_address="192.0.2.10",
        hostname="inventory-core-01",
        platform_family=PlatformFamily.IOS_XE,
    )


def _plan(*command_ids: CommandId) -> AssessmentPlan:
    return AssessmentPlan(
        plan_id="test-plan",
        version="0.2",
        commands=tuple(AssessmentPlanItem(command_id=item) for item in command_ids),
    )


def test_multi_command_plan_executes_in_order_and_traces_each_model(tmp_path: Path) -> None:
    registry = build_parser_registry()
    registry.register(FakeStackParser())
    transport = MultiCommandTransport(
        (
            ("show version", _FIXTURE.read_bytes()),
            ("show switch detail", b"Switch members: 2"),
        )
    )
    runner = build_runner(
        output_root=tmp_path,
        transport_factory=lambda: transport,
        parser_registry=registry,
    )

    result = runner.run(
        device=_device(),
        credentials=SSHCredentials(username="assessment", password="secret"),
        plan=_plan(CommandId.SYSTEM_VERSION, CommandId.SYSTEM_STACK),
    )

    assert result.run.status == AssessmentRunStatus.COMPLETED
    assert result.plan.command_ids == (CommandId.SYSTEM_VERSION, CommandId.SYSTEM_STACK)
    assert [item.sequence for item in result.command_executions] == [1, 2]
    assert [item.status for item in result.command_executions] == [
        CommandExecutionStatus.SUCCESS,
        CommandExecutionStatus.SUCCESS,
    ]
    assert len(result.raw_outputs) == 2
    assert transport.sent == [b"show version\n", b"show switch detail\n"]
    assert transport.closed is True

    version_result, stack_result = result.command_results
    assert version_result.requirement == CommandRequirement.REQUIRED
    assert stack_result.requirement == CommandRequirement.OPTIONAL
    assert version_result.succeeded is True
    assert stack_result.succeeded is True
    assert stack_result.parse_result is not None
    assert stack_result.parse_result.trace.normalized_model == NormalizedModelId.STACK_INFO
    assert isinstance(stack_result.normalized_model, FakeStackInfo)

    stack_collection = result.collection.commands[1]
    assert stack_result.parse_result.trace.command_execution_id == stack_collection.execution.id
    assert stack_collection.raw_output is not None
    assert stack_result.parse_result.trace.raw_output_id == stack_collection.raw_output.id
    assert stack_result.parse_result.trace.raw_sha256 == stack_collection.raw_output.sha256
    assert result.parse_result.data.hostname == "SW-CORE-01"
    assert result.report_path.exists()


def test_optional_parser_failure_yields_partial_and_keeps_report(tmp_path: Path) -> None:
    transport = MultiCommandTransport(
        (
            ("show version", _FIXTURE.read_bytes()),
            ("show switch detail", b"Switch members: 2"),
        )
    )
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    result = runner.run(
        device=_device(),
        credentials=SSHCredentials(username="assessment", password="secret"),
        plan=_plan(CommandId.SYSTEM_VERSION, CommandId.SYSTEM_STACK),
    )

    assert result.run.status == AssessmentRunStatus.PARTIAL
    assert len(result.raw_outputs) == 2
    optional_result = result.command_results[1]
    assert optional_result.requirement == CommandRequirement.OPTIONAL
    assert optional_result.succeeded is False
    assert optional_result.failure is not None
    assert optional_result.failure.stage == RunnerStage.PARSING
    assert optional_result.failure.error_type == "ParserNotFoundError"
    assert optional_result.collection is not None
    assert optional_result.collection.raw_output is not None
    assert result.report_path.exists()


def test_required_parser_failure_fails_run_but_preserves_all_raw(tmp_path: Path) -> None:
    transport = MultiCommandTransport(
        (
            ("show version", _FIXTURE.read_bytes()),
            ("show inventory", b"NAME: chassis, PID: C9300-48P, SN: FCW0000A1B2"),
        )
    )
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    with pytest.raises(AssessmentRunnerError) as caught:
        runner.run(
            device=_device(),
            credentials=SSHCredentials(username="assessment", password="secret"),
            plan=_plan(CommandId.SYSTEM_VERSION, CommandId.SYSTEM_INVENTORY),
        )

    error = caught.value
    assert error.run.status == AssessmentRunStatus.FAILED
    assert error.failure.stage == RunnerStage.PARSING
    assert error.failure.error_type == "ParserNotFoundError"
    assert error.collection is not None
    assert len(error.collection.commands) == 2
    assert all(
        item.execution.status == CommandExecutionStatus.SUCCESS
        for item in error.collection.commands
    )
    assert all(item.raw_output is not None for item in error.collection.commands)
    assert transport.sent == [b"show version\n", b"show inventory\n"]
    assert not list(tmp_path.glob("*/report/*.json"))
