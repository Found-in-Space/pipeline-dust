"""Build dust_map_ng.bin from finalmap.dat.gz — 3D dust voxel texture.

The Rezaei Kh. et al. 2024 map is predicted on a regular Cartesian grid:
  X, Y : 100 pc spacing
  Z    : 5 layers at −750, −375, 0, +375, +750 pc (Galactic height)

Raw rows are snapped to the nearest grid point and duplicates are averaged.
The output is a 3D voxel texture suitable for GPU volume rendering.

Output binary format (dust_map_ng.bin) — little-endian
------------------------------------------------------
  Header (48 bytes):
    Bytes  0– 3 : uint32   NX
    Bytes  4– 7 : uint32   NY
    Bytes  8–11 : uint32   NZ
    Bytes 12–15 : float32  max_density (cm⁻³, maps to uint8 255)
    Bytes 16–19 : float32  min_x (pc)
    Bytes 20–23 : float32  max_x (pc)
    Bytes 24–27 : float32  min_y (pc)
    Bytes 28–31 : float32  max_y (pc)
    Bytes 32–35 : float32  min_z (pc)
    Bytes 36–39 : float32  max_z (pc)
    Bytes 40–47 : reserved (0)
  Data (NX * NY * NZ bytes):
    uint8 density[iz, iy, ix]  — x varies fastest (Three.js convention)

Fixed-width column spec (finalmap ReadMe, 1-based columns)
----------------------------------------------------------
  1-  6  F6.2  deg     GLON      Galactic longitude
  8- 13  F6.2  deg     GLAT      Galactic latitude
 15- 22  F8.2  pc      Distance  Distance from the Sun
 24- 29  F6.2  cm-3    Density   Particle number density
 31- 35  F5.2  cm-3  s_Density   Standard deviation of Density
 37- 45  F9.2  pc      GalX      Galactic X coordinate
 47- 52  I6    pc      GalY      Galactic Y coordinate
"""

from __future__ import annotations

import gzip
import struct
import warnings
from pathlib import Path

import numpy as np

_XY_STEP = 100.0  # pc
_Z_LAYERS = np.array([-750.0, -375.0, 0.0, 375.0, 750.0])
_GRID_SNAP_WARN_THRESHOLD_PC = 1.0
_HEADER_SIZE = 48


def _warn_if_xy_snap_offset_large(
    source_name: str,
    galx_raw: np.ndarray,
    galx_snap: np.ndarray,
    galy_raw: np.ndarray,
    galy_snap: np.ndarray,
) -> None:
    """Emit UserWarning when catalog XY is not already on the 100 pc lattice (within 1 pc).

    Galactic height (Z) is not checked: it is derived continuously and is always
    snapped to the nearest slab, so large |raw − snapped| is expected there.
    """
    threshold = _GRID_SNAP_WARN_THRESHOLD_PC
    for label, raw, snap in (
        ("GalX", galx_raw, galx_snap),
        ("GalY", galy_raw, galy_snap),
    ):
        delta = np.abs(raw - snap)
        off = delta > threshold
        if not np.any(off):
            continue
        n = int(np.count_nonzero(off))
        worst = float(np.max(delta[off]))
        warnings.warn(
            f"{source_name}: {n} row(s) have |{label} raw - snapped| > {threshold} pc "
            f"(max {worst:.2f} pc); voxels use snapped XY.",
            UserWarning,
            stacklevel=2,
        )


def parse_finalmap_raw(path: Path) -> dict[str, np.ndarray]:
    """Parse finalmap.dat[.gz] into native Galactic raw arrays.

    The published map is fundamentally Galactic: GalX/GalY are tabulated in the
    catalog and Galactic height is derived from (distance, latitude). This
    helper is the internal representation used when gridding to the voxel
    texture.
    """
    open_fn = gzip.open if str(path).endswith(".gz") else open

    glon_list: list[float] = []
    glat_list: list[float] = []
    dist_list: list[float] = []
    density_list: list[float] = []
    sigma_density_list: list[float] = []
    galx_list: list[float] = []
    galy_list: list[float] = []

    with open_fn(path, "rt") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            glon_list.append(float(line[0:6]))
            glat_list.append(float(line[7:13]))
            dist_list.append(float(line[14:22]))
            density_list.append(float(line[23:29]))
            sigma_density_list.append(float(line[30:35]))
            galx_list.append(float(line[36:45]))
            galy_list.append(float(line[46:52]))

    glon = np.array(glon_list, dtype=np.float32)
    glat = np.array(glat_list, dtype=np.float32)
    distance = np.array(dist_list, dtype=np.float32)
    density = np.array(density_list, dtype=np.float32)
    sigma_density = np.array(sigma_density_list, dtype=np.float32)
    galx = np.array(galx_list, dtype=np.float32)
    galy = np.array(galy_list, dtype=np.float32)
    galz = (distance * np.sin(np.radians(glat))).astype(np.float32)

    return {
        "glon_deg": glon,
        "glat_deg": glat,
        "distance_pc": distance,
        "density_cm3": density,
        "sigma_density_cm3": sigma_density,
        "gal_x_pc": galx,
        "gal_y_pc": galy,
        "gal_z_pc": galz,
    }


def _parse_and_grid(path: Path) -> tuple[np.ndarray, dict]:
    """Parse finalmap.dat[.gz], snap to the publication grid, return 3D array.

    Returns
    -------
    grid : ndarray, shape (NZ, NY, NX), uint8 — normalised density.
    meta : dict with keys nx, ny, nz, max_density, min_x, max_x, …
    """
    raw = parse_finalmap_raw(path)
    galx_raw = raw["gal_x_pc"].astype(np.float64)
    galy_raw = raw["gal_y_pc"].astype(np.float64)
    galz_raw = raw["gal_z_pc"].astype(np.float64)
    density_raw = raw["density_cm3"].astype(np.float64)

    galx_snap = np.round(galx_raw / _XY_STEP) * _XY_STEP
    galy_snap = np.round(galy_raw / _XY_STEP) * _XY_STEP
    galz_snap = _Z_LAYERS[
        np.argmin(np.abs(galz_raw[:, None] - _Z_LAYERS[None, :]), axis=1)
    ]

    _warn_if_xy_snap_offset_large(path.name, galx_raw, galx_snap, galy_raw, galy_snap)

    # Average density for rows that map to the same grid cell
    keys = np.column_stack([galx_snap, galy_snap, galz_snap])
    unique_keys, inv, counts = np.unique(
        keys, axis=0, return_inverse=True, return_counts=True
    )
    density_sum = np.zeros(len(counts), dtype=np.float64)
    np.add.at(density_sum, inv, density_raw)
    density_mean = density_sum / counts

    # Build sorted axis arrays
    ux = np.sort(np.unique(galx_snap))
    uy = np.sort(np.unique(galy_snap))
    uz = np.sort(_Z_LAYERS)
    nx, ny, nz = len(ux), len(uy), len(uz)

    # Map snapped coords to grid indices
    x_to_ix = {v: i for i, v in enumerate(ux)}
    y_to_iy = {v: i for i, v in enumerate(uy)}
    z_to_iz = {v: i for i, v in enumerate(uz)}

    grid = np.zeros((nz, ny, nx), dtype=np.float64)

    for row, density_value in zip(unique_keys, density_mean, strict=True):
        ix = x_to_ix.get(row[0])
        iy = y_to_iy.get(row[1])
        iz = z_to_iz.get(row[2])
        if ix is not None and iy is not None and iz is not None:
            grid[iz, iy, ix] = density_value

    # Clamp negatives, normalise to uint8
    grid = np.clip(grid, 0.0, None)
    max_density = float(grid.max()) if grid.max() > 0 else 1.0
    grid_u8 = np.round(grid / max_density * 255.0).astype(np.uint8)

    meta = {
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "max_density": max_density,
        "min_x": float(ux[0]),
        "max_x": float(ux[-1]),
        "min_y": float(uy[0]),
        "max_y": float(uy[-1]),
        "min_z": float(uz[0]),
        "max_z": float(uz[-1]),
    }
    return grid_u8, meta


def build_dust_map_bin(
    input_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> Path:
    """Build *output_path* (dust_map_ng.bin) from *input_path* (finalmap.dat[.gz]).

    Skips the build if *output_path* already exists and *force* is False.
    Returns the output path.
    """
    input_path = Path(input_path).expanduser()
    output_path = Path(output_path).expanduser()

    if not input_path.exists():
        raise FileNotFoundError(
            f"Missing {input_path.name}. "
            "Run 'dust-pipeline rezaei2024 download --project PROJECT' first."
        )

    if output_path.exists() and not force:
        print(f"Skipping build (output exists): {output_path}")
        return output_path

    print(f"Loading {input_path.name}...")
    grid, meta = _parse_and_grid(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        header = struct.pack(
            "<III f ff ff ff II",
            meta["nx"],
            meta["ny"],
            meta["nz"],
            meta["max_density"],
            meta["min_x"],
            meta["max_x"],
            meta["min_y"],
            meta["max_y"],
            meta["min_z"],
            meta["max_z"],
            0,
            0,
        )
        f.write(header)
        f.write(grid.tobytes(order="C"))

    n_vox = meta["nx"] * meta["ny"] * meta["nz"]
    print(
        f"Wrote {output_path} "
        f"({meta['nx']}×{meta['ny']}×{meta['nz']} = {n_vox:,} voxels, "
        f"max_density={meta['max_density']:.3f} cm⁻³, "
        f"X=[{meta['min_x']:.0f},{meta['max_x']:.0f}] "
        f"Y=[{meta['min_y']:.0f},{meta['max_y']:.0f}] "
        f"Z=[{meta['min_z']:.0f},{meta['max_z']:.0f}] pc)."
    )
    return output_path
