from __future__ import annotations

import os
import shutil
import zlib
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from pathlib import PurePosixPath

from onesauce_companion.models import ArchiveInspection, ComponentSpec
from onesauce_companion.services.control import OperationController
from onesauce_companion.services.versioning import decode_version_text, parse_build_version, parse_version_from_filename

WINDOWS_SYSTEM_FILENAMES = {"thumbs.db", "desktop.ini", "ehthumbs.db"}


def inspect_archive(archive_path: Path, spec: ComponentSpec) -> ArchiveInspection:
    with zipfile.ZipFile(archive_path) as archive:
        embedded_version = None
        version_file_path = None
        if spec.version_file_relpath and spec.version_file_relpath in archive.namelist():
            version_file_path = spec.version_file_relpath
            embedded_version = parse_build_version(decode_version_text(archive.read(spec.version_file_relpath)))
        return ArchiveInspection(
            archive_path=archive_path,
            release_version=parse_version_from_filename(archive_path.name),
            embedded_version=embedded_version,
            version_file_path=version_file_path,
            entry_count=len(archive.infolist()),
        )


def primary_collection_root_for_archive(archive_path: Path) -> str | None:
    collection_roots = collection_roots_for_archive(archive_path)
    if not collection_roots:
        return None
    return collection_roots[0]


def collection_roots_for_archive(archive_path: Path) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if len(parts) < 4:
                continue
            if parts[0].casefold() not in {"content", "appdata"}:
                continue
            if parts[1].casefold() != "retrofe" or parts[2].casefold() != "collections":
                continue
            counts[parts[3]] = counts.get(parts[3], 0) + 1
    return tuple(
        name
        for name, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    )


def changed_files_for_archive(
    archive_path: Path,
    target_dir: Path,
    controller: OperationController | None = None,
    component_key: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[str]:
    changed: list[str] = []
    resolved_base = target_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        total = len(members)
        for index, info in enumerate(members, start=1):
            if controller:
                controller.raise_if_paused(component_key)
            if info.is_dir() or _should_skip_member(info.filename):
                if progress_callback:
                    progress_callback(index, total)
                continue
            target_path = _safe_target_path(resolved_base, info.filename)
            if not target_path.exists():
                if progress_callback:
                    progress_callback(index, total)
                continue
            if target_path.stat().st_size != info.file_size:
                changed.append(info.filename)
                if progress_callback:
                    progress_callback(index, total)
                continue
            if _file_crc32(target_path) != info.CRC:
                changed.append(info.filename)
            if progress_callback:
                progress_callback(index, total)
    return changed


def backup_existing_files(
    target_dir: Path,
    backup_dir: Path,
    relative_paths: Iterable[str],
    controller: OperationController | None = None,
    component_key: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    relative_path_list = list(relative_paths)
    total = len(relative_path_list)
    count = 0
    for index, relative_path in enumerate(relative_path_list, start=1):
        if controller:
            controller.raise_if_paused(component_key)
        source = target_dir / relative_path
        if not source.exists():
            if progress_callback:
                progress_callback(index, total)
            continue
        if _should_skip_member(relative_path):
            if progress_callback:
                progress_callback(index, total)
            continue
        destination = backup_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except PermissionError:
            if _should_skip_member(relative_path):
                if progress_callback:
                    progress_callback(index, total)
                continue
            raise
        count += 1
        if progress_callback:
            progress_callback(index, total)
    return count


def required_extract_bytes(
    archive_path: Path,
    target_dir: Path,
    changed_paths: Iterable[str],
) -> int:
    """Estimate the bytes of free space an extraction will consume.

    Counts the uncompressed size of entries that do not exist on the target
    plus, for entries known to differ (``changed_paths``), the uncompressed
    size of the replacement and the size of the existing file (which is
    copied into the backup directory on the same volume).
    """
    changed = set(changed_paths)
    required = 0
    resolved_base = target_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or _should_skip_member(info.filename):
                continue
            target_path = _safe_target_path(resolved_base, info.filename)
            try:
                existing_size = target_path.stat().st_size if target_path.exists() else None
            except OSError:
                existing_size = None
            if existing_size is None:
                required += info.file_size
            elif info.filename in changed:
                required += info.file_size + existing_size
    return required


def extract_archive(
    archive_path: Path,
    target_dir: Path,
    controller: OperationController | None = None,
    component_key: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    resolved_base = target_dir.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        total = len(members)
        for index, info in enumerate(members, start=1):
            if controller:
                controller.raise_if_paused(component_key)
            if _should_skip_member(info.filename):
                if progress_callback:
                    progress_callback(index, total, info.filename)
                continue
            destination = _safe_target_path(resolved_base, info.filename)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(info, "r") as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
                except PermissionError:
                    if _should_skip_member(info.filename):
                        if progress_callback:
                            progress_callback(index, total, info.filename)
                        continue
                    raise
            if progress_callback:
                progress_callback(index, total, info.filename)


def _file_crc32(path: Path) -> int:
    crc = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


# Roughly MAX_PATH minus slack; beyond this Windows file APIs need the
# \\?\ extended-length prefix unless long paths are enabled system-wide.
_WINDOWS_LONG_PATH_THRESHOLD = 248


def _safe_member_parts(member_name: str) -> tuple[str, ...]:
    """Validate an archive member name lexically and return its path parts.

    Rejects absolute paths, drive letters / NTFS streams, and parent-directory
    traversal so the joined path cannot escape the target directory. Purely
    lexical: no filesystem access per member (``Path.resolve`` per entry is
    prohibitively slow on Windows for 100k-entry game packs).
    """
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        raise ValueError(f"Archive entry escapes target directory: {member_name}")
    parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
    if not parts or ".." in parts:
        raise ValueError(f"Archive entry escapes target directory: {member_name}")
    return parts


def _safe_target_path(resolved_base: Path, member_name: str) -> Path:
    """Join a pre-resolved base directory with a validated member name.

    ``resolved_base`` must already be resolved (once per archive operation).
    """
    destination = resolved_base.joinpath(*_safe_member_parts(member_name))
    return _extended_length_path(destination)


def _extended_length_path(path: Path) -> Path:
    """Apply the Windows ``\\\\?\\`` prefix to long absolute paths.

    Deep ROM/media trees routinely exceed MAX_PATH; without the prefix,
    stat/open/mkdir fail on systems that have not opted into long paths.
    """
    if os.name != "nt":
        return path
    text = str(path)
    if len(text) < _WINDOWS_LONG_PATH_THRESHOLD or text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def _should_skip_member(member_name: str) -> bool:
    return Path(member_name).name.lower() in WINDOWS_SYSTEM_FILENAMES

