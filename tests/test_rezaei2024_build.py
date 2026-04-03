"""Tests for Rezaei 2024 finalmap gridding (snap + duplicate averaging)."""

from __future__ import annotations

from pathlib import Path

import pytest

from foundinspace.dust.rezaei2024.build import _parse_and_grid


def _finalmap_line(
    *,
    galx: float,
    galy: float,
    glon: float = 0.0,
    glat: float = 0.0,
    distance: float = 0.0,
    density: float = 1.0,
    sigma_density: float = 0.0,
) -> str:
    """One ASCII row matching parse_finalmap_raw fixed-width slices."""
    return (
        f"{glon:6.2f}"
        f" "
        f"{glat:6.2f}"
        f" "
        f"{distance:8.2f}"
        f" "
        f"{density:6.2f}"
        f" "
        f"{sigma_density:5.2f}"
        f" "
        f"{galx:9.2f}"
        f" "
        f"{galy:6.0f}"
    )


def test_parse_and_grid_warns_when_galx_off_lattice(tmp_path: Path) -> None:
    path = tmp_path / "finalmap.dat"
    path.write_text(_finalmap_line(galx=144.0, galy=0.0) + "\n", encoding="ascii")

    with pytest.warns(UserWarning, match=r"GalX"):
        grid, meta = _parse_and_grid(path)

    assert meta["nx"] >= 1
    assert grid.shape == (5, 1, 1)


def test_parse_and_grid_warns_when_galy_off_lattice(tmp_path: Path) -> None:
    path = tmp_path / "finalmap.dat"
    path.write_text(_finalmap_line(galx=100.0, galy=55.0) + "\n", encoding="ascii")

    with pytest.warns(UserWarning, match=r"GalY"):
        _parse_and_grid(path)


def test_parse_and_grid_no_warning_when_xy_on_lattice(
    tmp_path: Path, recwarn: pytest.WarningsRecorder
) -> None:
    path = tmp_path / "finalmap.dat"
    path.write_text(_finalmap_line(galx=100.0, galy=200.0) + "\n", encoding="ascii")

    _parse_and_grid(path)

    user_warnings = [w for w in recwarn if issubclass(w.category, UserWarning)]
    assert user_warnings == []
