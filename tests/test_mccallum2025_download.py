from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from foundinspace.dust.mccallum2025.download import download_record


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _urlopen_factory(payloads: dict[str, bytes]):
    calls: list[str] = []

    def urlopen(url: str) -> _FakeResponse:
        calls.append(url)
        return _FakeResponse(payloads[url])

    return urlopen, calls


def test_download_record_downloads_files_and_writes_lock(tmp_path: Path) -> None:
    cube_payload = b"fits-ish cube"
    map_payload = b"fits-ish sky map"
    record_url = "https://zenodo.org/api/records/15041318"
    record = {
        "id": 15041318,
        "doi": "10.5281/zenodo.fake",
        "conceptdoi": "10.5281/zenodo.fake-concept",
        "files": [
            {
                "key": "ha_grid.fits",
                "checksum": f"md5:{hashlib.md5(cube_payload).hexdigest()}",
                "links": {"download": "https://example.test/ha_grid.fits"},
            },
            {
                "key": "sky_map_ha.fits",
                "checksum": f"md5:{hashlib.md5(map_payload).hexdigest()}",
                "links": {"download": "https://example.test/sky_map_ha.fits"},
            },
        ],
    }
    urlopen, calls = _urlopen_factory(
        {
            record_url: json.dumps(record).encode("utf-8"),
            "https://example.test/ha_grid.fits": cube_payload,
            "https://example.test/sky_map_ha.fits": map_payload,
        }
    )

    lock_path = download_record("15041318", tmp_path, urlopen=urlopen)

    assert lock_path == tmp_path / "files.lock.json"
    assert (tmp_path / "record.json").exists()
    assert (tmp_path / "ha_grid.fits").read_bytes() == cube_payload
    assert (tmp_path / "sky_map_ha.fits").read_bytes() == map_payload

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["record_id"] == "15041318"
    assert lock["doi"] == "10.5281/zenodo.fake"
    assert [file["filename"] for file in lock["files"]] == [
        "ha_grid.fits",
        "sky_map_ha.fits",
    ]
    assert calls == [
        record_url,
        "https://example.test/ha_grid.fits",
        "https://example.test/sky_map_ha.fits",
    ]


def test_download_record_skips_existing_file_when_checksum_matches(
    tmp_path: Path,
) -> None:
    payload = b"already here"
    (tmp_path / "ha_grid.fits").write_bytes(payload)
    record_url = "https://zenodo.org/api/records/15041318"
    record = {
        "files": [
            {
                "key": "ha_grid.fits",
                "checksum": f"md5:{hashlib.md5(payload).hexdigest()}",
                "links": {"download": "https://example.test/ha_grid.fits"},
            }
        ],
    }
    urlopen, calls = _urlopen_factory({record_url: json.dumps(record).encode("utf-8")})

    download_record("15041318", tmp_path, urlopen=urlopen)

    assert calls == [record_url]


def test_download_record_rejects_checksum_mismatch(tmp_path: Path) -> None:
    payload = b"not the advertised bytes"
    record_url = "https://zenodo.org/api/records/15041318"
    record = {
        "files": [
            {
                "key": "ha_grid.fits",
                "checksum": "md5:00000000000000000000000000000000",
                "links": {"download": "https://example.test/ha_grid.fits"},
            }
        ],
    }
    urlopen, _calls = _urlopen_factory(
        {
            record_url: json.dumps(record).encode("utf-8"),
            "https://example.test/ha_grid.fits": payload,
        }
    )

    with pytest.raises(ValueError, match="Checksum mismatch"):
        download_record("15041318", tmp_path, urlopen=urlopen)
