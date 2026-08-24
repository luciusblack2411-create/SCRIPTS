"""Separate operational CLI for controlled Implementation Agent work-branch execution."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from .ci_validation import ImplementationCiValidationError, ImplementationOperationalDecision
from .github_ci import ImplementationGitHubCiError
from .github_mutation import ImplementationGitHubMutationError
from .mutation import ImplementationMutationError
from .operational import (
    ImplementationOperationFileError,
    execute_implementation_operation,
    load_implementation_operation,
    render_implementation_result_human,
    render_implementation_result_json,
)


class ImplementationOutputFormat(StrEnum):
    """Supported presentations for the canonical operational implementation result."""

    HUMAN = "human"
    JSON = "json"


app = typer.Typer(
    name="cisco-implementation",
    help=(
        "Run IMPLEMENTATION_AGENT_V1 work-branch mutation and CI validation from an explicit "
        "approved operation file."
    ),
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Expose devtools implementation operations separately from the productive Cisco CLI."""


@app.command("run")
def run_implementation(
    operation_file: Annotated[
        Path,
        typer.Argument(
            help="Strict JSON operation containing approved request, workspace, and work branch.",
            dir_okay=False,
        ),
    ],
    output: Annotated[
        ImplementationOutputFormat,
        typer.Option("--output", "-o", help="Render human summary or canonical JSON."),
    ] = ImplementationOutputFormat.HUMAN,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0, help="Maximum time to wait for exact CI."),
    ] = 900.0,
    poll_interval_seconds: Annotated[
        float,
        typer.Option("--poll-seconds", min=0.1, help="CI polling interval."),
    ] = 5.0,
) -> None:
    """Publish a dedicated work branch, validate CI, and stop before draft PR or merge."""
    try:
        operation = load_implementation_operation(operation_file)
        result = execute_implementation_operation(
            operation,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    except (
        ImplementationOperationFileError,
        ImplementationMutationError,
        ImplementationGitHubMutationError,
        ImplementationCiValidationError,
        ImplementationGitHubCiError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    rendered = (
        render_implementation_result_json(result)
        if output is ImplementationOutputFormat.JSON
        else render_implementation_result_human(result)
    )
    typer.echo(rendered)

    exit_code = implementation_decision_exit_code(result.decision)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def implementation_decision_exit_code(decision: ImplementationOperationalDecision) -> int:
    """Map deterministic operational decisions to automation-friendly process exit codes."""
    return {
        ImplementationOperationalDecision.READY_FOR_DRAFT_PR: 0,
        ImplementationOperationalDecision.NEEDS_BASE_REFRESH: 2,
        ImplementationOperationalDecision.CI_FAILED: 3,
        ImplementationOperationalDecision.CI_TIMEOUT: 4,
    }[decision]
