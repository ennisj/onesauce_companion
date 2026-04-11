from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Iterable
from zipfile import BadZipFile

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.archive import inspect_archive


DEFAULT_RETENTION_MODE = "latest"
RETENTION_MODES = {"delete", "latest", "days", "space"}


@dataclass(frozen=True)
class CacheCleanupResult:
    deleted_files: int
    freed_bytes: int


def default_downloads_dir() -> Path:
    new_dir = Path.home() / ".onesauce_companion" / "downloads"
    if new_dir.exists():
        return new_dir
    for legacy_dir in (
        Path.home() / ".onesauce_updater" / "downloads",
        Path.home() / ".onesauce" / "downloads",
    ):
        if legacy_dir.exists():
            return legacy_dir
    return new_dir


def clear_downloads_dir(downloads_dir: Path) -> CacheCleanupResult:
    return _delete_paths(_cache_files(downloads_dir))


def find_cached_download(downloads_dir: Path, spec: ComponentSpec) -> Path | None:
    cached = _best_matching_cached_archive(downloads_dir, spec)
    if cached is None:
        return None
    return cached[0]


def cached_download_version(downloads_dir: Path, spec: ComponentSpec) -> str | None:
    cached = _best_matching_cached_archive(downloads_dir, spec)
    if cached is None:
        return None
    return cached[1]


def _best_matching_cached_archive(downloads_dir: Path, spec: ComponentSpec) -> tuple[Path, str | None] | None:
    expected_version = spec.available_version.strip()
    candidates = _matching_cached_archives(downloads_dir, spec)
    if not candidates:
        return None
    if not expected_version:
        return candidates[0]
    acceptable = [
        (path, version)
        for path, version in candidates
        if version is not None and _version_sort_key(version) >= _version_sort_key(expected_version)
    ]
    if not acceptable:
        return None
    return max(
        acceptable,
        key=lambda item: (
            _version_sort_key(item[1] or ""),
            item[0].name.casefold() == spec.cache_name.casefold(),
            item[0].stat().st_mtime_ns,
        ),
    )


def enforce_download_cache_policy(
    downloads_dir: Path,
    mode: str,
    components: Iterable[ComponentSpec],
    *,
    days: int = 30,
    max_gb: float = 5.0,
) -> CacheCleanupResult:
    normalized_mode = mode if mode in RETENTION_MODES else DEFAULT_RETENTION_MODE
    downloads_dir.mkdir(parents=True, exist_ok=True)

    if normalized_mode == "delete":
        return clear_downloads_dir(downloads_dir)

    files = _cache_files(downloads_dir)
    if normalized_mode == "latest":
        keep_paths: set[Path] = set()
        for spec in components:
            candidates = _matching_cached_archives(downloads_dir, spec, files=files)
            if not candidates:
                continue
            best = _best_matching_cached_archive(downloads_dir, spec)
            if best is None:
                continue
            keep_paths.add(best[0])
        removable = [path for path in files if path.suffix.lower() == ".zip" and path not in keep_paths]
        return _delete_paths(removable)

    if normalized_mode == "days":
        cutoff = datetime.now() - timedelta(days=max(0, days))
        removable = [path for path in files if datetime.fromtimestamp(path.stat().st_mtime) < cutoff]
        return _delete_paths(removable)

    if normalized_mode == "space":
        max_bytes = max(0, int(max_gb * 1_000_000_000))
        total_bytes = sum(path.stat().st_size for path in files)
        if total_bytes <= max_bytes:
            return CacheCleanupResult(deleted_files=0, freed_bytes=0)
        removable: list[Path] = []
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            removable.append(path)
            total_bytes -= path.stat().st_size
            if total_bytes <= max_bytes:
                break
        return _delete_paths(removable)

    return CacheCleanupResult(deleted_files=0, freed_bytes=0)


def _cache_files(downloads_dir: Path) -> list[Path]:
    if not downloads_dir.exists():
        return []
    return sorted(
        (
            path
            for path in downloads_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".zip", ".part"}
        ),
        key=lambda item: item.name.casefold(),
    )


def _cache_key(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".part"):
        return name[:-5]
    return name


def _matching_cached_archives(
    downloads_dir: Path,
    spec: ComponentSpec,
    *,
    files: list[Path] | None = None,
) -> list[tuple[Path, str | None]]:
    candidates = files or _cache_files(downloads_dir)
    prefix = _cache_name_prefix(spec)
    matches: list[tuple[Path, str | None]] = []
    for path in candidates:
        if path.suffix.lower() != ".zip":
            continue
        if path.name.casefold() != spec.cache_name.casefold() and not path.name.casefold().startswith(prefix):
            continue
        version = _cached_archive_version(path, spec)
        if version is None and path.name.casefold() != spec.cache_name.casefold():
            continue
        matches.append((path, version))
    return matches


def _cached_archive_version(path: Path, spec: ComponentSpec) -> str | None:
    try:
        inspection = inspect_archive(path, spec)
    except (BadZipFile, OSError, ValueError):
        return None
    return inspection.embedded_version or inspection.release_version


def _cache_name_prefix(spec: ComponentSpec) -> str:
    match = re.search(r"v\d+\.\d+b\d+", spec.cache_name, re.IGNORECASE)
    if not match:
        return Path(spec.cache_name).stem.casefold()
    return spec.cache_name[:match.start()].casefold()


def _version_sort_key(value: str) -> tuple[int, int, int, str]:
    match = re.match(r"v(\d+)\.(\d+)b(\d+)", value, re.IGNORECASE)
    if not match:
        return (0, 0, 0, value.casefold())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), value.casefold())


def _delete_paths(paths: Iterable[Path]) -> CacheCleanupResult:
    deleted_files = 0
    freed_bytes = 0
    for path in paths:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
        deleted_files += 1
        freed_bytes += size
    return CacheCleanupResult(deleted_files=deleted_files, freed_bytes=freed_bytes)

