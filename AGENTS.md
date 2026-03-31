# Agent Instructions

## Python Tooling: Use `uv`

- Use `uv` for all Python dependency and environment operations in this repository.
- Do not use `pip`, `poetry`, or `conda` commands directly.

### Standard commands

- Sync/install dependencies: `uv sync --all-groups`
- Run Python entrypoints/tools: `uv run <command>`
- Run tests: `uv run pytest`
- CI: on push/PR to `main`, GitHub Actions runs `uv run pytest` with coverage (see `.github/workflows/ci.yml`).
- Add a dependency: `uv add <package>`
- Add a dev dependency: `uv add --dev <package>`

### Pre-commit (Ruff)

- Install git hooks once: `uv run pre-commit install`
- Run on all files: `uv run pre-commit run --all-files`

Hooks: `ruff-check` (lint + fix) and `ruff-format`, scoped to `src/` and `tests/`.

### Examples

- `uv run dust-pipeline --help`
- `uv run dust-pipeline project init project.toml`
- `uv run dust-pipeline rezaei2024 fetch --project project.toml`
- `uv run dust-pipeline rezaei2024 build --project project.toml`
- `uv run pytest tests/test_build.py`

## Package layout

- Import namespace: `foundinspace.dust.*`  (shared namespace with `found-in-space-pipeline`)
- No `__init__.py` at `src/foundinspace/` — namespace package, safe to coexist
- Entry point: `dust-pipeline = "foundinspace.dust.cli:cli"`

## Data / project files

Each command takes `--project path/to/project.toml`. The file may contain only
`[rezaei2024]` or mix in `[gaia]` / `[hip]` sections for fis-pipeline. Unknown
top-level sections are silently ignored by each pipeline's loader.

DO NOT run fetch or build commands unless explicitly asked. These download large
files (~400 MB) and write to wherever `output_bin` / `catalog_gz` point.
