# Found in Space — Dust Pipeline

Part of [Found in Space](https://foundin.space/), a project that turns real astronomical measurements into interactive explorations of the solar neighbourhood. See all repositories at [github.com/Found-in-Space](https://github.com/Found-in-Space).

This repository is the **dust pipeline**: it fetches the Rezaei Kh. et al. 2024 3D dust map from CDS and builds `dust_map.bin` — a compact float32 binary of interstellar dust density, positioned in the same heliocentric ICRS frame as the star catalogue, ready for WebGL/WebXR overlay.

**Source data:** Rezaei Kh. S. et al. (2024) — "3D structure of the Milky Way out to 10 kpc from the Sun", *Astron. Astrophys.* 692, A255.
DOI: [10.1051/0004-6361/202451424](https://doi.org/10.1051/0004-6361/202451424) ·
VizieR: [J/A+A/692/A255](https://cdsarc.cds.unistra.fr/ftp/J/A+A/692/A255)

Sibling of [Found-in-Space/pipeline](https://github.com/Found-in-Space/pipeline), sharing the `foundinspace.*` namespace, tooling (uv, Ruff, pytest), and [project-file convention](#project-files).

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

# Fetch the catalog (~400 MB)
dust-pipeline rezaei2024 fetch --project project.toml

# Build dust_map.bin
dust-pipeline rezaei2024 build --project project.toml
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

Because unknown top-level TOML sections are silently ignored by each pipeline,
a single `project.toml` can hold both the `[gaia]` / `[hip]` / `[merge]`
sections for [Found-in-Space/pipeline](https://github.com/Found-in-Space/pipeline) and the `[rezaei2024]` section for
**dust-pipeline**:

```toml
format_version = 1

# fis-pipeline sections
[gaia]
output_dir = "data/processed/gaia"

[hip]
download_ecsv = "data/catalogs/hipparcos2.ecsv"
output_parquet = "data/processed/hip_stars.parquet"

# dust-pipeline section
[rezaei2024]
catalog_gz = "data/catalogs/finalmap.dat.gz"
output_bin = "data/processed/dust_map.bin"
```

Path values may be absolute or relative to the project file's directory.
Environment-variable syntax (`$VAR`) is rejected.

---

## Output format — `dust_map.bin`

Binary layout (little-endian float32):

| Offset | Type | Description |
|--------|------|-------------|
| 0 | `float32` | Grid cell half-size in parsecs |
| 4 + i×16 | `float32` | X (ICRS pc) |
| 8 + i×16 | `float32` | Y (ICRS pc) |
| 12 + i×16 | `float32` | Z (ICRS pc) |
| 16 + i×16 | `float32` | Density (cm⁻³) |

Coordinates are **heliocentric ICRS Cartesian parsecs**, matching the star
catalogue produced by [Found-in-Space/pipeline](https://github.com/Found-in-Space/pipeline). Grid half-size is half the
median nearest-neighbour distance in the point cloud, so rendered cubes fill
the volume without gaps.

---

## Code layout

```
src/foundinspace/dust/
  __init__.py
  __main__.py         # python -m foundinspace.dust entry
  cli.py              # Click root; lazy subcommands rezaei2024, project
  project.py          # load_project, DustProject, Rezaei2024Config
  project_cli.py      # dust-pipeline project init
  rezaei2024/
    __init__.py
    cli.py            # rezaei2024 fetch, rezaei2024 build
    fetch.py          # fetch_catalog — download finalmap.dat.gz from CDS
    build.py          # build_dust_map_bin, parse_finalmap, galactic_to_icrs
```

---

## Develop

See [AGENTS.md](AGENTS.md) for `uv`, pre-commit, and CI.
