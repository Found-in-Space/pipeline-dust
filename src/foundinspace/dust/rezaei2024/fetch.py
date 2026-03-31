"""Fetch the 3D Milky Way dust map from CDS (Rezaei Kh. et al. 2024).

Downloads finalmap.dat.gz — the 3D distribution of dust density across the
Milky Way plane out to 10 kpc from the Sun, derived from APOGEE near-infrared
photometry using Bayesian statistics and Gaussian processes.

Reference
---------
Rezaei Kh. S., Beuther H., Benjamin R.A., Eilers A.-C., Henning T.,
    Jimenez-Donaire M.J., Miville-Deschenes M.-A. (2024)
"3D structure of the Milky Way out to 10 kpc from the Sun"
Astron. Astrophys. 692, A255
DOI: 10.1051/0004-6361/202451424
Bibcode: 2024A&A...692A.255R
VizieR: https://cdsarc.cds.unistra.fr/ftp/J/A+A/692/A255
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

_URL = "https://cdsarc.cds.unistra.fr/ftp/J/A+A/692/A255/finalmap.dat.gz"


def fetch_catalog(output_path: Path, *, force: bool = False) -> Path:
    """Download finalmap.dat.gz to *output_path*, returning the path.

    Skips the download if the file already exists and *force* is False.
    """
    output_path = Path(output_path).expanduser()
    if output_path.exists() and not force:
        return output_path

    print(f"Downloading {_URL} → {output_path}")
    _download(_URL, output_path)
    print(f"Saved {output_path} ({output_path.stat().st_size / 1_048_576:.1f} MB)")
    return output_path


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, open(dest, "wb") as f:  # noqa: S310
        while chunk := response.read(1 << 20):
            f.write(chunk)
