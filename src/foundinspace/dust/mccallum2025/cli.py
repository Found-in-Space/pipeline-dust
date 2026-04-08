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


@cli.command("build-tiled-volume")
@click.option(
    "--project",
    "project_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to pipeline project TOML.",
)
@click.option(
    "--out-dir",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override output fixed-grid tiled volume directory.",
)
@click.option("--force", "-f", is_flag=True, default=False)
@click.option(
    "--tile-grid-size",
    type=int,
    default=4,
    show_default=True,
    help="Number of equal world-space tiles per axis for every level.",
)
@click.option(
    "--levels",
    "level_count",
    type=int,
    default=4,
    show_default=True,
    help="Number of pooled 2x downsample levels to write after l0.",
)
@click.option(
    "--tile-halo-cells",
    type=int,
    default=1,
    show_default=True,
    help="Neighbor voxels to include around every tile payload for linear filtering.",
)
@click.option(
    "--compresslevel",
    type=int,
    default=9,
    show_default=True,
    help="gzip compression level for each tile payload.",
)
def build_tiled_volume(
    project_path: Path,
    output_dir: Path | None,
    force: bool,
    tile_grid_size: int,
    level_count: int,
    tile_halo_cells: int,
    compresslevel: int,
) -> None:
    """Build fixed-grid H-alpha tiles for single-texture runtime refinement."""
    from foundinspace.dust.mccallum2025.tiled import (
        DEFAULT_SOURCE_FILENAME,
        build_ha_tiled_volume,
        default_tiled_volume_output_dir,
    )

    project = _load_project_or_die(project_path)
    manifest = build_ha_tiled_volume(
        project.mccallum2025.raw_dir / DEFAULT_SOURCE_FILENAME,
        output_dir or default_tiled_volume_output_dir(project.project_path),
        force=force,
        tile_grid_size=tile_grid_size,
        level_count=level_count,
        tile_halo_cells=tile_halo_cells,
        compresslevel=compresslevel,
    )
    click.echo(f"H-alpha fixed-grid tiled volume ready at {manifest.resolve()}")
