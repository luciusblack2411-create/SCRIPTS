from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from typer.testing import CliRunner

from cisco_assessment import cli
from cisco_assessment.models import AssessmentRunStatus, PlatformFamily

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class FakeRunner:
    def __init__(self) -> None:
        self.device = None
        self.credentials = None

    def run(self, *, device, credentials):
        self.device = device
        self.credentials = credentials
        return SimpleNamespace(
            run=SimpleNamespace(id=uuid4(), status=AssessmentRunStatus.COMPLETED),
            report_path=Path("/tmp/assessment.json"),
            collection=SimpleNamespace(commands=()),
        )


def test_assess_cli_uses_hidden_password_prompt(monkeypatch, tmp_path: Path) -> None:
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
    assert "supersecret" not in result.output
    assert builder_calls == [
        {
            "output_root": tmp_path,
            "port": 22,
            "strict_host_key": True,
        }
    ]


def test_assess_cli_exposes_no_password_argument() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.app, ["assess", "--help"])

    assert result.exit_code == 0, result.output
    help_output = _ANSI_ESCAPE_RE.sub("", result.output)
    assert "--password" not in help_output
    assert "--key-file" in help_output
    assert "--use-agent" in help_output
