"""CLI commands for managing dust pipeline project files."""

from __future__ import annotations

from pathlib import Path

import click

from foundinspace.dust.project import render_project_template


@click.group(name="project")
def cli() -> None:
    """Manage dust pipeline project files."""


@cli.command("init")
@click.argument("project_path", type=click.Path(path_type=Path))
def project_init(project_path: Path) -> None:
    """Write a starter project.toml for dust-pipeline commands."""
    project_path = project_path.expanduser()
    if project_path.exists():
        raise click.ClickException(f"Project file already exists: {project_path}")
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text(render_project_template(), encoding="utf-8")
    click.echo(f"Wrote project file to {project_path.resolve()}")
