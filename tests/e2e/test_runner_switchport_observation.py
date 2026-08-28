from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cisco_assessment.assessment import AssessmentStatus
from cisco_assessment.catalog import (
    COMMAND_CATALOG_V0_1,
    CommandId,
    CommandRequirement,
    NormalizedModelId,
    ParserId,
)
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import (
    AssessmentRunStatus,
    CommandExecutionStatus,
    Device,
    PlatformFamily,
    SwitchportObservation,
)
from cisco_assessment.parsers import ParseStatus
from cisco_assessment.runner import (
    SWITCHPORT_OBSERVATION_PLAN_V0_1,
    ProductiveAssessmentPlanId,
    build_runner,
    resolve_productive_assessment_plan,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ios"
_VERSION = _FIXTURES / "show_version" / "c9300_iosxe.txt"
_SWITCHPORT = (
    _FIXTURES
    / "show_interfaces_switchport"
    / "c9300_iosxe_real_sanitized.raw"
)

_PROMPT = b"LAB-SWITCH0#"
_PAGER = b"--More--"

_EXPECTED_SHA256 = (
    "901b9a1a3aed745e4f228c0c5332bf956293078654d4f15c5f086cc051cce422"
)


class SwitchportPagerTransport:
    def __init__(self) -> None:
        self.raw = _SWITCHPORT.read_bytes()
        self.sent: list[bytes] = []
        self.closed = False

        self._opened = False
        self._version_pending = False
        self._switchport_started = False

        self._offset = 0
        self._continuations = 0

    @property
    def continuations(self) -> int:
        return self._continuations

    def connect(self, **kwargs: object) -> None:
        del kwargs

    def send(self, data: bytes) -> None:
        self.sent.append(data)

        if data == b"show version\n":
            if self._version_pending or self._switchport_started:
                raise AssertionError(
                    "show version sent at invalid state"
                )

            self._version_pending = True
            return

        if data == b"show interfaces switchport\n":
            if self._switchport_started:
                raise AssertionError(
                    "switchport command sent more than once"
                )

            self._switchport_started = True
            return

        if data == b" ":
            if not self._switchport_started:
                raise AssertionError(
                    "pager continuation before switchport command"
                )

            observed = self.raw[
                : self._offset
            ].count(_PAGER)

            if self._continuations >= observed:
                raise AssertionError(
                    "duplicate or premature pager continuation"
                )

            self._continuations += 1
            return

        raise AssertionError(
            f"unexpected transport send: {data!r}"
        )

    def receive_ready(self) -> bool:
        if not self._opened:
            return True

        if self._version_pending:
            return True

        if not self._switchport_started:
            return False

        if self._offset >= len(self.raw):
            return False

        if self._offset == 0:
            return True

        observed = self.raw[
            : self._offset
        ].count(_PAGER)

        return self._continuations == observed

    def receive(
        self,
        max_bytes: int = 65535,
    ) -> bytes:
        del max_bytes

        if not self._opened:
            self._opened = True
            return _PROMPT

        if self._version_pending:
            self._version_pending = False

            return (
                b"show version\r\n"
                + _VERSION.read_bytes()
                + b"\r\n"
                + _PROMPT
            )

        if not self._switchport_started:
            raise AssertionError(
                "switchport bytes requested before command"
            )

        next_marker = self.raw.find(
            _PAGER,
            self._offset,
        )

        end = (
            len(self.raw)
            if next_marker < 0
            else next_marker + len(_PAGER)
        )

        chunk = self.raw[
            self._offset : end
        ]

        self._offset = end
        return chunk

    def close(self) -> None:
        self.closed = True


def test_switchport_plan_contract() -> None:
    plan = SWITCHPORT_OBSERVATION_PLAN_V0_1

    assert plan.plan_id == "switchport-observation"
    assert plan.version == "0.1"

    assert plan.command_ids == (
        CommandId.SYSTEM_VERSION,
        CommandId.INTERFACES_SWITCHPORT,
    )

    assert resolve_productive_assessment_plan(
        ProductiveAssessmentPlanId.SWITCHPORT_OBSERVATION
    ) is plan

    assert tuple(
        COMMAND_CATALOG_V0_1.get(
            command_id
        ).requirement
        for command_id in plan.command_ids
    ) == (
        CommandRequirement.REQUIRED,
        CommandRequirement.REQUIRED,
    )


def test_switchport_productive_runner_preserves_real_paged_raw_and_evaluates_rules(
    tmp_path: Path,
) -> None:
    fixture = _SWITCHPORT.read_bytes()

    assert (
        hashlib.sha256(fixture).hexdigest()
        == _EXPECTED_SHA256
    )

    assert fixture.count(_PAGER) == 244

    assert fixture.startswith(
        b"show interfaces switchport\r\n"
    )

    assert fixture.endswith(_PROMPT)

    transport = SwitchportPagerTransport()

    runner = build_runner(
        output_root=tmp_path,
        transport_factory=lambda: transport,
    )

    result = runner.run(
        device=Device(
            management_address="192.0.2.10",
            hostname="switchport-core-01",
            platform_family=PlatformFamily.IOS_XE,
        ),
        credentials=SSHCredentials(
            username="assessment",
            password="secret",
        ),
        plan=SWITCHPORT_OBSERVATION_PLAN_V0_1,
    )

    assert (
        result.run.status
        is AssessmentRunStatus.COMPLETED
    )

    assert result.plan.command_ids == (
        CommandId.SYSTEM_VERSION,
        CommandId.INTERFACES_SWITCHPORT,
    )

    assert transport.sent == [
        b"show version\n",
        b"show interfaces switchport\n",
        *([b" "] * 244),
    ]

    assert transport.continuations == 244
    assert transport.closed is True

    assert len(result.collection.commands) == 2
    assert len(result.command_executions) == 2
    assert len(result.raw_outputs) == 2

    (
        version_execution,
        switchport_execution,
    ) = result.command_executions

    (
        _version_raw,
        switchport_raw,
    ) = result.raw_outputs

    assert (
        version_execution.status
        is CommandExecutionStatus.SUCCESS
    )

    assert (
        switchport_execution.status
        is CommandExecutionStatus.SUCCESS
    )

    assert (
        switchport_execution.command_key
        == CommandId.INTERFACES_SWITCHPORT.value
    )

    assert (
        switchport_raw.command_execution_id
        == switchport_execution.id
    )

    assert (
        switchport_raw.content.encode(
            switchport_raw.encoding
        )
        == fixture
    )

    assert (
        switchport_raw.sha256
        == _EXPECTED_SHA256
    )

    assert (
        switchport_raw.content.count("--More--")
        == 244
    )

    parsed = (
        result.switchport_observation_parse_result
    )

    assert parsed is not None
    assert parsed.status is ParseStatus.SUCCESS

    assert isinstance(
        parsed.data,
        SwitchportObservation,
    )

    assert (
        parsed.trace.parser_id
        is ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1
    )

    assert (
        parsed.trace.normalized_model
        is NormalizedModelId.SWITCHPORT_OBSERVATION
    )

    assert (
        parsed.trace.command_execution_id
        == switchport_execution.id
    )

    assert (
        parsed.trace.raw_output_id
        == switchport_raw.id
    )

    assert (
        parsed.trace.raw_sha256
        == _EXPECTED_SHA256
    )

    assert len(parsed.data.interfaces) == 310

    outcomes = {
        outcome.rule_id: outcome
        for outcome
        in result.assessment_result.outcomes
        if outcome.rule_id.startswith("SWP-")
    }

    assert set(outcomes) == {
        "SWP-001",
        "SWP-002",
        "SWP-003",
        "SWP-004",
    }

    assert all(
        outcome.status
        not in {
            AssessmentStatus.ERROR,
            AssessmentStatus.WARNING,
            AssessmentStatus.FAIL,
        }
        for outcome in outcomes.values()
    )

    swp001 = outcomes["SWP-001"]

    interface_evidence = next(
        evidence
        for evidence in swp001.evidence
        if evidence.field_path
        == "interfaces[0].interface"
    )

    assert interface_evidence.sources

    source = interface_evidence.sources[0]

    assert (
        source.assessment_run_id
        == result.run.id
    )

    assert (
        source.command_execution_id
        == switchport_execution.id
    )

    assert (
        source.raw_output_id
        == switchport_raw.id
    )

    assert (
        source.raw_sha256
        == _EXPECTED_SHA256
    )

    assert (
        source.parser_id
        == "ios.show_interfaces_switchport.v1"
    )

    assert source.line_start is not None

    raw_lines = (
        switchport_raw.content.splitlines()
    )

    source_line = raw_lines[
        source.line_start - 1
    ]

    assert (
        parsed.data.interfaces[0].interface
        in source_line
    )

    assert (
        result.report.hardware_inventory
        is None
    )

    assert (
        result.report.interface_observation
        is None
    )

    assert (
        result.report.vlan_observation
        is None
    )

    switchport_report = result.report.switchport_observation
    assert switchport_report is not None
    assert switchport_report.normalized_model == "SwitchportObservation"
    assert switchport_report.schema_version == parsed.data.schema_version
    assert switchport_report.vendor == parsed.data.vendor
    assert switchport_report.platform is parsed.data.platform
    assert len(switchport_report.interfaces) == len(parsed.data.interfaces)
    assert tuple(
        item.ordinal for item in switchport_report.interfaces
    ) == tuple(
        item.ordinal for item in parsed.data.interfaces
    )
    assert tuple(
        item.interface for item in switchport_report.interfaces
    ) == tuple(
        item.interface for item in parsed.data.interfaces
    )

    payload = json.loads(
        result.rendered_report.content
    )

    switchport_payload = payload["switchport_observation"]
    assert switchport_payload["normalized_model"] == "SwitchportObservation"
    assert switchport_payload["schema_version"] == "0.1"
    assert len(switchport_payload["interfaces"]) == 310
    assert switchport_payload["interfaces"] == [
        item.model_dump(mode="json")
        for item in switchport_report.interfaces
    ]

    report_swp_rule_ids = {
        item["rule"]["rule_id"]
        for item in payload["outcomes"]
        if item["rule"]["rule_id"].startswith(
            "SWP-"
        )
    }

    assert report_swp_rule_ids == {
        "SWP-001",
        "SWP-002",
        "SWP-003",
        "SWP-004",
    }

    swp001_payload = next(
        item
        for item in payload["outcomes"]
        if item["rule"]["rule_id"] == "SWP-001"
    )
    interface_evidence_payload = next(
        evidence
        for evidence in swp001_payload["evidence"]
        if evidence["field_path"] == "interfaces[0].interface"
    )
    source_payload = interface_evidence_payload["sources"][0]

    assert source_payload["command_execution_id"] == str(
        switchport_execution.id
    )
    assert source_payload["raw_output_id"] == str(switchport_raw.id)
    assert source_payload["raw_sha256"] == _EXPECTED_SHA256
    assert source_payload["parser_id"] == "ios.show_interfaces_switchport.v1"
    assert source_payload["line_start"] == source.line_start
    assert source_payload["line_end"] == source.line_end

    assert (
        result.report_path.read_bytes()
        == result.rendered_report.content
    )
