from hashlib import sha256

import pytest
from pydantic import ValidationError

from cisco_assessment.models import (
    AssessmentRun,
    CommandExecution,
    Device,
    RawCommandOutput,
)


def make_execution() -> CommandExecution:
    device = Device(management_address="10.10.10.20")
    run = AssessmentRun(
        device_id=device.id,
        framework_version="0.1.0",
        target_snapshot=device.snapshot(),
    )
    return CommandExecution(
        assessment_run_id=run.id,
        command_key="system.version",
        command="show version",
        sequence=1,
    )


def test_raw_factory_preserves_content_exactly_and_calculates_integrity() -> None:
    execution = make_execution()
    content = "show version\r\nCisco IOS XE Software\r\nSW-CORE-01#"

    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content=content,
    )

    payload = content.encode("utf-8")
    assert raw.command_execution_id == execution.id
    assert raw.content == content
    assert raw.byte_length == len(payload)
    assert raw.sha256 == sha256(payload).hexdigest()
    assert raw.is_truncated is False


def test_raw_output_is_frozen() -> None:
    execution = make_execution()
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content="Cisco IOS XE Software\n",
    )

    with pytest.raises(ValidationError):
        raw.content = "modified"  # type: ignore[misc]


def test_raw_output_rejects_invalid_hash() -> None:
    execution = make_execution()

    with pytest.raises(ValidationError):
        RawCommandOutput(
            command_execution_id=execution.id,
            content="raw",
            sha256="not-a-sha256",
            byte_length=3,
        )


def test_raw_output_rejects_unknown_encoding() -> None:
    execution = make_execution()

    with pytest.raises(ValidationError):
        RawCommandOutput(
            command_execution_id=execution.id,
            content="raw",
            encoding="definitely-not-an-encoding",
            sha256="0" * 64,
            byte_length=3,
        )


def test_raw_output_rejects_integrity_metadata_that_does_not_match_content() -> None:
    execution = make_execution()

    with pytest.raises(ValidationError):
        RawCommandOutput(
            command_execution_id=execution.id,
            content="raw",
            sha256="0" * 64,
            byte_length=3,
        )
