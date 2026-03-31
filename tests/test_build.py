"""Unit tests for rezaei2024 build functions using synthetic data."""

from __future__ import annotations

import gzip
import struct
from pathlib import Path

import numpy as np
import pytest

from foundinspace.dust.rezaei2024.build import (
    build_dust_map_bin,
    compute_grid_half_size_pc,
    galactic_to_icrs,
    parse_finalmap,
)

# Two synthetic rows matching the fixed-width column spec (1-based cols):
#   1- 6  GLON   7 = space   8-13  GLAT   14 = space  15-22  Distance
#   23 = space   24-29  Density   30 = space   31-35  s_Density
_SYNTHETIC_LINES = (
    "  0.00  0.00   100.00  0.10  0.01    99.97       0\n"
    " 90.00  0.00   200.00  0.05  0.01     0.00  199.97\n"
)


def _write_fixture(path: Path, compressed: bool = True) -> None:
    data = _SYNTHETIC_LINES.encode()
    if compressed:
        with gzip.open(path, "wb") as f:
            f.write(data)
    else:
        path.write_bytes(data)


def test_parse_finalmap_gz(tmp_path: Path) -> None:
    gz = tmp_path / "finalmap.dat.gz"
    _write_fixture(gz, compressed=True)
    coords, density = parse_finalmap(gz)
    assert coords.shape == (2, 3)
    assert density.shape == (2,)
    np.testing.assert_allclose(coords[0], [0.0, 0.0, 100.0], atol=0.01)
    np.testing.assert_allclose(density[0], 0.10, atol=0.01)


def test_parse_finalmap_uncompressed(tmp_path: Path) -> None:
    dat = tmp_path / "finalmap.dat"
    _write_fixture(dat, compressed=False)
    coords, density = parse_finalmap(dat)
    assert len(density) == 2


def test_galactic_to_icrs_shape() -> None:
    glon = np.array([0.0, 90.0])
    glat = np.array([0.0, 0.0])
    dist = np.array([100.0, 200.0])
    xyz = galactic_to_icrs(glon, glat, dist)
    assert xyz.shape == (2, 3)
    assert xyz.dtype == np.float32


def test_compute_grid_half_size_positive() -> None:
    rng = np.random.default_rng(0)
    pts = rng.uniform(0, 1000, size=(50, 3)).astype(np.float32)
    half = compute_grid_half_size_pc(pts)
    assert half > 0


def test_build_dust_map_bin_writes_correct_format(tmp_path: Path) -> None:
    gz = tmp_path / "finalmap.dat.gz"
    _write_fixture(gz)
    out = tmp_path / "dust_map.bin"
    result = build_dust_map_bin(gz, out)
    assert result == out
    assert out.exists()

    raw = out.read_bytes()
    # First 4 bytes: grid_half_size_pc (float32)
    (grid_half,) = struct.unpack_from("<f", raw, 0)
    assert grid_half > 0
    # Remaining bytes: N * 4 floats
    n_floats = (len(raw) - 4) // 4
    assert n_floats % 4 == 0, "payload should be N * 4 floats"
    n_points = n_floats // 4
    assert n_points == 2


def test_build_dust_map_bin_skips_when_output_exists(tmp_path: Path) -> None:
    gz = tmp_path / "finalmap.dat.gz"
    _write_fixture(gz)
    out = tmp_path / "dust_map.bin"
    out.write_bytes(b"sentinel")
    build_dust_map_bin(gz, out, force=False)
    assert out.read_bytes() == b"sentinel"  # untouched


def test_build_dust_map_bin_overwrites_with_force(tmp_path: Path) -> None:
    gz = tmp_path / "finalmap.dat.gz"
    _write_fixture(gz)
    out = tmp_path / "dust_map.bin"
    out.write_bytes(b"sentinel")
    build_dust_map_bin(gz, out, force=True)
    assert out.read_bytes() != b"sentinel"


def test_build_dust_map_bin_raises_when_input_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="missing.dat.gz"):
        build_dust_map_bin(tmp_path / "missing.dat.gz", tmp_path / "out.bin")
