from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Callable

import requests

from onesauce_companion.manifest import (
    BASE_BUILD_ARCHIVE_ITEM,
    BITLCD_ARCHIVE_ITEM,
    OPTIONAL_COMPONENTS,
    REQUIRED_COMPONENTS,
    SIMPLE_BLUE_ARCHIVE_ITEM,
    build_bitlcd_marquee_spec,
    build_optional_video_spec,
)
from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.formatting import format_size_label
from onesauce_companion.services.versioning import parse_version_from_filename, version_sort_key


_SCREENSAVER_PREFIX = "ha8800_screensaver "


class ArchiveBackedComponentCatalog:
    def __init__(self, fallback_specs: tuple[ComponentSpec, ...], loader: Callable[[], tuple[ComponentSpec, ...]]) -> None:
        self._fallback_specs = fallback_specs
        self._loader = loader
        self._cached_specs: tuple[ComponentSpec, ...] | None = None
        #: True when the most recent specs() call attempted a remote refresh
        #: and fell back to cached/baked-in data. Callers surface this to the user.
        self.last_refresh_failed = False

    def is_loaded(self) -> bool:
        return self._cached_specs is not None

    def specs(self, force_refresh: bool = False) -> tuple[ComponentSpec, ...]:
        if self._cached_specs is not None and not force_refresh:
            self.last_refresh_failed = False
            return self._cached_specs
        try:
            specs = self._loader()
            if specs:
                self._cached_specs = specs
                self.last_refresh_failed = False
                return specs
        except requests.RequestException:
            pass
        self.last_refresh_failed = True
        if self._cached_specs is not None:
            return self._cached_specs
        self._cached_specs = self._fallback_specs
        return self._cached_specs


def build_required_component_specs() -> tuple[ComponentSpec, ...]:
    files = _archive_files(BASE_BUILD_ARCHIVE_ITEM)
    latest_by_prefix = _latest_files_by_prefix(files, {spec.key: _filename_prefix(spec.filename) for spec in REQUIRED_COMPONENTS})
    specs: list[ComponentSpec] = []
    for template in REQUIRED_COMPONENTS:
        file_metadata = latest_by_prefix.get(template.key)
        if file_metadata is None:
            specs.append(template)
            continue
        filename = str(file_metadata["name"])
        version = parse_version_from_filename(filename) or template.available_version
        size_bytes = _parse_size_bytes(file_metadata.get("size")) or template.size_bytes
        specs.append(
            replace(
                template,
                filename=filename,
                download_url=f"https://archive.org/download/{template.archive_item}/{requests.utils.quote(filename)}",
                available_version=version,
                size_label=format_size_label(size_bytes) if size_bytes is not None else template.size_label,
                size_bytes=size_bytes,
            )
        )
    return tuple(specs)


def build_bitlcd_component_specs() -> tuple[ComponentSpec, ...]:
    files = _archive_files(BITLCD_ARCHIVE_ITEM)
    latest_by_name: dict[str, ComponentSpec] = {}
    for file_metadata in files:
        filename = file_metadata.get("name")
        if not isinstance(filename, str) or not filename.lower().endswith(".zip"):
            continue
        version = parse_version_from_filename(filename)
        if version is None:
            continue
        size_bytes = _parse_size_bytes(file_metadata.get("size"))
        spec = build_bitlcd_marquee_spec(filename, size_bytes)
        current = latest_by_name.get(spec.display_name)
        if current is None or version_sort_key(spec.available_version) > version_sort_key(current.available_version):
            latest_by_name[spec.display_name] = spec
    return tuple(sorted(latest_by_name.values(), key=lambda spec: spec.display_name.casefold()))


def build_optional_component_specs() -> tuple[ComponentSpec, ...]:
    specs: list[ComponentSpec] = []
    simple_blue_template = next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_simple_blue")
    simple_blue_file = _latest_matching_file(_archive_files(SIMPLE_BLUE_ARCHIVE_ITEM), _filename_prefix(simple_blue_template.filename))
    if simple_blue_file is None:
        specs.append(simple_blue_template)
    else:
        filename = str(simple_blue_file["name"])
        version = parse_version_from_filename(filename) or simple_blue_template.available_version
        size_bytes = _parse_size_bytes(simple_blue_file.get("size")) or simple_blue_template.size_bytes
        specs.append(
            replace(
                simple_blue_template,
                filename=filename,
                download_url=f"https://archive.org/download/{SIMPLE_BLUE_ARCHIVE_ITEM}/{requests.utils.quote(filename)}",
                available_version=version,
                size_label=format_size_label(size_bytes) if size_bytes is not None else simple_blue_template.size_label,
                size_bytes=size_bytes,
            )
        )

    base_build_files = _archive_files(BASE_BUILD_ARCHIVE_ITEM)
    latest_optional_videos: dict[str, ComponentSpec] = {}
    for file_metadata in base_build_files:
        video_filename = file_metadata.get("name")
        if not isinstance(video_filename, str) or not video_filename.lower().endswith(".zip"):
            continue
        if not video_filename.casefold().startswith(_SCREENSAVER_PREFIX.casefold()):
            continue
        if parse_version_from_filename(video_filename) is None:
            continue
        spec = build_optional_video_spec(video_filename, _parse_size_bytes(file_metadata.get("size")))
        current = latest_optional_videos.get(spec.display_name)
        if current is None or version_sort_key(spec.available_version) > version_sort_key(current.available_version):
            latest_optional_videos[spec.display_name] = spec
    specs.extend(sorted(latest_optional_videos.values(), key=lambda spec: spec.display_name.casefold()))
    return tuple(specs)


def _archive_files(archive_item: str) -> list[dict[str, Any]]:
    response = requests.get(f"https://archive.org/metadata/{archive_item}", timeout=8)
    response.raise_for_status()
    return list(response.json().get("files", []))


def _latest_files_by_prefix(
    files: list[dict[str, Any]],
    prefixes_by_key: dict[str, str],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for key, prefix in prefixes_by_key.items():
        file_metadata = _latest_matching_file(files, prefix)
        if file_metadata is not None:
            latest[key] = file_metadata
    return latest


def _latest_matching_file(files: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for file_metadata in files:
        filename = file_metadata.get("name")
        if not isinstance(filename, str) or not filename.lower().endswith(".zip"):
            continue
        if not filename.casefold().startswith(prefix.casefold()):
            continue
        version = parse_version_from_filename(filename)
        if version is None:
            continue
        if latest is None:
            latest = file_metadata
            continue
        latest_version = parse_version_from_filename(str(latest["name"])) or ""
        if version_sort_key(version) > version_sort_key(latest_version):
            latest = file_metadata
    return latest


def _filename_prefix(filename: str) -> str:
    return re.sub(r"\s+v\d+\.\d+b\d+\.zip$", " ", filename, flags=re.IGNORECASE)


def _parse_size_bytes(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


