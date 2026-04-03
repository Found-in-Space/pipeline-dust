"""CLI commands for the Rezaei et al. 2024 dust map source."""

from __future__ import annotations

from pathlib import Path

import click


@click.group(name="rezaei2024")
def cli() -> None:
    """Rezaei Kh. et al. 2024 APOGEE dust map (A&A 692, A255)."""


def _load_project_or_die(project_path: Path) -> object:
    from foundinspace.dust.cli import load_project_or_die

    return load_project_or_die(project_path, "rezaei2024")


@cli.command("fetch")
@click.option(
    "--project",
    "project_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to pipeline project TOML.",
)
@click.option("--force", "-f", is_flag=True, default=False)
def fetch(project_path: Path, force: bool) -> None:
    """Download finalmap.dat.gz from CDS."""
    from foundinspace.dust.rezaei2024.fetch import fetch_catalog

    project = _load_project_or_die(project_path)
    out = fetch_catalog(project.rezaei2024.catalog_gz, force=force)
    click.echo(f"Catalog ready at {out.resolve()}")


@cli.command("build")
@click.option(
    "--project",
    "project_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to pipeline project TOML.",
)
@click.option("--force", "-f", is_flag=True, default=False)
def build(project_path: Path, force: bool) -> None:
    """Build dust_map_ng.bin from finalmap.dat.gz."""
    from foundinspace.dust.rezaei2024.build import build_dust_map_bin

    project = _load_project_or_die(project_path)
    out = build_dust_map_bin(
        project.rezaei2024.catalog_gz,
        project.rezaei2024.output_bin,
        force=force,
    )
    click.echo(f"Wrote {out.resolve()}")
