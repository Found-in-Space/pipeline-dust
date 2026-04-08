"""CLI commands for the McCallum et al. 2025 H-alpha source."""

from __future__ import annotations

from pathlib import Path

import click


@click.group(name="mccallum2025")
def cli() -> None:
    """McCallum et al. 2025 local H-alpha / electron-density Zenodo source."""


def _load_project_or_die(project_path: Path) -> object:
    from foundinspace.dust.cli import load_project_or_die

    return load_project_or_die(project_path, "mccallum2025")


@cli.command("download")
@click.option(
    "--project",
    "project_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to pipeline project TOML.",
)
@click.option("--force", "-f", is_flag=True, default=False)
def download(project_path: Path, force: bool) -> None:
    """Download the pinned Zenodo record and write provenance lockfiles."""
    from foundinspace.dust.mccallum2025.download import download_record

    project = _load_project_or_die(project_path)
    lock_path = download_record(
        project.mccallum2025.record_id,
        project.mccallum2025.raw_dir,
        force=force,
    )
    click.echo(f"McCallum 2025 source files ready; wrote {lock_path.resolve()}")
