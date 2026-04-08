"""Shared H-alpha volume encoding helpers for the tiled McCallum output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

GALACTIC_TO_ICRS_ROTATION = [
    [-0.0548755604, +0.4941094279, -0.8676661490],
    [-0.8734370902, -0.4448296300, -0.1980763734],
    [-0.4838350155, +0.7469822445, +0.4559837762],
]


@dataclass(frozen=True, slots=True)
class Quantization:
    positive_voxel_count: int
    p50_positive: float
    p99_9_positive: float
    transform: str = "asinh(clamp(value, 0, p99_9_positive) / p50_positive)"

    def to_json(self) -> dict[str, Any]:
        return {
            "positive_voxel_count": self.positive_voxel_count,
            "p50_positive": self.p50_positive,
            "p99_9_positive": self.p99_9_positive,
            "transform": self.transform,
            "encoded_dtype": "uint8",
            "encoded_min": 0,
            "encoded_max": 255,
            "physical_values": False,
        }


def _average_pool_3d(block: np.ndarray, pool_factor: int) -> np.ndarray:
    z, y, x = block.shape
    if z % pool_factor or y % pool_factor or x % pool_factor:
        raise ValueError(f"block shape {block.shape} is not divisible by {pool_factor}")
    return block.reshape(
        z // pool_factor,
        pool_factor,
        y // pool_factor,
        pool_factor,
        x // pool_factor,
        pool_factor,
    ).mean(axis=(1, 3, 5), dtype=np.float32)


def _pooled_axis_center_bounds(
    header: fits.Header,
    *,
    crop_start: int,
    output_dim: int,
    pool_factor: int,
) -> dict[str, tuple[float, float]]:
    return {
        "x": _pooled_axis_center_bound(header, 1, crop_start, output_dim, pool_factor),
        "y": _pooled_axis_center_bound(header, 2, crop_start, output_dim, pool_factor),
        "z": _pooled_axis_center_bound(header, 3, crop_start, output_dim, pool_factor),
    }


def _pooled_axis_center_bound(
    header: fits.Header,
    axis_number: int,
    crop_start: int,
    output_dim: int,
    pool_factor: int,
) -> tuple[float, float]:
    crval = float(header.get(f"CRVAL{axis_number}", 0.0))
    crpix = float(header.get(f"CRPIX{axis_number}", 1.0))
    cdelt = float(header.get(f"CDELT{axis_number}", 1.0))

    def source_center(index_zero_based: float) -> float:
        fits_pixel = index_zero_based + 1.0
        return crval + (fits_pixel - crpix) * cdelt

    first = source_center(crop_start + (pool_factor - 1) / 2.0)
    last = source_center(
        crop_start + (output_dim - 1) * pool_factor + (pool_factor - 1) / 2.0
    )
    return (first, last)


def _build_lod_grids(
    *,
    data: np.ndarray,
    tmp_dir: Path,
    source_dim: int,
    leaf_dim: int,
    source_pool_factor: int,
    max_depth: int,
    brick_size: int,
    chunk_leaf_planes: int,
) -> dict[int, np.memmap]:
    lod_grids: dict[int, np.memmap] = {}
    leaf_grid = _new_memmap(
        tmp_dir, f"lod_{max_depth}_{leaf_dim}.dat", (leaf_dim, leaf_dim, leaf_dim)
    )

    for out_z0 in range(0, leaf_dim, chunk_leaf_planes):
        out_z1 = min(out_z0 + chunk_leaf_planes, leaf_dim)
        src_z0 = out_z0 * source_pool_factor
        src_z1 = out_z1 * source_pool_factor
        block = np.asarray(
            data[src_z0:src_z1, :source_dim, :source_dim], dtype=np.float32
        )
        np.nan_to_num(block, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        np.maximum(block, 0.0, out=block)
        if source_pool_factor == 1:
            pooled = block
        else:
            pooled = _average_pool_3d(block, source_pool_factor)
        leaf_grid[out_z0:out_z1] = pooled

    leaf_grid.flush()
    lod_grids[max_depth] = leaf_grid

    for level in range(max_depth - 1, -1, -1):
        child = lod_grids[level + 1]
        dim = brick_size * (2**level)
        parent = _new_memmap(tmp_dir, f"lod_{level}_{dim}.dat", (dim, dim, dim))
        for out_z0 in range(0, dim, chunk_leaf_planes):
            out_z1 = min(out_z0 + chunk_leaf_planes, dim)
            src_z0 = out_z0 * 2
            src_z1 = out_z1 * 2
            parent[out_z0:out_z1] = _average_pool_3d(
                np.asarray(child[src_z0:src_z1], dtype=np.float32),
                2,
            )
        parent.flush()
        lod_grids[level] = parent

    return lod_grids


def _new_memmap(tmp_dir: Path, filename: str, shape: tuple[int, int, int]) -> np.memmap:
    return np.memmap(tmp_dir / filename, dtype=np.float32, mode="w+", shape=shape)


def _compute_quantization(values: np.ndarray) -> Quantization:
    clean = np.asarray(values, dtype=np.float32)
    positive = clean[clean > 0.0]
    if positive.size == 0:
        return Quantization(
            positive_voxel_count=0, p50_positive=0.0, p99_9_positive=0.0
        )

    p50 = float(np.percentile(positive, 50.0))
    p99_9 = float(np.percentile(positive, 99.9))
    if not np.isfinite(p50) or p50 <= 0.0:
        p50 = float(np.min(positive))
    if not np.isfinite(p99_9) or p99_9 < p50:
        p99_9 = p50
    return Quantization(
        positive_voxel_count=int(positive.size),
        p50_positive=p50,
        p99_9_positive=p99_9,
    )


def _quantize_asinh_uint8_with_params(
    values: np.ndarray,
    quantization: Quantization,
) -> np.ndarray:
    clean = np.asarray(values, dtype=np.float32)
    clean = np.nan_to_num(clean, copy=True, nan=0.0, posinf=0.0, neginf=0.0)
    np.maximum(clean, 0.0, out=clean)

    p50 = quantization.p50_positive
    p99_9 = quantization.p99_9_positive
    if p50 <= 0.0 or p99_9 <= 0.0:
        return np.zeros(clean.shape, dtype=np.uint8)

    denom = float(np.arcsinh(p99_9 / p50))
    if not np.isfinite(denom) or denom <= 0.0:
        denom = 1.0
    encoded = np.arcsinh(np.minimum(clean, p99_9) / p50) / denom
    encoded = np.clip(encoded, 0.0, 1.0)
    return np.round(encoded * 255.0).astype(np.uint8)


def _world_bounds(
    axis_center_bounds: dict[str, tuple[float, float]],
    leaf_dim: int,
) -> dict[str, Any]:
    edges: dict[str, list[float]] = {}
    extent: dict[str, float] = {}
    center: dict[str, float] = {}
    for axis, bounds in axis_center_bounds.items():
        first, last = bounds
        spacing = (last - first) / max(1, leaf_dim - 1)
        edge0 = first - spacing / 2.0
        edge1 = last + spacing / 2.0
        edges[axis] = [float(edge0), float(edge1)]
        extent[axis] = float(abs(edge1 - edge0))
        center[axis] = float((edge0 + edge1) / 2.0)
    return {"edges": edges, "extent": extent, "center": center}
