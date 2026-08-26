"""CLI for the dedicated Draft PR Amendment control plane."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .draft_pr_amendment import ImplementationDraftPrAmendmentError
from .draft_pr_amendment_control_plane import (
    ImplementationDraftPrAmendmentControlPlaneError,
    execute_amendment_control_plane,
    load_amendment_operation,
)

app = typer.Typer(
    name="cisco-draft-pr-amendment-control",
    help="Amend one exact existing same-repository Draft PR and validate fresh exact-head CI.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Keep existing-ref amendment authority separate from create-only mutation."""


@app.command("run")
def run_amendment(
    operation_file: Annotated[Path, typer.Argument(dir_okay=False)],
) -> None:
    try:
        operation = load_amendment_operation(operation_file)
        result = execute_amendment_control_plane(operation)
    except (
        ImplementationDraftPrAmendmentControlPlaneError,
        ImplementationDraftPrAmendmentError,
    ) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(result.model_dump_json(indent=2))
