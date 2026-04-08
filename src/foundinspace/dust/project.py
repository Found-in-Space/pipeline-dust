"""Project-file loader for pipeline-dust.

Reads a TOML project file containing dataset sections. Paths are
resolved relative to the project file directory; env-variable syntax ($...)
is rejected.

Example project.toml
--------------------
format_version = 1

[rezaei2024]
catalog_gz = "data/catalogs/finalmap.dat.gz"
output_bin = "data/processed/dust_map_ng.bin"

[mccallum2025]
record_id = "15041318"
raw_dir = "data/raw/zenodo/mccallum_2025"
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

FORMAT_VERSION = 1

_REZAEI2024_KEYS = {"catalog_gz", "output_bin"}
_MCCALLUM2025_KEYS = {"record_id", "raw_dir"}


def _reject_env_expansion(value: str, *, field_name: str) -> None:
    if "$" in value:
        raise ValueError(
            f"{field_name} must not contain environment-variable syntax: {value!r}"
        )


def _resolve_path(project_dir: Path, value: str, *, field_name: str) -> Path:
    _reject_env_expansion(value, field_name=field_name)
    raw = Path(value)
    return raw if raw.is_absolute() else project_dir / raw


def _require_str(raw: dict[str, Any], key: str, *, field_name: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _reject_unknown_keys(
    raw: dict[str, Any], *, allowed: set[str], table_name: str
) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"Unknown key(s) in [{table_name}]: {', '.join(unknown)}")


class _SectionAccessor:
    def __init__(
        self, section_name: str, raw: dict[str, Any] | None, project_dir: Path
    ) -> None:
        self._section = section_name
        self._raw = raw
        self._project_dir = project_dir

    @property
    def is_configured(self) -> bool:
        """True if this section was present in the project file."""
        return self._raw is not None

    def _require_path(self, key: str) -> Path:
        if self._raw is None:
            raise ValueError(f"Missing [{self._section}] table in project file")
        value = _require_str(self._raw, key, field_name=f"{self._section}.{key}")
        return _resolve_path(
            self._project_dir, value, field_name=f"{self._section}.{key}"
        )


class Rezaei2024Config(_SectionAccessor):
    """Configuration for the Rezaei et al. 2024 dust map source."""

    @property
    def catalog_gz(self) -> Path:
        """Path to finalmap.dat.gz (or finalmap.dat)."""
        return self._require_path("catalog_gz")

    @property
    def output_bin(self) -> Path:
        """Path for the built dust_map_ng.bin artifact."""
        return self._require_path("output_bin")


class McCallum2025Config(_SectionAccessor):
    """Configuration for the McCallum et al. 2025 H-alpha source data."""

    @property
    def record_id(self) -> str:
        """Pinned Zenodo record id."""
        if self._raw is None:
            raise ValueError(f"Missing [{self._section}] table in project file")
        return _require_str(self._raw, "record_id", field_name="mccallum2025.record_id")

    @property
    def raw_dir(self) -> Path:
        """Directory for downloaded Zenodo files and provenance lockfiles."""
        return self._require_path("raw_dir")


@dataclass(frozen=True, slots=True)
class DustProject:
    project_path: Path
    rezaei2024: Rezaei2024Config
    mccallum2025: McCallum2025Config

    def require(self, *section_names: str) -> None:
        """Raise ValueError listing all missing required sections at once."""
        known: dict[str, _SectionAccessor] = {
            self.rezaei2024._section: self.rezaei2024,
            self.mccallum2025._section: self.mccallum2025,
        }
        unknown = sorted(set(section_names) - set(known))
        if unknown:
            raise ValueError(
                f"require() called with unknown section name(s): {', '.join(unknown)}"
            )
        missing = [n for n in section_names if not known[n].is_configured]
        if missing:
            raise ValueError(
                "Missing required config sections: "
                + ", ".join(f"[{n}]" for n in missing)
            )


def load_project(project_path: Path) -> DustProject:
    """Load and validate a dust pipeline project TOML file.

    Unknown top-level sections are silently ignored so this project file can
    coexist with found-in-space-pipeline sections in the same TOML.
    """
    resolved = project_path.expanduser().resolve()
    with resolved.open("rb") as fp:
        raw = tomllib.load(fp)

    if not isinstance(raw, dict):
        raise ValueError("Project file root must be a TOML table")

    format_version = raw.get("format_version")
    if format_version != FORMAT_VERSION:
        raise ValueError(
            f"format_version must be {FORMAT_VERSION}, got {format_version!r}"
        )

    project_dir = resolved.parent

    rezaei_raw = raw.get("rezaei2024")
    if rezaei_raw is not None:
        if not isinstance(rezaei_raw, dict):
            raise ValueError("Invalid [rezaei2024] table in project file")
        _reject_unknown_keys(
            rezaei_raw, allowed=_REZAEI2024_KEYS, table_name="rezaei2024"
        )

    mccallum_raw = raw.get("mccallum2025")
    if mccallum_raw is not None:
        if not isinstance(mccallum_raw, dict):
            raise ValueError("Invalid [mccallum2025] table in project file")
        _reject_unknown_keys(
            mccallum_raw, allowed=_MCCALLUM2025_KEYS, table_name="mccallum2025"
        )

    return DustProject(
        project_path=resolved,
        rezaei2024=Rezaei2024Config("rezaei2024", rezaei_raw, project_dir),
        mccallum2025=McCallum2025Config("mccallum2025", mccallum_raw, project_dir),
    )


def render_project_template() -> str:
    return (
        f"format_version = {FORMAT_VERSION}\n\n"
        "[rezaei2024]\n"
        'catalog_gz = "data/catalogs/finalmap.dat.gz"\n'
        'output_bin = "data/processed/dust_map_ng.bin"\n'
        "\n"
        "[mccallum2025]\n"
        'record_id = "15041318"\n'
        'raw_dir = "data/raw/zenodo/mccallum_2025"\n'
    )
