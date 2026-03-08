from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from onesauce_companion.models import ComponentSpec


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
        keep_names = {spec.cache_name.lower() for spec in components}
        removable = [path for path in files if _cache_key(path) not in keep_names]
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

