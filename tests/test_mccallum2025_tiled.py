from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from foundinspace.dust.mccallum2025.tiled import (
    FLAG_GZIP,
    TILED_LEVEL_HEADER_BYTES,
    TILED_LEVEL_RECORD_BYTES,
    TILED_VOLUME_FORMAT,
    build_ha_tiled_volume,
    read_tiled_level_index,
)


def _write_test_fits(path: Path, data: np.ndarray) -> None:
    hdu = fits.PrimaryHDU(data.astype(np.float32))
    header = hdu.header
    header["CTYPE1"] = "X"
    header["CTYPE2"] = "Y"
    header["CTYPE3"] = "Z"
    header["CRVAL1"] = -16.0
    header["CRVAL2"] = -16.0
    header["CRVAL3"] = -16.0
    header["CRPIX1"] = 1.0
    header["CRPIX2"] = 1.0
    header["CRPIX3"] = 1.0
    header["CDELT1"] = 1.0
    header["CDELT2"] = 1.0
    header["CDELT3"] = 1.0
    header["CUNIT1"] = "pc"
    header["CUNIT2"] = "pc"
    header["CUNIT3"] = "pc"
    header["BUNIT"] = "J/s/m^-3"
    hdu.writeto(path)


def _payload_for_brick(output_path: Path, brick) -> np.ndarray:
    payload = output_path.read_bytes()[
        brick.payload_offset : brick.payload_offset + brick.payload_length
    ]
    return np.frombuffer(gzip.decompress(payload), dtype=np.uint8)


def test_build_ha_tiled_volume_writes_fixed_grid_level_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ha_grid.fits"
    output_dir = tmp_path / "ha_tiled"
    data = np.zeros((32, 32, 32), dtype=np.float32)
    data[:16, :16, :16] = 4.0
    data[16:, 16:, 16:] = 2.0
    _write_test_fits(source, data)

    manifest_path = build_ha_tiled_volume(
        source,
        output_dir,
        level_count=1,
        fine_dimension=16,
        tile_grid_size=4,
        chunk_planes=2,
        compresslevel=9,
    )

    assert manifest_path == output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == TILED_VOLUME_FORMAT
    assert manifest["tile_grid"]["grid_size"] == 4
    assert manifest["tile_grid"]["brick_count"] == 64
    assert manifest["runtime_policy"]["high_level_id"] == "l0"
    assert manifest["runtime_policy"]["low_level_id"] == "l1"
    assert [level["id"] for level in manifest["lod"]["levels"]] == ["l0", "l1"]
    assert manifest["payload"]["compresslevel"] == 9
    assert manifest["payload"]["tile_halo_cells"] == 1

    l0_path = output_dir / "ha_l0_32_tile4.bin"
    header, bricks = read_tiled_level_index(l0_path)
    assert header["header_size"] == TILED_LEVEL_HEADER_BYTES
    assert header["record_size"] == TILED_LEVEL_RECORD_BYTES
    assert header["brick_count"] == 64
    assert header["level_index"] == 0
    assert header["tile_grid_size"] == 4
    assert header["dimension"] == 32
    assert header["sample_size"] == 8
    assert (
        header["payload_start"]
        == TILED_LEVEL_HEADER_BYTES + 64 * TILED_LEVEL_RECORD_BYTES
    )
    assert header["file_bytes"] == l0_path.stat().st_size
    assert header["uncompressed_payload_bytes"] == 64 * 10 * 10 * 10

    assert len(bricks) == 64
    assert [
        (brick.slot_index, brick.grid_x, brick.grid_y, brick.grid_z)
        for brick in bricks[:8]
    ] == [
        (0, 0, 0, 0),
        (1, 1, 0, 0),
        (2, 0, 1, 0),
        (3, 1, 1, 0),
        (4, 0, 0, 1),
        (5, 1, 0, 1),
        (6, 0, 1, 1),
        (7, 1, 1, 1),
    ]
    assert all(brick.flags & FLAG_GZIP for brick in bricks)
    assert all(
        left.payload_offset + left.payload_length == right.payload_offset
        for left, right in zip(bricks[:-1], bricks[1:], strict=True)
    )

    decoded = _payload_for_brick(l0_path, bricks[0])
    assert decoded.shape == (10 * 10 * 10,)
    assert decoded.min() == 255
    assert decoded.max() == 255

    assert (bricks[8].grid_x, bricks[8].grid_y, bricks[8].grid_z) == (2, 0, 0)
    assert (bricks[9].grid_x, bricks[9].grid_y, bricks[9].grid_z) == (3, 0, 0)
    empty_tile = _payload_for_brick(l0_path, bricks[9])
    assert empty_tile.shape == (10 * 10 * 10,)
    assert empty_tile.max() == 0


def test_build_ha_tiled_volume_reports_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="mccallum2025 download"):
        build_ha_tiled_volume(tmp_path / "ha_grid.fits", tmp_path / "ha_tiled")
