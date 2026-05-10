from __future__ import annotations

import re
from typing import Any

import requests

from onesauce_companion.manifest import GAME_PACKS, GAME_PACKS_ARCHIVE_ITEM, build_system_pack_spec
from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.versioning import parse_version_from_filename


_SYSTEM_PACK_NAME_PATTERN = re.compile(r"\s+v\d+\.\d+b\d+\.zip$", re.IGNORECASE)
_VERSION_PATTERN = re.compile(r"v(\d+)\.(\d+)b(\d+)", re.IGNORECASE)


class SystemPackCatalogService:
    def __init__(self) -> None:
        self._cached_specs: tuple[ComponentSpec, ...] | None = None

    def is_loaded(self) -> bool:
        return self._cached_specs is not None

    def specs(self, force_refresh: bool = False) -> tuple[ComponentSpec, ...]:
        if self._cached_specs is not None and not force_refresh:
            return self._cached_specs

        try:
            response = requests.get(f"https://archive.org/metadata/{GAME_PACKS_ARCHIVE_ITEM}", timeout=8)
            response.raise_for_status()
            specs = build_system_pack_specs_from_archive_files(response.json().get("files", []))
            if specs:
                self._cached_specs = specs
                return specs
        except requests.RequestException:
            pass

        if self._cached_specs is not None:
            return self._cached_specs
        self._cached_specs = GAME_PACKS
        return self._cached_specs


def build_system_pack_specs_from_archive_files(files: list[dict[str, Any]]) -> tuple[ComponentSpec, ...]:
    latest_by_name: dict[str, ComponentSpec] = {}
    for file_metadata in files:
        filename = file_metadata.get("name")
        if not isinstance(filename, str) or not filename.lower().endswith(".zip"):
            continue
        version = parse_version_from_filename(filename)
        if version is None:
            continue
        name = _system_pack_name_from_filename(filename)
        if not name:
            continue
        size_bytes = _parse_size_bytes(file_metadata.get("size"))
        spec = build_system_pack_spec(name, version, size_bytes)
        current = latest_by_name.get(name)
        if current is None or _version_sort_key(spec.available_version) > _version_sort_key(current.available_version):
            latest_by_name[name] = spec
    return tuple(sorted(latest_by_name.values(), key=lambda spec: spec.display_name.casefold()))


def _system_pack_name_from_filename(filename: str) -> str:
    return _SYSTEM_PACK_NAME_PATTERN.sub("", filename).strip()


def _parse_size_bytes(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _version_sort_key(value: str) -> tuple[int, int, int, str]:
    match = _VERSION_PATTERN.match(value)
    if not match:
        return (0, 0, 0, value.casefold())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), value.casefold())
