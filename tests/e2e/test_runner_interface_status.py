from __future__ import annotations

import json
from pathlib import Path

from cisco_assessment.assessment import AssessmentStatus
from cisco_assessment.catalog import CommandId, NormalizedModelId, ParserId
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import (
    AssessmentRunStatus,
    CommandExecutionStatus,
    Device,
    InterfaceObservation,
    PlatformFamily,
)
from cisco_assessment.parsers import (
    IOSShowInterfacesStatusParser,
    ParseStatus,
    build_parser_registry,
)
from cisco_assessment.runner import INTERFACE_STATUS_PLAN_V0_1, build_runner

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ios"
_VERSION = _FIXTURES / "show_version" / "c9300_iosxe.txt"
_INTERFACES = _FIXTURES / "show_interfaces_status" / "c9300_iosxe_genie_v0_1.txt"
_PROMPT = b"SW-CORE-01#"


class InterfaceStatusTransport:
    def __init__(self) -> None:
        self._chunks = [
            _PROMPT,
            b"show version\r\n" + _VERSION.read_bytes() + b"\r\n" + _PROMPT,
            b"show interfaces status\r\n" + _INTERFACES.read_bytes() + b"\r\n" + _PROMPT,
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


def _device() -> Device:
    return Device(
        management_address="192.0.2.10",
        hostname="interfaces-core-01",
        platform_family=PlatformFamily.IOS_XE,
    )


def test_productive_registry_resolves_genie_backed_interface_status_parser() -> None:
    parser = build_parser_registry().resolve(
        ParserId.IOS_SHOW_INTERFACES_STATUS_V1,
        PlatformFamily.IOS_XE,
    )

    assert isinstance(parser, IOSShowInterfacesStatusParser)
    assert parser.descriptor.command_id is CommandId.INTERFACES_STATUS
    assert parser.descriptor.normalized_model is NormalizedModelId.INTERFACE_OBSERVATION
    assert parser.descriptor.supported_platforms == frozenset(
        {PlatformFamily.IOS, PlatformFamily.IOS_XE}
    )


def test_interface_status_vertical_slice_assesses_and_reports_with_raw_trace(
    tmp_path: Path,
) -> None:
    transport = InterfaceStatusTransport()
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    result = runner.run(
        device=_device(),
        credentials=SSHCredentials(username="assessment", password="secret"),
        plan=INTERFACE_STATUS_PLAN_V0_1,
    )

    assert result.run.status is AssessmentRunStatus.COMPLETED
    assert result.plan.command_ids == (
        CommandId.SYSTEM_VERSION,
        CommandId.INTERFACES_STATUS,
    )
    assert transport.sent == [b"show version\n", b"show interfaces status\n"]
    assert transport.closed is True
    assert len(result.collection.commands) == 2
    assert len(result.command_executions) == 2
    assert len(result.raw_outputs) == 2

    version_execution, interface_execution = result.command_executions
    version_raw, interface_raw = result.raw_outputs
    assert [version_execution.sequence, interface_execution.sequence] == [1, 2]
    assert version_execution.status is CommandExecutionStatus.SUCCESS
    assert interface_execution.status is CommandExecutionStatus.SUCCESS
    assert interface_execution.command_key == CommandId.INTERFACES_STATUS.value
    assert interface_raw.command_execution_id == interface_execution.id

    interface_parse = result.interface_observation_parse_result
    assert interface_parse is not None
    assert interface_parse.status is ParseStatus.SUCCESS
    assert isinstance(interface_parse.data, InterfaceObservation)
    assert interface_parse.trace.parser_id is ParserId.IOS_SHOW_INTERFACES_STATUS_V1
    assert interface_parse.trace.normalized_model is NormalizedModelId.INTERFACE_OBSERVATION
    assert interface_parse.trace.command_execution_id == interface_execution.id
    assert interface_parse.trace.raw_output_id == interface_raw.id
    assert interface_parse.trace.raw_sha256 == interface_raw.sha256
    assert result.hardware_inventory_parse_result is None

    statuses = {record.interface: record.status for record in interface_parse.data.interfaces}
    assert statuses["GigabitEthernet1/0/4"] == "err-disabled"
    assert statuses["GigabitEthernet1/0/2"] == "notconnect"

    outcomes = {outcome.rule_id: outcome for outcome in result.assessment_result.outcomes}
    assert {"INT-001", "INT-002", "INT-003", "INT-004"}.issubset(outcomes)
    assert outcomes["INT-001"].status is AssessmentStatus.FAIL
    assert outcomes["INT-002"].status is AssessmentStatus.INFO
    assert outcomes["INT-003"].status is AssessmentStatus.INFO
    assert outcomes["INT-004"].status is AssessmentStatus.PASS

    int001 = outcomes["INT-001"]
    assert {evidence.field_path for evidence in int001.evidence} == {
        "interfaces[3].interface",
        "interfaces[3].status",
    }
    for evidence in int001.evidence:
        assert evidence.sources
        source = evidence.sources[0]
        assert source.assessment_run_id == result.run.id
        assert source.command_execution_id == interface_execution.id
        assert source.raw_output_id == interface_raw.id
        assert source.raw_sha256 == interface_raw.sha256
        assert source.parser_id == "ios.show_interfaces_status.v1"
        assert source.line_start == 5
        assert source.line_end == 5

    interface_findings = tuple(
        finding
        for finding in result.assessment_result.findings
        if finding.rule_id.startswith("INT-")
    )
    assert {finding.rule_id for finding in interface_findings} == {
        "INT-001",
        "INT-002",
        "INT-003",
    }
    assert all(
        evidence.observed_value != "notconnect"
        for finding in interface_findings
        for evidence in finding.evidence
    )

    assert result.report.hardware_inventory is None
    assert result.report.interface_observation is not None
    assert len(result.report.interface_observation.interfaces) == len(interface_parse.data.interfaces)

    payload = json.loads(result.rendered_report.content)
    assert payload["hardware_inventory"] is None
    assert payload["interface_observation"] is not None
    assert len(payload["interface_observation"]["interfaces"]) == 7
    int001_payload = next(
        item for item in payload["outcomes"] if item["rule"]["rule_id"] == "INT-001"
    )
    status_evidence = next(
        item
        for item in int001_payload["evidence"]
        if item["field_path"] == "interfaces[3].status"
    )
    source_payload = status_evidence["sources"][0]
    assert source_payload["command_execution_id"] == str(interface_execution.id)
    assert source_payload["raw_output_id"] == str(interface_raw.id)
    assert source_payload["raw_sha256"] == interface_raw.sha256
    assert source_payload["parser_id"] == "ios.show_interfaces_status.v1"
    assert result.report_path.read_bytes() == result.rendered_report.content
