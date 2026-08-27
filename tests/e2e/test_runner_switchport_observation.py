from __future__ import annotations

import hashlib
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
from cisco_assessment.models import Device, PlatformFamily, SwitchportObservation
from cisco_assessment.runner import (
    ProductiveAssessmentPlanId,
    SWITCHPORT_OBSERVATION_PLAN_V0_1,
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
_PROMPT = b"LAB_SWITCH01#"
_MARKER = b"--More--"
_EXPECTED_SHA256 = "901b9a1a3aed745e4f228c0c5332bf956293078654d4f15c5f086cc051cce422"


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

    def connect(self, **kwargs: object) -> None:
        del kwargs

    def send(self, data: bytes) -> None:
        self.sent.append(data)
        if data == b"show version\n":
            self._version_pending = True
        elif data == b"show interfaces switchport\n":
            self._switchport_started = True
        elif data == b" ":
            self._continuations += 1

    def receive_ready(self) -> bool:
        if not self._opened or self._version_pending:
            return True
        if not self._switchport_started:
            return False
        if self._offset >= len(self.raw):
            return False
        if self._offset == 0:
            return True
        return self._continuations == self.raw[: self._offset].count(_MARKER)

    def receive(self, max_bytes: int = 65535) -> bytes:
        del max_bytes
        if not self._opened:
            self._opened = True
            return _PROMPT
        if self._version_pending:
            self._version_pending = False
            return b"show version\r\n" + _VERSION.read_bytes() + b"\r\n" + _PROMPT
        next_marker = self.raw.find(_MARKER, self._offset)
        end = len(self.raw) if next_marker < 0 else next_marker + len(_MARKER)
        chunk = self.raw[self._offset : end]
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
        COMMAND_CATALOG_V0_1.get(command_id).requirement for command_id in plan.command_ids
    ) == (CommandRequirement.REQUIRED, CommandRequirement.REQUIRED)


def test_switchport_productive_runner_preserves_real_paged_raw_and_evaluates_rules(
    tmp_path: Path,
) -> None:
    fixture = _SWITCHPORT.read_bytes()
    assert hashlib.sha256(fixture).hexdigest() == _EXPECTED_SHA256
    assert fixture.count(_MARKER) == 244

    transport = SwitchportPagerTransport()
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)
    result = runner.run(
        device=Device(
            management_address="192.0.2.10",
            hostname="switchport-core-01",
            platform_family=PlatformFamily.IOS_XE,
        ),
        credentials=SSHCredentials(username="assessment", password="secret"),
        plan=SWITCHPORT_OBSERVATION_PLAN_V0_1,
    )

    assert transport.sent == [
        b"show version\n",
        b"show interfaces switchport\n",
        *([b" "] * 244),
    ]
    switchport_collection = result.collection.commands[1]
    assert switchport_collection.raw_output is not None
    raw = switchport_collection.raw_output
    assert raw.content.encode(raw.encoding) == fixture
    assert raw.sha256 == _EXPECTED_SHA256

    parsed = result.switchport_observation_parse_result
    assert parsed is not None
    assert isinstance(parsed.data, SwitchportObservation)
    assert parsed.trace.parser_id is ParserId.IOS_SHOW_INTERFACES_SWITCHPORT_V1
    assert parsed.trace.normalized_model is NormalizedModelId.SWITCHPORT_OBSERVATION
    assert parsed.trace.raw_sha256 == _EXPECTED_SHA256
    assert len(parsed.data.interfaces) == 310

    outcomes = {
        outcome.rule_id: outcome
        for outcome in result.assessment_result.outcomes
        if outcome.rule_id.startswith("SWP-")
    }
    assert set(outcomes) == {"SWP-001", "SWP-002", "SWP-003", "SWP-004"}
    assert all(
        outcome.status not in {AssessmentStatus.WARNING, AssessmentStatus.FAIL}
        for outcome in outcomes.values()
    )
    assert result.report.hardware_inventory is None
    assert result.report.interface_observation is None
    assert result.report.vlan_observation is None
