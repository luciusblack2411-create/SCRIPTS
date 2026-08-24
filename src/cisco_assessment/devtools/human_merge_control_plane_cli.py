"""Operational CLI for the explicit human-authorized merge gate."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from .github_human_merge import GitHubHumanMergeError
from .human_merge_control_plane import (
    HumanMergeControlPlaneError,
    HumanMergeControlPlaneFileError,
    execute_human_merge_control_plane,
    load_human_merge_operation,
    render_human_merge_control_plane_human,
    render_human_merge_control_plane_json,
)
from .human_merge_gate import HumanMergeDecision, HumanMergeError
from .pr_review.github import GitHubContextError
from .pr_review.github_rest import GitHubRestError


class HumanMergeOutputFormat(StrEnum):
    """Supported presentations for the canonical control-plane result."""

    HUMAN = "human"
    JSON = "json"


app = typer.Typer(
    name="cisco-human-merge-control",
    help=(
        "Run PR_REVIEW_AGENT_V1 read-only, require an exact human MERGE_APPROVED "
        "authorization, merge once, verify main, and stop."
    ),
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keep explicit human merge separate from productive Cisco execution."""


@app.command("run")
def run_human_merge_control_plane(
    operation_file: Annotated[
        Path,
        typer.Argument(
            help="Strict JSON containing ReviewRequest and exact human MERGE_APPROVED authorization.",
            dir_okay=False,
        ),
    ],
    output: Annotated[
        HumanMergeOutputFormat,
        typer.Option("--output", "-o", help="Render human summary or canonical JSON."),
    ] = HumanMergeOutputFormat.HUMAN,
) -> None:
    """Run fresh review, verify human authorization, merge once, and stop."""
    try:
        operation = load_human_merge_operation(operation_file)
        result = execute_human_merge_control_plane(operation)
    except (
        HumanMergeControlPlaneFileError,
        HumanMergeControlPlaneError,
        HumanMergeError,
        GitHubHumanMergeError,
        GitHubContextError,
        GitHubRestError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    rendered = (
        render_human_merge_control_plane_json(result)
        if output is HumanMergeOutputFormat.JSON
        else render_human_merge_control_plane_human(result)
    )
    typer.echo(rendered)

    exit_code = human_merge_exit_code(result.human_merge.decision)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def human_merge_exit_code(decision: HumanMergeDecision) -> int:
    """Map gate decisions to automation-friendly process exit codes."""
    return {
        HumanMergeDecision.MERGED: 0,
        HumanMergeDecision.NEEDS_BASE_REFRESH: 2,
        HumanMergeDecision.REVIEW_NOT_APPROVED: 3,
    }[decision]
