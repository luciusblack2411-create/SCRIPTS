"""Operational CLI for PR review handoff and controlled Ready-for-Review."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from .github_ready_for_review import GitHubReadyForReviewError
from .pr_review.github import GitHubContextError
from .pr_review.github_rest import GitHubRestError
from .ready_for_review import ReadyForReviewDecision, ReadyForReviewError
from .ready_for_review_control_plane import (
    ReadyForReviewControlPlaneError,
    ReadyForReviewControlPlaneFileError,
    execute_ready_for_review_control_plane,
    load_ready_for_review_operation,
    render_ready_for_review_control_plane_human,
    render_ready_for_review_control_plane_json,
)


class ReadyForReviewOutputFormat(StrEnum):
    """Supported presentations for the canonical control-plane result."""

    HUMAN = "human"
    JSON = "json"


app = typer.Typer(
    name="cisco-ready-for-review-control",
    help=(
        "Run PR_REVIEW_AGENT_V1 read-only, mark an approved Draft PR Ready for Review, "
        "and stop before merge."
    ),
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keep review handoff separate from productive Cisco execution and merge."""


@app.command("run")
def run_ready_for_review_control_plane(
    operation_file: Annotated[
        Path,
        typer.Argument(
            help="Strict JSON containing ReviewRequest and READY_FOR_REVIEW authorization.",
            dir_okay=False,
        ),
    ],
    output: Annotated[
        ReadyForReviewOutputFormat,
        typer.Option("--output", "-o", help="Render human summary or canonical JSON."),
    ] = ReadyForReviewOutputFormat.HUMAN,
) -> None:
    """Run fresh review, transition only on APPROVE, and stop before merge."""
    try:
        operation = load_ready_for_review_operation(operation_file)
        result = execute_ready_for_review_control_plane(operation)
    except (
        ReadyForReviewControlPlaneFileError,
        ReadyForReviewControlPlaneError,
        ReadyForReviewError,
        GitHubReadyForReviewError,
        GitHubContextError,
        GitHubRestError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    rendered = (
        render_ready_for_review_control_plane_json(result)
        if output is ReadyForReviewOutputFormat.JSON
        else render_ready_for_review_control_plane_human(result)
    )
    typer.echo(rendered)

    exit_code = ready_for_review_exit_code(result.ready_for_review.decision)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def ready_for_review_exit_code(decision: ReadyForReviewDecision) -> int:
    """Map gate decisions to automation-friendly process exit codes."""
    return {
        ReadyForReviewDecision.READY_FOR_REVIEW: 0,
        ReadyForReviewDecision.NEEDS_BASE_REFRESH: 2,
        ReadyForReviewDecision.REVIEW_NOT_APPROVED: 3,
    }[decision]
