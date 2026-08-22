from __future__ import annotations

import json
from pathlib import Path

import pytest

from cisco_assessment.assessment import AssessmentStatus
from cisco_assessment.collector.exceptions import AuthenticationError
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import (
    AssessmentRunStatus,
    CommandExecutionStatus,
    Device,
    PlatformFamily,
)
from cisco_assessment.runner import AssessmentRunnerError, RunnerStage, build_runner

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "ios" / "show_version" / "c9300_iosxe.txt"


class FakeShowVersionTransport:
    def __init__(self, output: bytes) -> None:
        self._chunks = [
            b"SW-CORE-01#",
            b"show version\r\n" + output + b"\r\nSW-CORE-01#",
        ]
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


class FailingAuthenticationTransport:
    def __init__(self) -> None:
        self.closed = False

    def connect(self, **kwargs: object) -> None:
        del kwargs
        raise AuthenticationError("bad credentials")

    def send(self, data: bytes) -> None:
        del data

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        return b""

    def receive_ready(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


def _device() -> Device:
    return Device(
        management_address="192.0.2.10",
        hostname="inventory-core-01",
        platform_family=PlatformFamily.IOS_XE,
    )


def test_show_version_runner_preserves_traceability_and_persists_json(tmp_path: Path) -> None:
    transport = FakeShowVersionTransport(_FIXTURE.read_bytes())
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    result = runner.run(
        device=_device(),
        credentials=SSHCredentials(username="assessment", password="secret"),
    )

    assert result.run.status == AssessmentRunStatus.COMPLETED
    assert result.run.finished_at is not None
    assert result.run.command_catalog_version == "0.1"
    assert result.run.ruleset_version == "0.1.0"
    assert len(result.command_executions) == 1
    assert result.command_executions[0].status == CommandExecutionStatus.SUCCESS
    assert len(result.raw_outputs) == 1
    assert result.collection.commands[0].raw_path is not None
    assert result.collection.commands[0].raw_path.exists()
    assert transport.sent == [b"show version\n"]
    assert transport.closed is True

    device_info = result.normalized_models[0]
    assert device_info.platform == PlatformFamily.IOS_XE
    assert device_info.hostname == "SW-CORE-01"
    assert device_info.software_version == "17.09.04a"
    assert device_info.model == "C9300-48P"
    assert device_info.serial_number == "FCW0000A1B2"
    assert device_info.boot_mode == "INSTALL"

    assert {outcome.rule_id for outcome in result.assessment_result.outcomes} == {
        "SYS-001",
        "SYS-002",
        "SYS-003",
    }
    assert any(
        outcome.rule_id == "SYS-003" and outcome.status == AssessmentStatus.INFO
        for outcome in result.assessment_result.outcomes
    )

    assert result.report_path.exists()
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["run"]["assessment_run_id"] == str(result.run.id)
    assert payload["run"]["status"] == "completed"
    assert payload["device_info"]["hostname"] == "SW-CORE-01"

    software_finding = next(
        finding for finding in payload["findings"] if finding["rule"]["rule_id"] == "SYS-003"
    )
    software_evidence = next(
        item for item in software_finding["evidence"] if item["field_path"] == "software_version"
    )
    source = software_evidence["sources"][0]
    command = result.collection.commands[0]
    assert source["assessment_run_id"] == str(result.run.id)
    assert source["command_execution_id"] == str(command.execution.id)
    assert source["raw_output_id"] == str(command.raw_output.id)
    assert source["raw_sha256"] == command.raw_output.sha256
    assert source["parser_id"] == "ios.show_version.v1"


def test_collection_failure_closes_run_and_retains_command_execution(tmp_path: Path) -> None:
    transport = FailingAuthenticationTransport()
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    with pytest.raises(AssessmentRunnerError) as caught:
        runner.run(
            device=_device(),
            credentials=SSHCredentials(username="assessment", password="wrong"),
        )

    error = caught.value
    assert error.failure.stage == RunnerStage.COLLECTION
    assert error.failure.error_type == "authentication_failed"
    assert error.run.status == AssessmentRunStatus.FAILED
    assert error.run.finished_at is not None
    assert error.run.error_message is not None
    assert error.collection is not None
    assert len(error.collection.commands) == 1
    assert error.collection.commands[0].execution.status == CommandExecutionStatus.TRANSPORT_ERROR
    assert error.collection.commands[0].raw_output is None
    assert transport.closed is True


def test_parse_failure_preserves_raw_and_closes_run(tmp_path: Path) -> None:
    transport = FakeShowVersionTransport(b"unrecognized sanitized output")
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    with pytest.raises(AssessmentRunnerError) as caught:
        runner.run(
            device=_device(),
            credentials=SSHCredentials(username="assessment", password="secret"),
        )

    error = caught.value
    assert error.failure.stage == RunnerStage.PARSING
    assert error.failure.error_type == "UnrecognizedFormatError"
    assert error.run.status == AssessmentRunStatus.FAILED
    assert error.collection is not None
    collected = error.collection.commands[0]
    assert collected.execution.status == CommandExecutionStatus.SUCCESS
    assert collected.raw_output is not None
    assert collected.raw_path is not None
    assert collected.raw_path.exists()
    assert "unrecognized sanitized output" in collected.raw_output.content
    assert not list(tmp_path.glob("*/report/*.json"))
