"""CLI for the controlled Return-to-Draft operation."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from .github_return_to_draft import GitHubReturnToDraftError
from .pr_review.github_rest import GitHubRestError
from .return_to_draft import ReturnToDraftDecision, ReturnToDraftError
from .return_to_draft_control_plane import (
    ReturnToDraftControlPlaneError,
    ReturnToDraftControlPlaneFileError,
    execute_return_to_draft_control_plane,
    load_return_to_draft_operation,
    render_return_to_draft_control_plane_human,
    render_return_to_draft_control_plane_json,
)


class ReturnToDraftOutputFormat(StrEnum):
    HUMAN = "human"
    JSON = "json"


app = typer.Typer(
    name="cisco-return-to-draft-control",
    help="Perform one explicitly authorized Ready-for-Review to Draft transition.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keep Return-to-Draft separate from review, amendment, merge, and Cisco execution."""


@app.command("run")
def run_return_to_draft_control_plane(
    operation_file: Annotated[Path, typer.Argument(dir_okay=False)],
    output: Annotated[
        ReturnToDraftOutputFormat, typer.Option("--output", "-o")
    ] = ReturnToDraftOutputFormat.HUMAN,
) -> None:
    try:
        operation = load_return_to_draft_operation(operation_file)
        result = execute_return_to_draft_control_plane(operation)
    except (
        ReturnToDraftControlPlaneFileError,
        ReturnToDraftControlPlaneError,
        ReturnToDraftError,
        GitHubReturnToDraftError,
        GitHubRestError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(
        render_return_to_draft_control_plane_json(result)
        if output is ReturnToDraftOutputFormat.JSON
        else render_return_to_draft_control_plane_human(result)
    )
    if result.return_to_draft.decision is ReturnToDraftDecision.NEEDS_REF_REFRESH:
        raise typer.Exit(code=2)
