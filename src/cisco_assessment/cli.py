"""Command-line entry point for the assessment framework."""

import typer

app = typer.Typer(help="Cisco Switch Assessment Framework")


@app.callback()
def main() -> None:
    """Cisco Switch Assessment Framework."""


@app.command()
def version() -> None:
    """Print the framework version."""
    from cisco_assessment import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
