# Found in Space — Dust Pipeline

Part of [Found in Space](https://foundin.space/), a project that turns real astronomical measurements into interactive explorations of the solar neighbourhood. Source code and companion repositories live in the [Found-in-Space](https://github.com/Found-in-Space) GitHub organization.

This repository is the **dust pipeline**: it fetches the Rezaei Kh. et al. 2024 3D dust map from CDS and builds `dust_map_ng.bin` — a compact Galactic voxel texture of interstellar dust density for WebGL/WebXR overlay. It also contains the early McCallum et al. 2025 H-alpha source-data acquisition steps used for the upcoming local emissivity volume pipeline.

**Source data:** Rezaei Kh. S. et al. (2024) — "3D structure of the Milky Way out to 10 kpc from the Sun", *Astron. Astrophys.* 692, A255.
DOI: [10.1051/0004-6361/202451424](https://doi.org/10.1051/0004-6361/202451424) ·
VizieR: [J/A+A/692/A255](https://cdsarc.cds.unistra.fr/ftp/J/A+A/692/A255)

This package shares the `foundinspace` namespace layout with other repositories in the organization, uses uv, Ruff, and pytest, and follows the [project-file convention](#project-files).

---

## Install

```bash
uv sync --all-groups
```

## CLI

```bash
dust-pipeline --help

# Generate a starter project file
dust-pipeline project init project.toml

# Download the catalog (~400 MB)
dust-pipeline rezaei2024 download --project project.toml

# Build dust_map_ng.bin
dust-pipeline rezaei2024 build --project project.toml

# Download McCallum et al. 2025 H-alpha FITS sources from Zenodo
dust-pipeline mccallum2025 download --project project.toml
```

Or as a module:

```bash
uv run python -m foundinspace.dust --help
```

---

## Project files

All commands require `--project path/to/project.toml`. The project file is the
single source of truth for catalog/output paths. Generate a starter file with
`dust-pipeline project init project.toml`.

Unknown top-level tables that **dust-pipeline** does not read are ignored, so
the same `project.toml` can also contain sections for
[Found-in-Space/pipeline](https://github.com/Found-in-Space/pipeline) (for example `[gaia]`, `[hip]`). Keys and semantics
for those tables belong in that repository’s docs — this project only loads
`[rezaei2024]` and `[mccallum2025]`.

```toml
format_version = 1

[rezaei2024]
catalog_gz = "data/catalogs/finalmap.dat.gz"
output_bin = "data/processed/dust_map_ng.bin"

[mccallum2025]
record_id = "15041318"
raw_dir = "data/raw/zenodo/mccallum_2025"
```

Path values may be absolute or relative to the project file's directory.
Environment-variable syntax (`$VAR`) is rejected.

---

## Artifacts

The build step produces **`dust_map_ng.bin`**: a shader-facing Galactic voxel
texture derived from the published catalog (`finalmap.dat.gz`).

The McCallum download step downloads the pinned Zenodo record into `raw_dir` and writes:

- `record.json`: the Zenodo record API response
- `files.lock.json`: downloaded file names, source URLs, checksums, DOI metadata, and download time

Downloaded files are skipped when already present and checksum-valid. Use `--force` to refresh them.

## Output format — `dust_map_ng.bin`

Header (48 bytes), followed by `NX * NY * NZ` bytes of density samples:

| Byte range | Type | Description |
|------------|------|-------------|
| 0-3 | `uint32` | `NX` |
| 4-7 | `uint32` | `NY` |
| 8-11 | `uint32` | `NZ` |
| 12-15 | `float32` | `max_density` (cm⁻³, mapped to uint8 255) |
| 16-19 | `float32` | `min_x` (Galactic pc) |
| 20-23 | `float32` | `max_x` (Galactic pc) |
| 24-27 | `float32` | `min_y` (Galactic pc) |
| 28-31 | `float32` | `max_y` (Galactic pc) |
| 32-35 | `float32` | `min_z` (Galactic pc) |
| 36-39 | `float32` | `max_z` (Galactic pc) |
| 40-47 | reserved | zeros |

Data layout:

- `uint8 density[iz, iy, ix]`
- Galactic Cartesian, heliocentric
- `x` varies fastest
- X/Y use 100 pc spacing
- Z uses the five published layers at `-750, -375, 0, +375, +750 pc`

The voxel texture is intentionally Galactic-native. Viewer code is responsible
for mapping Galactic sample space into whatever world or sky orientation it
needs.

---

## Code layout

```
src/foundinspace/dust/
  __init__.py
  __main__.py         # python -m foundinspace.dust entry
  cli.py              # Click root; lazy subcommands rezaei2024, mccallum2025, project
  project.py          # load_project, DustProject, Rezaei2024Config
  project_cli.py      # dust-pipeline project init
  rezaei2024/
    cli.py            # rezaei2024 download, rezaei2024 build
    download.py       # download_catalog — download finalmap.dat.gz from CDS
    build.py          # build_dust_map_bin, parse_finalmap_raw
```

---

## Develop

See [AGENTS.md](AGENTS.md) for `uv`, pre-commit, and CI.
