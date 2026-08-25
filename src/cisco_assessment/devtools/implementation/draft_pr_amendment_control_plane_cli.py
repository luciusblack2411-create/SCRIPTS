"""CLI for controlled Draft PR amendment."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from .draft_pr_amendment import ImplementationDraftPrAmendmentError
from .draft_pr_amendment_control_plane import (
    ImplementationDraftPrAmendmentControlPlaneError,
    ImplementationDraftPrAmendmentControlPlaneOperation,
    execute_draft_pr_amendment_control_plane,
)

app = typer.Typer(
    name="cisco-draft-pr-amendment-control",
    help="Amend one exact open Draft PR, require exact-head CI, and stop.",
    no_args_is_help=True,
)


@app.command("run")
def run_draft_pr_amendment_control_plane(
    operation_file: Annotated[
        Path,
        typer.Argument(
            help="Strict CONTROLLED_DRAFT_PR_AMENDMENT_V1 JSON operation.",
            dir_okay=False,
        ),
    ],
) -> None:
    """Amend one exact Draft PR and print canonical non-secret evidence."""
    try:
        content = operation_file.read_text(encoding="utf-8")
        operation = ImplementationDraftPrAmendmentControlPlaneOperation.model_validate_json(
            content
        )
        result = execute_draft_pr_amendment_control_plane(operation)
    except (
        OSError,
        UnicodeError,
        ValidationError,
        ImplementationDraftPrAmendmentError,
        ImplementationDraftPrAmendmentControlPlaneError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(result.model_dump_json(indent=2))
