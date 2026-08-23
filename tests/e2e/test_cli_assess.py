from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from typer.testing import CliRunner

from cisco_assessment import cli
from cisco_assessment.models import AssessmentRunStatus, PlatformFamily
from cisco_assessment.runner import (
    HARDWARE_INVENTORY_PLAN_V0_1,
    INTERFACE_STATUS_PLAN_V0_1,
    SHOW_VERSION_PLAN_V0_2,
    build_runner,
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_FIXTURES = Path(__file__).parents[1] / "fixtures" / "ios"
_VERSION = _FIXTURES / "show_version" / "c9300_iosxe.txt"
_INVENTORY = _FIXTURES / "show_inventory" / "c9300_iosxe.txt"
_PROMPT = b"SW-CORE-01#"


class FakeRunner:
    def __init__(self) -> None:
        self.device = None
        self.credentials = None
        self.plan = None

    def run(self, *, device, credentials, plan):
        self.device = device
        self.credentials = credentials
        self.plan = plan
        return SimpleNamespace(
            run=SimpleNamespace(id=uuid4(), status=AssessmentRunStatus.COMPLETED),
            report_path=Path("/tmp/assessment.json"),
            collection=SimpleNamespace(commands=()),
        )


class CliHardwareInventoryTransport:
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


def test_assess_cli_defaults_to_show_version_and_uses_hidden_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_runner = FakeRunner()
    builder_calls: list[dict[str, object]] = []

    def fake_builder(**kwargs: object) -> FakeRunner:
        builder_calls.append(dict(kwargs))
        return fake_runner

    monkeypatch.setattr(cli, "build_default_runner", fake_builder)
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "assess",
            "--host",
            "192.0.2.10",
            "--username",
            "assessment",
            "--platform",
            "ios_xe",
            "--output-dir",
            str(tmp_path),
        ],
        input="supersecret\n",
    )

    assert result.exit_code == 0, result.output
    assert fake_runner.credentials is not None
    assert fake_runner.credentials.password == "supersecret"
    assert fake_runner.credentials.key_filename is None
    assert fake_runner.device is not None
    assert fake_runner.device.platform_family == PlatformFamily.IOS_XE
    assert fake_runner.plan is SHOW_VERSION_PLAN_V0_2
    assert "supersecret" not in result.output
    assert builder_calls == [
        {
            "output_root": tmp_path,
            "port": 22,
            "strict_host_key": True,
        }
    ]


def test_assess_cli_selects_interface_status_productive_plan(monkeypatch, tmp_path: Path) -> None:
    fake_runner = FakeRunner()

    def fake_builder(**kwargs: object) -> FakeRunner:
        del kwargs
        return fake_runner

    monkeypatch.setattr(cli, "build_default_runner", fake_builder)
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "assess",
            "--host",
            "192.0.2.10",
            "--username",
            "assessment",
            "--platform",
            "ios_xe",
            "--plan",
            "interface-status",
            "--use-agent",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_runner.plan is INTERFACE_STATUS_PLAN_V0_1


def test_assess_cli_hardware_inventory_plan_runs_both_productive_commands(
    monkeypatch,
    tmp_path: Path,
) -> None:
    transport = CliHardwareInventoryTransport()

    def fake_builder(**kwargs: object):
        del kwargs
        return build_runner(output_root=tmp_path, transport_factory=lambda: transport)

    monkeypatch.setattr(cli, "build_default_runner", fake_builder)
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "assess",
            "--host",
            "192.0.2.10",
            "--username",
            "assessment",
            "--platform",
            "ios_xe",
            "--plan",
            "hardware-inventory",
            "--use-agent",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert transport.sent == [b"show version\n", b"show inventory\n"]
    assert transport.closed is True
    payload = json.loads(result.output)
    assert len(payload["raw_paths"]) == 2
    report_payload = json.loads(Path(payload["report_path"]).read_text())
    hardware_payload = report_payload["hardware_inventory"]
    assert hardware_payload["records"][0]["pid"] == "C9300-48P"
    assert "chassis" not in hardware_payload
    assert "modules" not in hardware_payload
    assert "components" not in hardware_payload
    assert HARDWARE_INVENTORY_PLAN_V0_1.command_ids[0].value == "system.version"
    assert HARDWARE_INVENTORY_PLAN_V0_1.command_ids[1].value == "system.inventory"


def test_assess_cli_rejects_unlisted_plan_before_building_runner(monkeypatch) -> None:
    builder_called = False

    def fake_builder(**kwargs: object):
        nonlocal builder_called
        builder_called = True
        raise AssertionError(kwargs)

    monkeypatch.setattr(cli, "build_default_runner", fake_builder)
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "assess",
            "--host",
            "192.0.2.10",
            "--username",
            "assessment",
            "--plan",
            "show interfaces status",
            "--use-agent",
        ],
    )

    assert result.exit_code == 2
    assert builder_called is False
    output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "show-version" in output
    assert "hardware-inventory" in output
    assert "interface-status" in output


def test_assess_cli_help_exposes_supported_plans_and_no_free_command_option() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["assess", "--help"])

    assert result.exit_code == 0, result.output
    help_output = " ".join(_ANSI_ESCAPE_RE.sub("", result.output).split())
    assert "--password" not in help_output
    assert "--key-file" in help_output
    assert "--use-agent" in help_output
    assert "--plan" in help_output
    assert "show-version" in help_output
    assert "hardware-inventory" in help_output
    assert "interface-status" in help_output
    assert "--command" not in help_output
