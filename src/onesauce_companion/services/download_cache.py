from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Iterable
from zipfile import BadZipFile

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.archive import inspect_archive
from onesauce_companion.services.versioning import version_sort_key


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


def find_cached_download(
    downloads_dir: Path,
    spec: ComponentSpec,
    *,
    files: list[Path] | None = None,
) -> Path | None:
    cached = _best_matching_cached_archive(downloads_dir, spec, files=files)
    if cached is None:
        return None
    return cached[0]


def cached_download_version(
    downloads_dir: Path,
    spec: ComponentSpec,
    *,
    files: list[Path] | None = None,
) -> str | None:
    cached = _best_matching_cached_archive(downloads_dir, spec, files=files)
    if cached is not None:
        path, version = cached
        if version is not None:
            return version
        if path.name.casefold() == spec.cache_name.casefold():
            return spec.available_version
    return None


def list_cached_archive_files(downloads_dir: Path) -> list[Path]:
    """Return the sorted list of cached archive/partial files under ``downloads_dir``.

    Callers iterating many specs should pre-compute this once and pass it via
    the ``files=`` kwarg to avoid an ``rglob`` per spec.
    """
    return _cache_files(downloads_dir)


def _best_matching_cached_archive(
    downloads_dir: Path,
    spec: ComponentSpec,
    *,
    files: list[Path] | None = None,
) -> tuple[Path, str | None] | None:
    expected_version = spec.available_version.strip()
    candidates = _matching_cached_archives(downloads_dir, spec, files=files)
    if not candidates:
        return None
    if not expected_version:
        return candidates[0]
    exact_name_match = next((item for item in candidates if item[0].name.casefold() == spec.cache_name.casefold()), None)
    if exact_name_match is not None:
        _, version = exact_name_match
        # Trust the filename when version is unreadable (e.g. versionless game packs), or
        # when the embedded version already meets the requirement.
        if version is None or version_sort_key(version) >= version_sort_key(expected_version):
            return exact_name_match
    acceptable = [
        (path, version)
        for path, version in candidates
        if version is not None and version_sort_key(version) >= version_sort_key(expected_version)
    ]
    if not acceptable:
        return None
    return max(
        acceptable,
        key=lambda item: (
            version_sort_key(item[1] or ""),
            item[0].name.casefold() == spec.cache_name.casefold(),
            item[0].stat().st_mtime_ns,
        ),
    )


def _best_matching_partial_archive(downloads_dir: Path, spec: ComponentSpec) -> tuple[Path, str | None] | None:
    candidates = _matching_partial_archives(downloads_dir, spec)
    if not candidates:
        return None
    exact_names = {
        f"{spec.cache_name}.part".casefold(),
        f"{spec.cache_name}.zip.part".casefold(),
    }
    exact_name_match = next((item for item in candidates if item[0].name.casefold() in exact_names), None)
    if exact_name_match is not None:
        return exact_name_match
    return max(
        candidates,
        key=lambda item: (
            version_sort_key(item[1] or ""),
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
            best = _best_matching_cached_archive(downloads_dir, spec, files=files)
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
        removable = []
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


def _matching_partial_archives(
    downloads_dir: Path,
    spec: ComponentSpec,
    *,
    files: list[Path] | None = None,
) -> list[tuple[Path, str | None]]:
    candidates = files or _cache_files(downloads_dir)
    prefix = _cache_name_prefix(spec)
    matches: list[tuple[Path, str | None]] = []
    for path in candidates:
        if path.suffix.lower() != ".part":
            continue
        normalized_name = _cache_key(path)
        if normalized_name != spec.cache_name.casefold() and not normalized_name.startswith(prefix):
            continue
        version = _version_from_cache_filename(path.name)
        matches.append((path, version))
    return matches


# Inspecting an archive opens its zip central directory; with many specs
# matching the same cached files this dominated cache-policy enforcement.
# Keyed on (path, file id, mtime, size, version-file relpath): st_ino changes
# when a finished download replaces the file, covering rewrites that land
# within the filesystem's mtime granularity.
_INSPECTION_CACHE: dict[tuple[str, int, int, int, str | None], str | None] = {}
_INSPECTION_CACHE_MAX_ENTRIES = 1024


def _cached_archive_version(path: Path, spec: ComponentSpec) -> str | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    cache_key = (
        str(path),
        stat_result.st_ino,
        stat_result.st_mtime_ns,
        stat_result.st_size,
        spec.version_file_relpath,
    )
    if cache_key in _INSPECTION_CACHE:
        return _INSPECTION_CACHE[cache_key]
    try:
        inspection = inspect_archive(path, spec)
        version = inspection.embedded_version or inspection.release_version
    except (BadZipFile, OSError, ValueError):
        version = None
    if len(_INSPECTION_CACHE) >= _INSPECTION_CACHE_MAX_ENTRIES:
        _INSPECTION_CACHE.clear()
    _INSPECTION_CACHE[cache_key] = version
    return version


def _cache_name_prefix(spec: ComponentSpec) -> str:
    match = re.search(r"v\d+\.\d+b\d+", spec.cache_name, re.IGNORECASE)
    if not match:
        return Path(spec.cache_name).stem.casefold()
    return spec.cache_name[:match.start()].casefold()


def _version_from_cache_filename(filename: str) -> str | None:
    match = re.search(r"v\d+\.\d+b\d+", filename, re.IGNORECASE)
    if match is None:
        return None
    return match.group(0)


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

