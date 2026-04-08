from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

from foundinspace.dust.project import (
    FORMAT_VERSION,
    load_project,
    render_project_template,
)


def _project_text() -> str:
    return (
        "format_version = 1\n\n"
        "[rezaei2024]\n"
        'catalog_gz = "data/catalogs/finalmap.dat.gz"\n'
        'output_bin = "data/processed/dust_map_ng.bin"\n'
        "\n"
        "[mccallum2025]\n"
        'record_id = "15041318"\n'
        'raw_dir = "data/raw/zenodo/mccallum_2025"\n'
    )


def test_load_project_resolves_relative_paths(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(_project_text(), encoding="utf-8")

    project = load_project(project_path)
    assert (
        project.rezaei2024.catalog_gz
        == tmp_path / "data" / "catalogs" / "finalmap.dat.gz"
    )
    assert (
        project.rezaei2024.output_bin
        == tmp_path / "data" / "processed" / "dust_map_ng.bin"
    )
    assert project.mccallum2025.record_id == "15041318"
    assert (
        project.mccallum2025.raw_dir
        == tmp_path / "data" / "raw" / "zenodo" / "mccallum_2025"
    )


def test_load_project_ignores_unknown_top_level_sections(tmp_path: Path) -> None:
    """Unknown sections (e.g. [gaia] from fis-pipeline) are silently ignored."""
    project_path = tmp_path / "project.toml"
    project_path.write_text(
        _project_text() + '\n[gaia]\noutput_dir = "data/processed/gaia"\n',
        encoding="utf-8",
    )
    project = load_project(project_path)
    assert project.rezaei2024.is_configured is True
    assert project.mccallum2025.is_configured is True


def test_load_project_rejects_env_style_path_strings(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(
        _project_text().replace(
            'catalog_gz = "data/catalogs/finalmap.dat.gz"',
            'catalog_gz = "${DATA_DIR}/finalmap.dat.gz"',
        ),
        encoding="utf-8",
    )
    project = load_project(project_path)
    with pytest.raises(ValueError, match="environment-variable syntax"):
        _ = project.rezaei2024.catalog_gz


def test_load_project_rejects_env_style_mccallum_path_strings(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(
        _project_text().replace(
            'raw_dir = "data/raw/zenodo/mccallum_2025"',
            'raw_dir = "$DATA_DIR/mccallum_2025"',
        ),
        encoding="utf-8",
    )
    project = load_project(project_path)
    with pytest.raises(ValueError, match="environment-variable syntax"):
        _ = project.mccallum2025.raw_dir


def test_load_project_rejects_unknown_keys_in_section(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(
        _project_text().replace(
            'output_bin = "data/processed/dust_map_ng.bin"\n',
            'output_bin = "data/processed/dust_map_ng.bin"\nextra_key = "oops"\n',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"Unknown key\(s\) in \[rezaei2024\]"):
        load_project(project_path)


def test_load_project_rejects_unknown_keys_in_mccallum_section(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(
        _project_text() + 'extra_key = "oops"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"Unknown key\(s\) in \[mccallum2025\]"):
        load_project(project_path)


def test_load_project_requires_format_version(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(
        _project_text().replace("format_version = 1", "format_version = 99"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=f"format_version must be {FORMAT_VERSION}"):
        load_project(project_path)


def test_section_is_configured_false_when_absent(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text("format_version = 1\n", encoding="utf-8")

    project = load_project(project_path)
    assert project.rezaei2024.is_configured is False
    assert project.mccallum2025.is_configured is False
    with pytest.raises(ValueError, match=r"Missing \[rezaei2024\]"):
        _ = project.rezaei2024.catalog_gz
    with pytest.raises(ValueError, match=r"Missing \[mccallum2025\]"):
        _ = project.mccallum2025.raw_dir


def test_require_raises_listing_missing_sections(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text("format_version = 1\n", encoding="utf-8")

    project = load_project(project_path)
    with pytest.raises(ValueError, match=r"\[rezaei2024\].*\[mccallum2025\]"):
        project.require("rezaei2024", "mccallum2025")


def test_require_raises_for_unknown_section_name(tmp_path: Path) -> None:
    project_path = tmp_path / "project.toml"
    project_path.write_text(_project_text(), encoding="utf-8")

    project = load_project(project_path)
    with pytest.raises(ValueError, match="unknown section name"):
        project.require("unknown-section")


def test_render_project_template_is_valid_toml(tmp_path: Path) -> None:
    rendered = render_project_template()
    parsed = tomllib.loads(rendered)
    assert parsed["format_version"] == FORMAT_VERSION
    assert "catalog_gz" in parsed["rezaei2024"]
    assert "output_bin" in parsed["rezaei2024"]
    assert parsed["mccallum2025"]["record_id"] == "15041318"
    assert "raw_dir" in parsed["mccallum2025"]
