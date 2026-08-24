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
    PlatformFamily,
    VlanObservation,
    VlanStatus,
)
from cisco_assessment.parsers import IOSShowVlanBriefParser, ParseStatus, build_parser_registry
from cisco_assessment.runner import VLAN_OBSERVATION_PLAN_V0_1, build_runner

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ios"
_VERSION = _FIXTURES / "show_version" / "c9300_iosxe.txt"
_VLANS = _FIXTURES / "show_vlan_brief" / "c9300_iosxe_real_sanitized.raw"
_PROMPT = b"SW-CORE-01#"


class VlanObservationTransport:
    def __init__(self) -> None:
        self._chunks = [
            _PROMPT,
            b"show version\r\n" + _VERSION.read_bytes() + b"\r\n" + _PROMPT,
            _VLANS.read_bytes(),
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
        hostname="vlan-core-01",
        platform_family=PlatformFamily.IOS_XE,
    )


def test_productive_registry_resolves_vlan_brief_parser() -> None:
    parser = build_parser_registry().resolve(
        ParserId.IOS_SHOW_VLAN_BRIEF_V1,
        PlatformFamily.IOS_XE,
    )

    assert isinstance(parser, IOSShowVlanBriefParser)
    assert parser.descriptor.command_id is CommandId.VLANS_BRIEF
    assert parser.descriptor.normalized_model is NormalizedModelId.VLAN_OBSERVATION
    assert parser.descriptor.supported_platforms == frozenset(
        {PlatformFamily.IOS, PlatformFamily.IOS_XE}
    )


def test_vlan_observation_vertical_slice_assesses_and_reports_with_raw_trace(
    tmp_path: Path,
) -> None:
    transport = VlanObservationTransport()
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    result = runner.run(
        device=_device(),
        credentials=SSHCredentials(username="assessment", password="secret"),
        plan=VLAN_OBSERVATION_PLAN_V0_1,
    )

    assert result.run.status is AssessmentRunStatus.COMPLETED
    assert result.plan.command_ids == (
        CommandId.SYSTEM_VERSION,
        CommandId.VLANS_BRIEF,
    )
    assert transport.sent == [b"show version\n", b"show vlan brief\n", b" "]
    assert transport.closed is True
    assert len(result.collection.commands) == 2
    assert len(result.command_executions) == 2
    assert len(result.raw_outputs) == 2

    version_execution, vlan_execution = result.command_executions
    _version_raw, vlan_raw = result.raw_outputs
    assert [version_execution.sequence, vlan_execution.sequence] == [1, 2]
    assert version_execution.status is CommandExecutionStatus.SUCCESS
    assert vlan_execution.status is CommandExecutionStatus.SUCCESS
    assert vlan_execution.command_key == CommandId.VLANS_BRIEF.value
    assert vlan_raw.command_execution_id == vlan_execution.id
    assert b"--More--" in vlan_raw.content.encode(vlan_raw.encoding)
    assert "\b" in vlan_raw.content

    vlan_parse = result.vlan_observation_parse_result
    assert vlan_parse is not None
    assert vlan_parse.status is ParseStatus.SUCCESS
    assert isinstance(vlan_parse.data, VlanObservation)
    assert vlan_parse.trace.parser_id is ParserId.IOS_SHOW_VLAN_BRIEF_V1
    assert vlan_parse.trace.normalized_model is NormalizedModelId.VLAN_OBSERVATION
    assert vlan_parse.trace.command_execution_id == vlan_execution.id
    assert vlan_parse.trace.raw_output_id == vlan_raw.id
    assert vlan_parse.trace.raw_sha256 == vlan_raw.sha256
    assert result.hardware_inventory_parse_result is None
    assert result.interface_observation_parse_result is None

    vlans = vlan_parse.data.vlans
    assert len(vlans) == 17
    assert [record.ordinal for record in vlans] == list(range(1, 18))
    assert vlans[0].vlan_id == 1
    assert vlans[0].status is VlanStatus.ACTIVE
    assert vlans[0].ports is not None
    assert len(vlans[0].ports) == 54
    assert next(record for record in vlans if record.vlan_id == 2).ports == ()
    assert {
        record.vlan_id
        for record in vlans
        if record.status is VlanStatus.ACTIVE_UNSUPPORTED
    } == {1002, 1003, 1004, 1005}

    outcomes = {outcome.rule_id: outcome for outcome in result.assessment_result.outcomes}
    assert {"VLAN-001", "VLAN-002", "VLAN-003", "VLAN-004"}.issubset(outcomes)
    assert outcomes["VLAN-001"].status is AssessmentStatus.INFO
    assert outcomes["VLAN-002"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-003"].status is AssessmentStatus.PASS
    assert outcomes["VLAN-004"].status is AssessmentStatus.INFO

    vlan004 = outcomes["VLAN-004"]
    assert any(evidence.field_path == "vlans[13].status" for evidence in vlan004.evidence)
    raw_lines = vlan_raw.content.splitlines()
    status_evidence = next(
        evidence for evidence in vlan004.evidence if evidence.field_path == "vlans[13].status"
    )
    assert status_evidence.sources
    source = status_evidence.sources[0]
    assert source.assessment_run_id == result.run.id
    assert source.command_execution_id == vlan_execution.id
    assert source.raw_output_id == vlan_raw.id
    assert source.raw_sha256 == vlan_raw.sha256
    assert source.parser_id == "ios.show_vlan_brief.v1"
    assert source.line_start is not None
    source_line = raw_lines[source.line_start - 1]
    assert source_line.startswith("1002 ")
    assert "act/unsup" in source_line

    assert result.report.hardware_inventory is None
    assert result.report.interface_observation is None
    assert result.report.vlan_observation is not None
    assert result.report.vlan_observation.vlans == vlan_parse.data.vlans

    payload = json.loads(result.rendered_report.content)
    assert payload["hardware_inventory"] is None
    assert payload["interface_observation"] is None
    assert payload["vlan_observation"] is not None
    assert len(payload["vlan_observation"]["vlans"]) == 17
    assert payload["vlan_observation"]["vlans"][0]["vlan_id"] == 1
    assert len(payload["vlan_observation"]["vlans"][0]["ports"]) == 54
    vlan004_payload = next(
        item for item in payload["outcomes"] if item["rule"]["rule_id"] == "VLAN-004"
    )
    status_payload = next(
        item
        for item in vlan004_payload["evidence"]
        if item["field_path"] == "vlans[13].status"
    )
    source_payload = status_payload["sources"][0]
    assert source_payload["command_execution_id"] == str(vlan_execution.id)
    assert source_payload["raw_output_id"] == str(vlan_raw.id)
    assert source_payload["raw_sha256"] == vlan_raw.sha256
    assert source_payload["parser_id"] == "ios.show_vlan_brief.v1"
    assert result.report_path.read_bytes() == result.rendered_report.content
