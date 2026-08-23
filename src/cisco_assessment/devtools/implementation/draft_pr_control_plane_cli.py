"""Operational CLI for the separate Draft PR control plane."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from .draft_pr import ImplementationDraftPrDecision, ImplementationDraftPrError
from .draft_pr_control_plane import (
    ImplementationDraftPrControlPlaneError,
    ImplementationDraftPrControlPlaneFileError,
    execute_draft_pr_control_plane,
    load_draft_pr_control_plane_operation,
    render_draft_pr_control_plane_result_human,
    render_draft_pr_control_plane_result_json,
)
from .github_draft_pr import ImplementationGitHubDraftPrError


class DraftPrControlPlaneOutputFormat(StrEnum):
    """Supported presentations for the canonical control-plane result."""

    HUMAN = "human"
    JSON = "json"


app = typer.Typer(
    name="cisco-draft-pr-control",
    help=(
        "Create one verified Implementation Agent Draft PR using the dedicated "
        "control-plane credential and stop before review or merge."
    ),
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keep Draft PR creation separate from work-branch mutation and productive Cisco CLI."""


@app.command("run")
def run_draft_pr_control_plane(
    operation_file: Annotated[
        Path,
        typer.Argument(
            help="Strict JSON containing READY_FOR_DRAFT_PR evidence and DRAFT_PR authorization.",
            dir_okay=False,
        ),
    ],
    output: Annotated[
        DraftPrControlPlaneOutputFormat,
        typer.Option("--output", "-o", help="Render human summary or canonical JSON."),
    ] = DraftPrControlPlaneOutputFormat.HUMAN,
) -> None:
    """Create exactly one Draft PR and stop before Ready for Review, review, or merge."""
    try:
        operation = load_draft_pr_control_plane_operation(operation_file)
        result = execute_draft_pr_control_plane(operation)
    except (
        ImplementationDraftPrControlPlaneFileError,
        ImplementationDraftPrControlPlaneError,
        ImplementationDraftPrError,
        ImplementationGitHubDraftPrError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    rendered = (
        render_draft_pr_control_plane_result_json(result)
        if output is DraftPrControlPlaneOutputFormat.JSON
        else render_draft_pr_control_plane_result_human(result)
    )
    typer.echo(rendered)

    exit_code = draft_pr_control_plane_exit_code(result.draft_pr.decision)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def draft_pr_control_plane_exit_code(decision: ImplementationDraftPrDecision) -> int:
    """Map Draft PR decisions to automation-friendly process exit codes."""
    return {
        ImplementationDraftPrDecision.DRAFT_PR_CREATED: 0,
        ImplementationDraftPrDecision.NEEDS_BASE_REFRESH: 2,
    }[decision]
