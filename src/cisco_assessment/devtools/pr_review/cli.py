"""Separate operational CLI for the advisory PR Review Agent."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from .enums import ReviewDecision
from .github import GitHubContextError
from .github_rest import GitHubRestError
from .operational import (
    ReviewRequestFileError,
    execute_review_request,
    load_review_request,
    render_review_report_human,
    render_review_report_json,
)


class ReviewOutputFormat(StrEnum):
    """Supported operational presentations for the canonical ReviewReport."""

    HUMAN = "human"
    JSON = "json"


app = typer.Typer(
    name="cisco-pr-review",
    help=(
        "Run PR_REVIEW_AGENT_V1 in advisory/read-only mode from an explicit JSON ReviewRequest."
    ),
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Expose explicit devtools subcommands without changing the productive Cisco CLI."""


@app.command("run")
def run_review(
    request_file: Annotated[
        Path,
        typer.Argument(
            help="Path to a strict ReviewRequest JSON file containing approved review scope.",
            dir_okay=False,
        ),
    ],
    output: Annotated[
        ReviewOutputFormat,
        typer.Option("--output", "-o", help="Render human summary or canonical JSON."),
    ] = ReviewOutputFormat.HUMAN,
) -> None:
    """Review one PR without mutating GitHub, source branches, Cisco devices, or Cisco CLI."""
    try:
        request = load_review_request(request_file)
        report = execute_review_request(request)
    except (ReviewRequestFileError, GitHubContextError, GitHubRestError) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    rendered = (
        render_review_report_json(report)
        if output is ReviewOutputFormat.JSON
        else render_review_report_human(report)
    )
    typer.echo(rendered)

    exit_code = review_decision_exit_code(report.decision)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def review_decision_exit_code(decision: ReviewDecision) -> int:
    """Map deterministic advisory decisions to automation-friendly process exit codes."""
    return {
        ReviewDecision.APPROVE: 0,
        ReviewDecision.NEEDS_HUMAN_REVIEW: 2,
        ReviewDecision.REQUEST_CHANGES: 3,
        ReviewDecision.BLOCKED: 4,
    }[decision]
