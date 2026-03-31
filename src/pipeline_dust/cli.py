"""CLI entry point for pipeline-dust."""

from __future__ import annotations

import click


@click.group()
@click.version_option()
def cli() -> None:
    """Dust map pipeline: fetch and build steps (see README)."""


@cli.command("hello")
def hello() -> None:
    """Sanity check that the CLI is installed."""
    click.echo("Hello from pipeline-dust")


if __name__ == "__main__":
    cli()
