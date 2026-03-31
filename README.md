# pipeline-dust

Pipeline for **3D interstellar dust** data (e.g. Rezaei Kh. et al. 2024 `finalmap.dat.gz` → `dust_map.bin` and related outputs). Tooling matches the sibling **found-in-space-pipeline** repo: **uv**, **hatchling** `src/` layout, **Ruff**, **pytest + coverage**, **pre-commit**, and **GitHub Actions CI**.

## Install

```bash
uv sync --all-groups
```

## CLI

```bash
uv run dust-pipeline --help
# or
uv run python -m pipeline_dust --help
```

Subcommands will be added as fetch/build steps land here.

## Develop

See [AGENTS.md](AGENTS.md) for `uv`, pre-commit, and CI.
