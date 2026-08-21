from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    AssessmentRun,
    CommandExecution,
    CommandExecutionStatus,
    Device,
)


def make_run() -> AssessmentRun:
    device = Device(management_address="10.10.10.20")
    return AssessmentRun(
        device_id=device.id,
        framework_version="0.1.0",
        target_snapshot=device.snapshot(),
    )


def test_command_execution_references_assessment_run() -> None:
    run = make_run()

    execution = CommandExecution(
        assessment_run_id=run.id,
        command_key="system.version",
        command="show version",
        sequence=1,
        status=CommandExecutionStatus.SUCCESS,
        duration_ms=81,
    )

    assert execution.assessment_run_id == run.id
    assert execution.command_key == "system.version"
    assert execution.command == "show version"


def test_command_execution_rejects_zero_sequence() -> None:
    run = make_run()

    with pytest.raises(ValidationError):
        CommandExecution(
            assessment_run_id=run.id,
            command_key="system.version",
            command="show version",
            sequence=0,
        )


def test_command_execution_rejects_negative_duration() -> None:
    run = make_run()

    with pytest.raises(ValidationError):
        CommandExecution(
            assessment_run_id=run.id,
            command_key="system.version",
            command="show version",
            sequence=1,
            duration_ms=-1,
        )


def test_command_execution_rejects_finish_before_start() -> None:
    run = make_run()
    started = datetime(2026, 8, 21, 23, 14, tzinfo=UTC)

    with pytest.raises(ValidationError):
        CommandExecution(
            assessment_run_id=run.id,
            command_key="system.version",
            command="show version",
            sequence=1,
            started_at=started,
            finished_at=started - timedelta(milliseconds=1),
        )
