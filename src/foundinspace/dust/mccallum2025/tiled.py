"""Build fixed-grid tiled H-alpha volume artifacts."""

from __future__ import annotations

import contextlib
import gzip
import json
import math
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from foundinspace.dust.mccallum2025.encoding import (
    GALACTIC_TO_ICRS_ROTATION,
    Quantization,
    _build_lod_grids,
    _compute_quantization,
    _pooled_axis_center_bounds,
    _quantize_asinh_uint8_with_params,
    _world_bounds,
)

TILED_VOLUME_FORMAT = "mccallum_ha_tiled_volume_v1"
TILED_LEVEL_MAGIC = b"FHATILE1"
TILED_LEVEL_VERSION = 1
TILED_LEVEL_HEADER_STRUCT = struct.Struct("<8s H H I I H H I I I f 6f 6f Q Q Q Q 8x")
TILED_LEVEL_RECORD_STRUCT = struct.Struct("<I H H H H B B H I Q I")
TILED_LEVEL_HEADER_BYTES = TILED_LEVEL_HEADER_STRUCT.size
TILED_LEVEL_RECORD_BYTES = TILED_LEVEL_RECORD_STRUCT.size

DEFAULT_TILED_VOLUME_RELATIVE_DIR = Path("data/packed/mccallum_2025/ha_tiled")
DEFAULT_SOURCE_FILENAME = "ha_grid.fits"
DEFAULT_LEVEL_COUNT = 4
DEFAULT_FINE_DIMENSION = 512
DEFAULT_CHUNK_PLANES = 8
DEFAULT_LOD_BRICK_SIZE = 8
DEFAULT_TILE_GRID_SIZE = 4
DEFAULT_TILE_HALO_CELLS = 1
DEFAULT_COMPRESSLEVEL = 9

FLAG_GZIP = 1 << 0


@dataclass(slots=True)
class TiledBrick:
    slot_index: int
    level_index: int
    level_id: str
    sample_size: int
    grid_x: int
    grid_y: int
    grid_z: int
    encoded_max: int = 0
    nonzero_count: int = 0
    payload_offset: int = 0
    payload_length: int = 0
    flags: int = FLAG_GZIP


def default_tiled_volume_output_dir(project_path: Path) -> Path:
    """Return the conventional project-relative fixed-grid tiled volume dir."""
    return (
        Path(project_path).expanduser().resolve().parent
        / DEFAULT_TILED_VOLUME_RELATIVE_DIR
    )


def _max_depth_for_fine_dimension(fine_dimension: int) -> int:
    ratio = fine_dimension / DEFAULT_LOD_BRICK_SIZE
    max_depth = int(math.log2(ratio)) if ratio > 0 else -1
    if DEFAULT_LOD_BRICK_SIZE * (2**max_depth) != fine_dimension:
        raise ValueError(
            f"fine_dimension must be {DEFAULT_LOD_BRICK_SIZE} * 2^N, "
            f"got {fine_dimension}"
        )
    return max_depth


def _level_specs(
    *,
    fine_dimension: int,
    level_count: int,
    max_depth: int,
) -> list[dict[str, Any]]:
    specs = []
    for level_index in range(level_count):
        dimension = fine_dimension // (2**level_index)
        level_id = f"l{level_index + 1}"
        specs.append(
            {
                "id": level_id,
                "dimension": dimension,
                "grid_level": max_depth - level_index,
            }
        )
    return specs


def _native_level_spec(source_dim: int) -> dict[str, Any]:
    return {
        "id": "l0",
        "dimension": source_dim,
        "grid_level": None,
    }


def build_ha_tiled_volume(
    input_path: Path,
    output_dir: Path,
    *,
    force: bool = False,
    level_count: int = DEFAULT_LEVEL_COUNT,
    fine_dimension: int = DEFAULT_FINE_DIMENSION,
    tile_grid_size: int = DEFAULT_TILE_GRID_SIZE,
    tile_halo_cells: int = DEFAULT_TILE_HALO_CELLS,
    chunk_planes: int = DEFAULT_CHUNK_PLANES,
    compresslevel: int = DEFAULT_COMPRESSLEVEL,
) -> Path:
    """Build fixed 4x4x4 gzip-tiled ``l0``..``lN`` H-alpha levels."""
    input_path = Path(input_path).expanduser()
    output_dir = Path(output_dir).expanduser()
    manifest_path = output_dir / "manifest.json"

    if not input_path.exists():
        raise FileNotFoundError(
            f"Missing {input_path.name}. "
            "Run 'dust-pipeline mccallum2025 download --project PROJECT' first."
        )

    _validate_tiled_options(
        level_count=level_count,
        fine_dimension=fine_dimension,
        tile_grid_size=tile_grid_size,
        tile_halo_cells=tile_halo_cells,
        chunk_planes=chunk_planes,
        compresslevel=compresslevel,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.TemporaryDirectory(prefix="ha_tiled_", dir=output_dir)
    try:
        with fits.open(input_path, memmap=True) as hdul:
            hdu = hdul[0]
            header = hdu.header
            data = hdu.data
            if data is None or data.ndim != 3:
                raise ValueError(f"{input_path} must contain a 3D primary FITS image")
            if len(set(data.shape)) != 1:
                raise ValueError(
                    f"{input_path} must be a cubic FITS image, got {data.shape}"
                )

            source_dim = int(data.shape[0])
            if source_dim % fine_dimension != 0:
                raise ValueError(
                    f"FITS dimension {source_dim} must be divisible by "
                    f"fine_dimension={fine_dimension}"
                )
            max_depth = _max_depth_for_fine_dimension(fine_dimension)
            if level_count > max_depth:
                raise ValueError(
                    f"level_count={level_count} would go below 16^3 for "
                    f"fine_dimension={fine_dimension}; maximum is {max_depth}"
                )
            source_pool_factor = source_dim // fine_dimension
            level_specs = [
                _native_level_spec(source_dim),
                *_level_specs(
                    fine_dimension=fine_dimension,
                    level_count=level_count,
                    max_depth=max_depth,
                ),
            ]
            expected_paths = [
                output_dir
                / _level_filename(
                    str(spec["id"]), int(spec["dimension"]), tile_grid_size
                )
                for spec in level_specs
            ]
            if (
                manifest_path.exists()
                and all(path.exists() for path in expected_paths)
                and _existing_manifest_matches(
                    manifest_path,
                    level_count=level_count,
                    fine_dimension=fine_dimension,
                    tile_grid_size=tile_grid_size,
                    compresslevel=compresslevel,
                    tile_halo_cells=tile_halo_cells,
                )
                and not force
            ):
                print(f"Skipping fixed-grid tiled build (outputs exist): {output_dir}")
                return manifest_path

            print(
                f"Building fixed-grid H-alpha tiles from {source_dim}^3 to "
                f"{level_specs[-1]['dimension']}^3 using {tile_grid_size}^3 slots"
            )
            lod_grids = _build_lod_grids(
                data=data,
                tmp_dir=Path(tmp_dir.name),
                source_dim=source_dim,
                leaf_dim=fine_dimension,
                source_pool_factor=source_pool_factor,
                max_depth=max_depth,
                brick_size=DEFAULT_LOD_BRICK_SIZE,
                chunk_leaf_planes=chunk_planes,
            )
            quantization = _compute_quantization(lod_grids[max_depth])
            print(
                "Tiled volume quantization from l1: "
                f"p50={quantization.p50_positive:.6g}, "
                f"p99.9={quantization.p99_9_positive:.6g}"
            )

            axis_center_bounds = _pooled_axis_center_bounds(
                header,
                crop_start=0,
                output_dim=source_dim,
                pool_factor=1,
            )
            world = _world_bounds(axis_center_bounds, source_dim)
            levels: list[dict[str, Any]] = []
            for spec in level_specs:
                level_id = str(spec["id"])
                level_index = int(level_id[1:])
                dim = int(spec["dimension"])
                grid_level = spec["grid_level"]
                data_for_level = (
                    data if grid_level is None else lod_grids[int(grid_level)]
                )
                output_path = output_dir / _level_filename(
                    level_id, dim, tile_grid_size
                )
                level_summary = _write_tiled_level(
                    data=data_for_level,
                    output_path=output_path,
                    level_id=level_id,
                    level_index=level_index,
                    dim=dim,
                    tile_grid_size=tile_grid_size,
                    tile_halo_cells=tile_halo_cells,
                    axis_center_bounds=_pooled_axis_center_bounds(
                        header,
                        crop_start=0,
                        output_dim=dim,
                        pool_factor=source_dim // dim,
                    ),
                    world=world,
                    quantization=quantization,
                    compresslevel=compresslevel,
                    force=force,
                )
                level_summary["source_pool_factor"] = (
                    None if grid_level is None else source_dim // dim
                )
                levels.append(level_summary)
                print(
                    f"Wrote {output_path} ({dim}^3 as "
                    f"{tile_grid_size}^3 tiles, "
                    f"{level_summary['compressed_payload_bytes']} bytes gzip payload)"
                )

            manifest = _build_manifest(
                input_path=input_path,
                output_dir=output_dir,
                header=header,
                data_shape=data.shape,
                data_dtype=str(data.dtype),
                source_dim=source_dim,
                fine_dimension=fine_dimension,
                level_count=level_count,
                tile_grid_size=tile_grid_size,
                tile_halo_cells=tile_halo_cells,
                compresslevel=compresslevel,
                quantization=quantization,
                world=world,
                levels=levels,
            )
            tmp_manifest_path = manifest_path.with_name(".manifest.json.tmp")
            tmp_manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tmp_manifest_path.replace(manifest_path)
    finally:
        tmp_dir.cleanup()

    print(f"H-alpha fixed-grid tiled volume ready at {manifest_path}")
    return manifest_path


def read_tiled_level_index(path: Path) -> tuple[dict[str, Any], list[TiledBrick]]:
    """Read a fixed-grid tiled level header and record table."""
    with Path(path).open("rb") as fp:
        raw_header = fp.read(TILED_LEVEL_HEADER_BYTES)
        if len(raw_header) != TILED_LEVEL_HEADER_BYTES:
            raise ValueError("truncated H-alpha tiled level header")
        (
            magic,
            version,
            header_size,
            record_size,
            brick_count,
            level_index,
            tile_grid_size,
            dimension,
            sample_size,
            flags,
            scalar_max,
            center_min_x,
            center_max_x,
            center_min_y,
            center_max_y,
            center_min_z,
            center_max_z,
            world_min_x,
            world_max_x,
            world_min_y,
            world_max_y,
            world_min_z,
            world_max_z,
            payload_start,
            file_bytes,
            compressed_payload_bytes,
            uncompressed_payload_bytes,
        ) = TILED_LEVEL_HEADER_STRUCT.unpack(raw_header)
        if magic != TILED_LEVEL_MAGIC:
            raise ValueError(f"bad H-alpha tiled level magic: {magic!r}")
        if version != TILED_LEVEL_VERSION:
            raise ValueError(f"unsupported H-alpha tiled level version: {version}")
        if header_size != TILED_LEVEL_HEADER_BYTES:
            raise ValueError(f"unexpected H-alpha tiled header size: {header_size}")
        if record_size != TILED_LEVEL_RECORD_BYTES:
            raise ValueError(f"unexpected H-alpha tiled record size: {record_size}")

        bricks = []
        for index in range(brick_count):
            raw = fp.read(TILED_LEVEL_RECORD_BYTES)
            if len(raw) != TILED_LEVEL_RECORD_BYTES:
                raise ValueError("truncated H-alpha tiled level record table")
            bricks.append(_unpack_brick(level_index, sample_size, raw, index))

    return (
        {
            "version": version,
            "header_size": header_size,
            "record_size": record_size,
            "brick_count": brick_count,
            "level_index": level_index,
            "tile_grid_size": tile_grid_size,
            "dimension": dimension,
            "sample_size": sample_size,
            "flags": flags,
            "scalar_max": scalar_max,
            "world_center_bounds_pc": {
                "x": [center_min_x, center_max_x],
                "y": [center_min_y, center_max_y],
                "z": [center_min_z, center_max_z],
            },
            "world_bounds_pc": {
                "x": [world_min_x, world_max_x],
                "y": [world_min_y, world_max_y],
                "z": [world_min_z, world_max_z],
            },
            "payload_start": payload_start,
            "file_bytes": file_bytes,
            "compressed_payload_bytes": compressed_payload_bytes,
            "uncompressed_payload_bytes": uncompressed_payload_bytes,
        },
        bricks,
    )


def _validate_tiled_options(
    *,
    level_count: int,
    fine_dimension: int,
    tile_grid_size: int,
    tile_halo_cells: int,
    chunk_planes: int,
    compresslevel: int,
) -> None:
    if level_count <= 0:
        raise ValueError("level_count must be positive")
    if fine_dimension <= 0:
        raise ValueError("fine_dimension must be positive")
    if tile_grid_size <= 0:
        raise ValueError("tile_grid_size must be positive")
    if tile_grid_size & (tile_grid_size - 1):
        raise ValueError("tile_grid_size must be a power of two")
    if fine_dimension % tile_grid_size:
        raise ValueError("fine_dimension must be divisible by tile_grid_size")
    if tile_halo_cells < 0:
        raise ValueError("tile_halo_cells must be non-negative")
    if chunk_planes <= 0:
        raise ValueError("chunk_planes must be positive")
    if not 0 <= compresslevel <= 9:
        raise ValueError("compresslevel must be between 0 and 9")


def _existing_manifest_matches(
    manifest_path: Path,
    *,
    level_count: int,
    fine_dimension: int,
    tile_grid_size: int,
    tile_halo_cells: int,
    compresslevel: int,
) -> bool:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    lod = manifest.get("lod", {})
    tile_grid = manifest.get("tile_grid", {})
    payload = manifest.get("payload", {})
    return (
        lod.get("level_count") == level_count
        and lod.get("fine_dimension") == fine_dimension
        and tile_grid.get("grid_size") == tile_grid_size
        and payload.get("tile_halo_cells", 0) == tile_halo_cells
        and payload.get("compresslevel") == compresslevel
    )


def _level_filename(level_id: str, dim: int, tile_grid_size: int) -> str:
    return f"ha_{level_id}_{dim}_tile{tile_grid_size}.bin"


def _morton3(x: int, y: int, z: int) -> int:
    code = 0
    for bit in range(10):
        code |= ((x >> bit) & 1) << (bit * 3)
        code |= ((y >> bit) & 1) << (bit * 3 + 1)
        code |= ((z >> bit) & 1) << (bit * 3 + 2)
    return code


def _decode_morton3(code: int) -> tuple[int, int, int]:
    x = y = z = 0
    for bit in range(10):
        x |= ((code >> (bit * 3)) & 1) << bit
        y |= ((code >> (bit * 3 + 1)) & 1) << bit
        z |= ((code >> (bit * 3 + 2)) & 1) << bit
    return x, y, z


def _write_tiled_level(
    *,
    data: np.ndarray,
    output_path: Path,
    level_id: str,
    level_index: int,
    dim: int,
    tile_grid_size: int,
    tile_halo_cells: int,
    axis_center_bounds: dict[str, tuple[float, float]],
    world: dict[str, Any],
    quantization: Quantization,
    compresslevel: int,
    force: bool,
) -> dict[str, Any]:
    sample_size = dim // tile_grid_size
    if sample_size <= 0 or sample_size * tile_grid_size != dim:
        raise ValueError(f"level dimension {dim} must be divisible by {tile_grid_size}")
    texture_sample_size = sample_size + 2 * tile_halo_cells
    brick_count = tile_grid_size**3
    table_bytes = TILED_LEVEL_HEADER_BYTES + brick_count * TILED_LEVEL_RECORD_BYTES
    records: list[TiledBrick] = []

    if output_path.exists() and not force:
        header, _ = read_tiled_level_index(output_path)
        expected_raw_bytes = brick_count * texture_sample_size**3
        if (
            int(header["dimension"]) == dim
            and int(header["sample_size"]) == sample_size
            and int(header["tile_grid_size"]) == tile_grid_size
            and int(header["uncompressed_payload_bytes"]) == expected_raw_bytes
        ):
            return _level_summary_from_header(
                output_path=output_path,
                level_id=level_id,
                level_index=level_index,
                header=header,
                compresslevel=compresslevel,
                tile_halo_cells=tile_halo_cells,
            )

    tmp_output_path = output_path.with_name(f".{output_path.name}.tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp_output_path.unlink()

    with tmp_output_path.open("wb") as fp:
        fp.write(bytes(table_bytes))
        for slot_index in range(brick_count):
            grid_x, grid_y, grid_z = _decode_morton3(slot_index)
            if (
                grid_x >= tile_grid_size
                or grid_y >= tile_grid_size
                or grid_z >= tile_grid_size
            ):
                raise ValueError(
                    f"Morton slot {slot_index} is outside {tile_grid_size}^3"
                )
            z0 = grid_z * sample_size
            y0 = grid_y * sample_size
            x0 = grid_x * sample_size
            brick = _extract_tile_with_halo(
                data=data,
                z0=z0,
                y0=y0,
                x0=x0,
                sample_size=sample_size,
                halo_cells=tile_halo_cells,
            )
            encoded = _quantize_asinh_uint8_with_params(brick, quantization)
            compressed = gzip.compress(
                encoded.tobytes(order="C"), compresslevel=compresslevel
            )
            records.append(
                TiledBrick(
                    slot_index=slot_index,
                    level_index=level_index,
                    level_id=level_id,
                    sample_size=sample_size,
                    grid_x=grid_x,
                    grid_y=grid_y,
                    grid_z=grid_z,
                    encoded_max=int(encoded.max(initial=0)),
                    nonzero_count=int(np.count_nonzero(encoded)),
                    payload_offset=fp.tell(),
                    payload_length=len(compressed),
                )
            )
            fp.write(compressed)

        file_bytes = fp.tell()
        fp.seek(0)
        fp.write(
            _pack_header(
                brick_count=brick_count,
                level_index=level_index,
                tile_grid_size=tile_grid_size,
                dim=dim,
                sample_size=sample_size,
                axis_center_bounds=axis_center_bounds,
                world=world,
                payload_start=table_bytes,
                file_bytes=file_bytes,
                compressed_payload_bytes=sum(brick.payload_length for brick in records),
                uncompressed_payload_bytes=brick_count * texture_sample_size**3,
            )
        )
        for brick in records:
            fp.write(_pack_brick(brick))

    tmp_output_path.replace(output_path)

    header, _ = read_tiled_level_index(output_path)
    return _level_summary_from_header(
        output_path=output_path,
        level_id=level_id,
        level_index=level_index,
        header=header,
        compresslevel=compresslevel,
        tile_halo_cells=tile_halo_cells,
    )


def _extract_tile_with_halo(
    *,
    data: np.ndarray,
    z0: int,
    y0: int,
    x0: int,
    sample_size: int,
    halo_cells: int,
) -> np.ndarray:
    dim_z, dim_y, dim_x = data.shape
    desired_z0 = z0 - halo_cells
    desired_y0 = y0 - halo_cells
    desired_x0 = x0 - halo_cells
    desired_z1 = z0 + sample_size + halo_cells
    desired_y1 = y0 + sample_size + halo_cells
    desired_x1 = x0 + sample_size + halo_cells

    src_z0 = max(0, desired_z0)
    src_y0 = max(0, desired_y0)
    src_x0 = max(0, desired_x0)
    src_z1 = min(dim_z, desired_z1)
    src_y1 = min(dim_y, desired_y1)
    src_x1 = min(dim_x, desired_x1)

    brick = np.asarray(
        data[src_z0:src_z1, src_y0:src_y1, src_x0:src_x1],
        dtype=np.float32,
    )
    pad_width = (
        (src_z0 - desired_z0, desired_z1 - src_z1),
        (src_y0 - desired_y0, desired_y1 - src_y1),
        (src_x0 - desired_x0, desired_x1 - src_x1),
    )
    if any(before or after for before, after in pad_width):
        brick = np.pad(brick, pad_width, mode="edge")
    return brick


def _pack_header(
    *,
    brick_count: int,
    level_index: int,
    tile_grid_size: int,
    dim: int,
    sample_size: int,
    axis_center_bounds: dict[str, tuple[float, float]],
    world: dict[str, Any],
    payload_start: int,
    file_bytes: int,
    compressed_payload_bytes: int,
    uncompressed_payload_bytes: int,
) -> bytes:
    center = axis_center_bounds
    edges = world["edges"]
    return TILED_LEVEL_HEADER_STRUCT.pack(
        TILED_LEVEL_MAGIC,
        TILED_LEVEL_VERSION,
        TILED_LEVEL_HEADER_BYTES,
        TILED_LEVEL_RECORD_BYTES,
        brick_count,
        level_index,
        tile_grid_size,
        dim,
        sample_size,
        FLAG_GZIP,
        1.0,
        center["x"][0],
        center["x"][1],
        center["y"][0],
        center["y"][1],
        center["z"][0],
        center["z"][1],
        edges["x"][0],
        edges["x"][1],
        edges["y"][0],
        edges["y"][1],
        edges["z"][0],
        edges["z"][1],
        payload_start,
        file_bytes,
        compressed_payload_bytes,
        uncompressed_payload_bytes,
    )


def _pack_brick(brick: TiledBrick) -> bytes:
    return TILED_LEVEL_RECORD_STRUCT.pack(
        brick.slot_index,
        brick.grid_x,
        brick.grid_y,
        brick.grid_z,
        0,
        brick.encoded_max,
        brick.flags,
        0,
        brick.nonzero_count,
        brick.payload_offset,
        brick.payload_length,
    )


def _unpack_brick(
    level_index: int, sample_size: int, raw: bytes, index: int
) -> TiledBrick:
    (
        slot_index,
        grid_x,
        grid_y,
        grid_z,
        _reserved0,
        encoded_max,
        flags,
        _reserved1,
        nonzero_count,
        payload_offset,
        payload_length,
    ) = TILED_LEVEL_RECORD_STRUCT.unpack(raw)
    if slot_index != _morton3(grid_x, grid_y, grid_z):
        raise ValueError(
            f"record {index} has Morton slot {slot_index}, "
            f"expected {_morton3(grid_x, grid_y, grid_z)}"
        )
    return TiledBrick(
        slot_index=slot_index,
        level_index=level_index,
        level_id=f"l{level_index}",
        sample_size=sample_size,
        grid_x=grid_x,
        grid_y=grid_y,
        grid_z=grid_z,
        encoded_max=encoded_max,
        nonzero_count=nonzero_count,
        payload_offset=payload_offset,
        payload_length=payload_length,
        flags=flags,
    )


def _level_summary_from_header(
    *,
    output_path: Path,
    level_id: str,
    level_index: int,
    header: dict[str, Any],
    compresslevel: int,
    tile_halo_cells: int,
) -> dict[str, Any]:
    raw_bytes = int(header["uncompressed_payload_bytes"])
    compressed_bytes = int(header["compressed_payload_bytes"])
    sample_size = int(header["sample_size"])
    return {
        "id": level_id,
        "level_index": level_index,
        "dimension": int(header["dimension"]),
        "sample_size": sample_size,
        "tile_halo_cells": tile_halo_cells,
        "texture_sample_size": sample_size + 2 * tile_halo_cells,
        "tile_grid_size": int(header["tile_grid_size"]),
        "brick_count": int(header["brick_count"]),
        "path": output_path.name,
        "file_bytes": int(header["file_bytes"]),
        "raw_payload_bytes": raw_bytes,
        "compressed_payload_bytes": compressed_bytes,
        "compression": "gzip",
        "compresslevel": compresslevel,
        "compression_ratio": compressed_bytes / raw_bytes if raw_bytes else 0.0,
    }


def _build_manifest(
    *,
    input_path: Path,
    output_dir: Path,
    header: fits.Header,
    data_shape: tuple[int, ...],
    data_dtype: str,
    source_dim: int,
    fine_dimension: int,
    level_count: int,
    tile_grid_size: int,
    tile_halo_cells: int,
    compresslevel: int,
    quantization: Quantization,
    world: dict[str, Any],
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": TILED_VOLUME_FORMAT,
        "runtime_frame": "galactic_cartesian_sun_centered",
        "native_frame": {
            "name": "galactic_cartesian_sun_centered",
            "axis_unit": "pc",
            "galactic_to_icrs_rotation": GALACTIC_TO_ICRS_ROTATION,
        },
        "source": {
            "path": str(input_path),
            "hdu": 0,
            "shape": list(data_shape),
            "dtype": data_dtype,
            "value_unit": str(header.get("BUNIT", "")),
            "axis_units": [
                str(header.get("CUNIT1", "")),
                str(header.get("CUNIT2", "")),
                str(header.get("CUNIT3", "")),
            ],
        },
        "world_bounds_pc": world["edges"],
        "world_extent_pc": world["extent"],
        "world_center_pc": world["center"],
        "lod": {
            "source_dimension": source_dim,
            "fine_dimension": fine_dimension,
            "level_count": level_count,
            "levels": levels,
            "naming": (
                "l0 is native resolution; l1 is the finest pooled level; "
                "later levels are repeated 2x mean downsampled"
            ),
        },
        "tile_grid": {
            "grid_size": tile_grid_size,
            "halo_cells": tile_halo_cells,
            "brick_count": tile_grid_size**3,
            "ordering": "morton_xyz",
            "description": (
                "Every level uses the same world-space grid; a runtime may "
                "replace any low-resolution slot with the same slot from a "
                "higher-resolution level."
            ),
        },
        "runtime_policy": {
            "low_level_id": "l3"
            if any(level["id"] == "l3" for level in levels)
            else levels[-1]["id"],
            "high_level_id": "l0",
            "description": (
                "Load low-level fixed slots first, then request one l0 slot at "
                "a time and swap it into the same world-space cube."
            ),
        },
        "quantization": {
            **quantization.to_json(),
            "source": "l1",
        },
        "payload": {
            "compression": "gzip",
            "compresslevel": compresslevel,
            "tile_halo_cells": tile_halo_cells,
            "brick_layout": "uint8 scalar[iz, iy, ix], x varies fastest",
            "file_layout": (
                "Each level file contains a 128-byte header, a 32-byte record "
                "per Morton-ordered brick, then independently gzip-compressed "
                "brick payloads. Each brick payload includes a halo around "
                "the fixed world-space tile interior."
            ),
            "level_magic": TILED_LEVEL_MAGIC.decode("ascii"),
            "level_header_bytes": TILED_LEVEL_HEADER_BYTES,
            "level_record_bytes": TILED_LEVEL_RECORD_BYTES,
            "flags": {
                "gzip": FLAG_GZIP,
            },
        },
        "output": {
            "directory": str(output_dir),
            "manifest": "manifest.json",
        },
    }
