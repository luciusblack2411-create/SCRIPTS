"""CLI for the dedicated Draft PR amendment control plane."""
from pathlib import Path
from typing import Annotated

import typer

from .draft_pr_amendment import ImplementationDraftPrAmendmentError
from .draft_pr_amendment_control_plane import (
    ImplementationDraftPrAmendmentControlPlaneError,
    execute_amendment_control_plane,
    load_amendment_operation,
)

app = typer.Typer(name="cisco-draft-pr-amendment-control", no_args_is_help=True)


@app.command("run")
def run(operation_file: Annotated[Path, typer.Argument(dir_okay=False)]) -> None:
    try:
        result = execute_amendment_control_plane(load_amendment_operation(operation_file))
    except (ImplementationDraftPrAmendmentControlPlaneError, ImplementationDraftPrAmendmentError) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=4) from exc
    typer.echo(result.model_dump_json(indent=2))
