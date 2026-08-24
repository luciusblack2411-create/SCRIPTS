"""Command-line entry point for the assessment framework."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cisco_assessment.collector.transport import SSHCredentials
from cisco_assessment.models import Device, PlatformFamily
from cisco_assessment.runner import (
    AssessmentRunnerError,
    ProductiveAssessmentPlanId,
    build_default_runner,
    resolve_productive_assessment_plan,
)

app = typer.Typer(help="Cisco Switch Assessment Framework")

_KEY_FILE_OPTION = typer.Option(
    None,
    "--key-file",
    exists=True,
    file_okay=True,
    dir_okay=False,
    readable=True,
    help="SSH private-key file. When supplied, no password prompt is shown.",
)
_OUTPUT_DIR_OPTION = typer.Option(
    Path("assessment-output"),
    "--output-dir",
    file_okay=False,
    help="Directory where RAW evidence and the JSON report are persisted.",
)
_PLAN_OPTION = typer.Option(
    ProductiveAssessmentPlanId.SHOW_VERSION,
    "--plan",
    help=(
        "Productive assessment plan. show-version (default): show version only; "
        "hardware-inventory: show version + show inventory; "
        "interface-status: show version + show interfaces status; "
        "vlan-observation: show version + show vlan brief."
    ),
)


def _parse_platform(value: str) -> PlatformFamily:
    normalized = value.strip().lower().replace("-", "_")
    if normalized == PlatformFamily.IOS.value:
        return PlatformFamily.IOS
    if normalized == PlatformFamily.IOS_XE.value:
        return PlatformFamily.IOS_XE
    raise typer.BadParameter(
        "Runner supports only 'ios' and 'ios_xe'.",
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
    plan: ProductiveAssessmentPlanId = _PLAN_OPTION,
    port: int = typer.Option(22, "--port", min=1, max=65535, help="SSH port."),
    key_file: Path | None = _KEY_FILE_OPTION,
    use_agent: bool = typer.Option(
        False,
        "--use-agent",
        help="Use SSH agent/default keys instead of prompting for a password.",
    ),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    accept_unknown_host_key: bool = typer.Option(
        False,
        "--accept-unknown-host-key",
        help="Allow an unknown SSH host key for this run. Strict checking is the default.",
    ),
) -> None:
    """Assess one IOS/IOS-XE switch using a supported productive assessment plan."""
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
    assessment_plan = resolve_productive_assessment_plan(plan)
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
        result = runner.run(
            device=device,
            credentials=credentials,
            plan=assessment_plan,
        )
    except AssessmentRunnerError as exc:
        failure_payload: dict[str, object] = {
            "status": exc.run.status.value,
            "assessment_run_id": str(exc.run.id),
            "error": exc.failure.as_dict(),
        }
        typer.echo(json.dumps(failure_payload, indent=2, sort_keys=True), err=True)
        raise typer.Exit(code=1) from exc

    raw_paths = [
        str(item.raw_path)
        for item in result.collection.commands
        if item.raw_path is not None
    ]
    success_payload: dict[str, object] = {
        "status": result.run.status.value,
        "assessment_run_id": str(result.run.id),
        "report_path": str(result.report_path),
        "raw_paths": raw_paths,
    }
    typer.echo(json.dumps(success_payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
