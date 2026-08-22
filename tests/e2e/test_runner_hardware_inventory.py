from __future__ import annotations

import json
from pathlib import Path

from cisco_assessment.catalog import CommandId, NormalizedModelId
from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import (
    AssessmentRunStatus,
    CommandExecutionStatus,
    Device,
    PlatformFamily,
)
from cisco_assessment.runner import HARDWARE_INVENTORY_PLAN_V0_1, build_runner

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ios"
_VERSION = _FIXTURES / "show_version" / "c9300_iosxe.txt"
_INVENTORY = _FIXTURES / "show_inventory" / "c9300_iosxe.txt"
_PROMPT = b"SW-CORE-01#"


class HardwareInventoryTransport:
    def __init__(self) -> None:
        self._chunks = [
            _PROMPT,
            b"show version\r\n" + _VERSION.read_bytes() + b"\r\n" + _PROMPT,
            b"show inventory\r\n" + _INVENTORY.read_bytes() + b"\r\n" + _PROMPT,
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


def test_hardware_inventory_vertical_slice_preserves_independent_raw_and_report_trace(
    tmp_path: Path,
) -> None:
    transport = HardwareInventoryTransport()
    runner = build_runner(output_root=tmp_path, transport_factory=lambda: transport)
    device = Device(
        management_address="192.0.2.10",
        hostname="inventory-core-01",
        platform_family=PlatformFamily.IOS_XE,
    )

    result = runner.run(
        device=device,
        credentials=SSHCredentials(username="assessment", password="secret"),
        plan=HARDWARE_INVENTORY_PLAN_V0_1,
    )

    assert result.run.status is AssessmentRunStatus.COMPLETED
    assert result.plan.command_ids == (CommandId.SYSTEM_VERSION, CommandId.SYSTEM_INVENTORY)
    assert transport.sent == [b"show version\n", b"show inventory\n"]
    assert transport.closed is True

    assert len(result.command_executions) == 2
    assert len(result.raw_outputs) == 2
    version_execution, inventory_execution = result.command_executions
    version_raw, inventory_raw = result.raw_outputs
    assert [version_execution.sequence, inventory_execution.sequence] == [1, 2]
    assert version_execution.status is CommandExecutionStatus.SUCCESS
    assert inventory_execution.status is CommandExecutionStatus.SUCCESS
    assert version_execution.id != inventory_execution.id
    assert version_raw.id != inventory_raw.id
    assert version_raw.command_execution_id == version_execution.id
    assert inventory_raw.command_execution_id == inventory_execution.id

    hardware_parse = result.hardware_inventory_parse_result
    assert hardware_parse is not None
    assert hardware_parse.trace.normalized_model is NormalizedModelId.HARDWARE_INVENTORY
    assert hardware_parse.trace.command_execution_id == inventory_execution.id
    assert hardware_parse.trace.raw_output_id == inventory_raw.id
    assert hardware_parse.trace.raw_sha256 == inventory_raw.sha256
    assert hardware_parse.data.chassis is not None
    assert hardware_parse.data.chassis.pid == "C9300-48P"

    rule_ids = {outcome.rule_id for outcome in result.assessment_result.outcomes}
    assert {"HW-001", "HW-002", "HW-003"}.issubset(rule_ids)
    assert result.report.hardware_inventory is not None
    assert result.report.hardware_inventory.chassis is not None
    assert result.report.hardware_inventory.chassis.serial_number == "FOC0000AAAA"

    payload = json.loads(result.rendered_report.content)
    assert payload["hardware_inventory"]["chassis"]["pid"] == "C9300-48P"
    hw001 = next(item for item in payload["outcomes"] if item["rule"]["rule_id"] == "HW-001")
    serial_evidence = next(
        item for item in hw001["evidence"] if item["field_path"] == "chassis.serial_number"
    )
    source = serial_evidence["sources"][0]
    assert source["command_execution_id"] == str(inventory_execution.id)
    assert source["raw_output_id"] == str(inventory_raw.id)
    assert source["raw_sha256"] == inventory_raw.sha256
    assert source["parser_id"] == "ios.show_inventory.v1"
    assert result.report_path.read_bytes() == result.rendered_report.content
