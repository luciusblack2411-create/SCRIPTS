from typer.testing import CliRunner

from cisco_assessment import __version__
from cisco_assessment.cli import app

runner = CliRunner()


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"
