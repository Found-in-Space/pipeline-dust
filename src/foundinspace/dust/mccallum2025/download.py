"""Download McCallum et al. 2025 H-alpha source files from Zenodo."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

ZENODO_RECORD_API = "https://zenodo.org/api/records/{record_id}"

UrlOpener = Callable[[str], BinaryIO]


def download_record(
    record_id: str,
    output_dir: Path,
    *,
    force: bool = False,
    urlopen: UrlOpener = urllib.request.urlopen,
) -> Path:
    """Download every file in a pinned Zenodo record and write provenance files.

    Existing files are verified against Zenodo checksums and skipped unless
    *force* is true. Returns the written lockfile path.
    """
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    record_url = ZENODO_RECORD_API.format(record_id=record_id)
    record = _read_json(record_url, urlopen=urlopen)
    files = [_normalise_file_entry(entry) for entry in record.get("files", [])]
    if not files:
        raise ValueError(f"Zenodo record {record_id} did not list any files")

    (output_dir / "record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    locked_files = []
    for entry in files:
        destination = output_dir / entry["filename"]
        expected = entry["checksum"]
        if destination.exists() and not force:
            _verify_checksum(destination, expected)
        else:
            print(f"Downloading {entry['filename']} -> {destination}")
            _download(entry["url"], destination, urlopen=urlopen)
            _verify_checksum(destination, expected)

        locked_files.append(
            {
                "filename": entry["filename"],
                "checksum": expected,
                "size_bytes": destination.stat().st_size,
                "url": entry["url"],
            }
        )

    lock = {
        "record_id": str(record_id),
        "doi": record.get("doi"),
        "conceptdoi": record.get("conceptdoi"),
        "record_url": record_url,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "files": locked_files,
    }
    lock_path = output_dir / "files.lock.json"
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return lock_path


def _read_json(url: str, *, urlopen: UrlOpener) -> dict[str, Any]:
    with urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalise_file_entry(entry: dict[str, Any]) -> dict[str, str]:
    filename = entry.get("key") or entry.get("filename")
    checksum = entry.get("checksum")
    links = entry.get("links") or {}
    url = links.get("download") or links.get("self")
    if not isinstance(filename, str) or not filename:
        raise ValueError(f"Zenodo file entry is missing a filename: {entry!r}")
    if not isinstance(checksum, str) or ":" not in checksum:
        raise ValueError(f"Zenodo file {filename!r} is missing a typed checksum")
    if not isinstance(url, str) or not url:
        raise ValueError(f"Zenodo file {filename!r} is missing a download URL")
    return {"filename": filename, "checksum": checksum, "url": url}


def _download(url: str, destination: Path, *, urlopen: UrlOpener) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url) as response, destination.open("wb") as fp:
        while chunk := response.read(1 << 20):
            fp.write(chunk)


def _verify_checksum(path: Path, expected: str) -> None:
    algorithm, expected_digest = expected.split(":", 1)
    algorithm = algorithm.lower()
    try:
        hasher = hashlib.new(algorithm)
    except ValueError as exc:
        raise ValueError(f"Unsupported checksum algorithm {algorithm!r}") from exc

    with path.open("rb") as fp:
        while chunk := fp.read(1 << 20):
            hasher.update(chunk)

    actual_digest = hasher.hexdigest()
    if actual_digest.lower() != expected_digest.lower():
        raise ValueError(
            f"Checksum mismatch for {path}: expected {expected}, got {algorithm}:{actual_digest}"
        )
