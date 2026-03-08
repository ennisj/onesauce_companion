from __future__ import annotations

import shutil
import zlib
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path

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


def changed_files_for_archive(
    archive_path: Path,
    target_dir: Path,
    controller: OperationController | None = None,
    component_key: str | None = None,
) -> list[str]:
    changed: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if controller:
                controller.wait_if_paused(component_key)
            if info.is_dir() or _should_skip_member(info.filename):
                continue
            target_path = _safe_target_path(target_dir, info.filename)
            if not target_path.exists():
                continue
            if target_path.stat().st_size != info.file_size:
                changed.append(info.filename)
                continue
            if _file_crc32(target_path) != info.CRC:
                changed.append(info.filename)
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
            controller.wait_if_paused(component_key)
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


def extract_archive(
    archive_path: Path,
    target_dir: Path,
    controller: OperationController | None = None,
    component_key: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        total = len(members)
        for index, info in enumerate(members, start=1):
            if controller:
                controller.wait_if_paused(component_key)
            if _should_skip_member(info.filename):
                if progress_callback:
                    progress_callback(index, total, info.filename)
                continue
            destination = _safe_target_path(target_dir, info.filename)
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


def _safe_target_path(target_dir: Path, member_name: str) -> Path:
    base = target_dir.resolve()
    destination = (target_dir / member_name).resolve()
    if not destination.is_relative_to(base):
        raise ValueError(f"Archive entry escapes target directory: {member_name}")
    return destination


def _should_skip_member(member_name: str) -> bool:
    return Path(member_name).name.lower() in WINDOWS_SYSTEM_FILENAMES

