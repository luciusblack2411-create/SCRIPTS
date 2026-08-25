"""CLI for CONTROLLED_DRAFT_PR_AMENDMENT_V1."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from .draft_pr_amendment_control_plane import ControlledDraftPrAmendmentOperation, execute_controlled_draft_pr_amendment
from .github_ci import GitHubImplementationCiBackend, UrllibGitHubImplementationCiTransport
from .github_draft_pr_amendment import GitHubImplementationDraftPrAmendmentBackend

TOKEN_ENV = "CISCO_ASSESSMENT_DRAFT_PR_AMENDMENT_TOKEN"
app = typer.Typer(name="cisco-draft-pr-amendment-control", no_args_is_help=True)


@app.command("run")
def run(operation_file: Annotated[Path, typer.Argument(dir_okay=False)]) -> None:
    token = os.environ.get(TOKEN_ENV)
    if token is None or not token.strip():
        typer.echo(f"ERROR: {TOKEN_ENV} is required", err=True)
        raise typer.Exit(code=4)
    operation = ControlledDraftPrAmendmentOperation.model_validate_json(operation_file.read_text(encoding="utf-8"))
    transport = UrllibGitHubImplementationCiTransport(token=token)
    if not hasattr(transport, "patch_json") or not hasattr(transport, "post_json"):
        typer.echo("ERROR: configured transport lacks bounded amendment methods", err=True)
        raise typer.Exit(code=4)
    backend = GitHubImplementationDraftPrAmendmentBackend(transport=transport)  # type: ignore[arg-type]
    ci_backend = GitHubImplementationCiBackend(transport=transport)
    result = execute_controlled_draft_pr_amendment(operation, backend, ci_backend)
    typer.echo(result.model_dump_json(indent=2))
