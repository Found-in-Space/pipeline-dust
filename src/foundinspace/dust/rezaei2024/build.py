"""Build dust_map.bin from finalmap.dat.gz — 3D dust in ICRS for star overlay.

Reads the APOGEE-based dust map (Galactic l, b, distance) and converts to
ICRS Cartesian parsecs to match the foundinspace star coordinate convention.

Output binary format (dust_map.bin)
------------------------------------
  4 bytes  : float32  grid_half_size_pc
  N * 16 bytes : float32[4] per point — X, Y, Z (ICRS pc), Density (cm⁻³)

Grid half-size is half the median nearest-neighbour distance, so rendered cubes
fill the volume without gaps.

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
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import ICRS, Galactic


def parse_finalmap(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Parse fixed-width finalmap.dat[.gz] into coordinate and density arrays.

    Returns
    -------
    coords : ndarray, shape (N, 3)
        Galactic longitude (deg), latitude (deg), distance (pc).
    density : ndarray, shape (N,), float32
        Particle number density (cm⁻³).
    """
    open_fn = gzip.open if str(path).endswith(".gz") else open
    mode = "rt"

    glon, glat, dist, density = [], [], [], []
    with open_fn(path, mode) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            glon.append(float(line[0:6]))
            glat.append(float(line[7:13]))
            dist.append(float(line[14:22]))
            density.append(float(line[23:29]))

    coords = np.column_stack([glon, glat, dist])
    return coords, np.array(density, dtype=np.float32)


def galactic_to_icrs(
    glon_deg: np.ndarray, glat_deg: np.ndarray, dist_pc: np.ndarray
) -> np.ndarray:
    """Convert Galactic (l, b, d) heliocentric to ICRS Cartesian parsecs.

    Matches the coordinate system used by foundinspace star parquet outputs.

    Returns
    -------
    ndarray, shape (N, 3), float32 — X, Y, Z in ICRS parsecs.
    """
    gal = Galactic(
        l=glon_deg * u.deg,
        b=glat_deg * u.deg,
        distance=dist_pc * u.pc,
    )
    icrs = gal.transform_to(ICRS())
    cart = icrs.cartesian
    return np.column_stack(
        [
            cart.x.to_value(u.pc),
            cart.y.to_value(u.pc),
            cart.z.to_value(u.pc),
        ]
    ).astype(np.float32)


def compute_grid_half_size_pc(xyz_pc: np.ndarray, sample_size: int = 500) -> float:
    """Estimate grid cell half-size from median nearest-neighbour distance.

    Samples *sample_size* points and finds the nearest neighbour in the full
    set.  Returns half the median spacing so rendered cubes touch at edges.
    """
    n = len(xyz_pc)
    rng = np.random.default_rng(42)
    idx = rng.choice(n, min(sample_size, n), replace=False)
    sample = xyz_pc[idx]
    nn_dists = []
    for pt in sample:
        d = np.sqrt(((xyz_pc - pt) ** 2).sum(axis=1))
        d[d < 1e-6] = np.inf
        nn_dists.append(float(d.min()))
    return float(np.median(nn_dists) / 2)


def build_dust_map_bin(
    input_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> Path:
    """Build *output_path* (dust_map.bin) from *input_path* (finalmap.dat[.gz]).

    Skips the build if *output_path* already exists and *force* is False.
    Returns the output path.
    """
    input_path = Path(input_path).expanduser()
    output_path = Path(output_path).expanduser()

    if not input_path.exists():
        raise FileNotFoundError(
            f"Missing {input_path.name}. "
            "Run 'dust-pipeline rezaei2024 fetch --project PROJECT' first."
        )

    if output_path.exists() and not force:
        print(f"Skipping build (output exists): {output_path}")
        return output_path

    print(f"Loading {input_path.name}...")
    coords, density = parse_finalmap(input_path)
    glon, glat, dist = coords[:, 0], coords[:, 1], coords[:, 2]

    print("Converting Galactic → ICRS (matches star coordinates)...")
    xyz_icrs = galactic_to_icrs(glon, glat, dist)

    print("Computing grid cell half-size (median NN distance / 2)...")
    grid_half_pc = compute_grid_half_size_pc(xyz_icrs)
    print(f"  Grid half-size: {grid_half_pc:.2f} pc")

    point_cloud = np.empty((len(density), 4), dtype=np.float32)
    point_cloud[:, 0] = xyz_icrs[:, 0]
    point_cloud[:, 1] = xyz_icrs[:, 1]
    point_cloud[:, 2] = xyz_icrs[:, 2]
    point_cloud[:, 3] = density

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        np.array([grid_half_pc], dtype=np.float32).tofile(f)
        point_cloud.flatten().tofile(f)

    print(
        f"Wrote {output_path} "
        f"({len(density):,} points, ICRS pc + density, "
        f"grid half={grid_half_pc:.1f} pc)."
    )
    return output_path
