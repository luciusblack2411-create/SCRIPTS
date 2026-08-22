"""Command-line entry point for the assessment framework."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import Device, PlatformFamily
from cisco_assessment.runner import AssessmentRunnerError, build_default_runner

app = typer.Typer(help="Cisco Switch Assessment Framework")


def _parse_platform(value: str) -> PlatformFamily:
    normalized = value.strip().lower().replace("-", "_")
    if normalized == PlatformFamily.IOS.value:
        return PlatformFamily.IOS
    if normalized == PlatformFamily.IOS_XE.value:
        return PlatformFamily.IOS_XE
    raise typer.BadParameter(
        "Runner v0.1 supports only 'ios' and 'ios_xe'.",
        param_hint="--platform",
    )


@app.callback()
def main() -> None:
    """Cisco Switch Assessment Framework."""


@app.command()
def version() -> None:
    """Print the framework version."""
    from cisco_assessment import __version__

    typer.echo(__version__)


@app.command("assess")
def assess(
    host: str = typer.Option(..., "--host", help="Switch management address or resolvable name."),
    username: str = typer.Option(..., "--username", "-u", help="SSH username."),
    platform: str = typer.Option(
        "ios_xe",
        "--platform",
        help="Target platform: ios or ios_xe.",
    ),
    port: int = typer.Option(22, "--port", min=1, max=65535, help="SSH port."),
    key_file: Path | None = typer.Option(
        None,
        "--key-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="SSH private-key file. When supplied, no password prompt is shown.",
    ),
    use_agent: bool = typer.Option(
        False,
        "--use-agent",
        help="Use SSH agent/default keys instead of prompting for a password.",
    ),
    output_dir: Path = typer.Option(
        Path("assessment-output"),
        "--output-dir",
        file_okay=False,
        help="Directory where RAW evidence and the JSON report are persisted.",
    ),
    accept_unknown_host_key: bool = typer.Option(
        False,
        "--accept-unknown-host-key",
        help="Allow an unknown SSH host key for this run. Strict checking is the default.",
    ),
) -> None:
    """Assess one IOS/IOS-XE switch using only the show version vertical slice."""
    if not host.strip():
        raise typer.BadParameter("host must not be blank", param_hint="--host")
    if not username.strip():
        raise typer.BadParameter("username must not be blank", param_hint="--username")
    if key_file is not None and use_agent:
        raise typer.BadParameter(
            "choose either --key-file or --use-agent, not both",
            param_hint="--key-file/--use-agent",
        )

    platform_family = _parse_platform(platform)
    password: str | None = None
    if key_file is None and not use_agent:
        password = typer.prompt("SSH password", hide_input=True)

    credentials = SSHCredentials(
        username=username,
        password=password,
        key_filename=str(key_file) if key_file is not None else None,
    )
    device = Device(
        management_address=host,
        platform_family=platform_family,
    )
    runner = build_default_runner(
        output_root=output_dir,
        port=port,
        strict_host_key=not accept_unknown_host_key,
    )

    try:
        result = runner.run(device=device, credentials=credentials)
    except AssessmentRunnerError as exc:
        payload = {
            "status": exc.run.status.value,
            "assessment_run_id": str(exc.run.id),
            "error": exc.failure.as_dict(),
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True), err=True)
        raise typer.Exit(code=1) from exc

    raw_paths = [
        str(item.raw_path)
        for item in result.collection.commands
        if item.raw_path is not None
    ]
    payload = {
        "status": result.run.status.value,
        "assessment_run_id": str(result.run.id),
        "report_path": str(result.report_path),
        "raw_paths": raw_paths,
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
