from __future__ import annotations

import zipfile

import pytest

from onesauce_companion.services import disk_space
from onesauce_companion.services.archive import required_extract_bytes
from onesauce_companion.services.disk_space import (
    InsufficientDiskSpaceError,
    ensure_free_space,
    free_bytes_for_path,
)


def test_free_bytes_walks_up_to_existing_ancestor(tmp_path) -> None:
    missing = tmp_path / "not" / "created" / "yet"

    free = free_bytes_for_path(missing)

    assert free is not None
    assert free > 0
    assert free == free_bytes_for_path(tmp_path)


def test_ensure_free_space_raises_with_readable_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(disk_space, "free_bytes_for_path", lambda path: 1024)

    with pytest.raises(InsufficientDiskSpaceError) as exc_info:
        ensure_free_space(tmp_path, 5 * 1024**3, "install Sony PlayStation")

    message = str(exc_info.value)
    assert "install Sony PlayStation" in message
    assert "5.0 GB" in message
    assert "1.0 KB" in message


def test_ensure_free_space_passes_when_space_is_sufficient(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(disk_space, "free_bytes_for_path", lambda path: 10_000)

    ensure_free_space(tmp_path, 9_999, "download Component")


def test_ensure_free_space_skips_unknown_volumes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(disk_space, "free_bytes_for_path", lambda path: None)

    ensure_free_space(tmp_path, 10**15, "install Component")


def test_ensure_free_space_skips_zero_requirement(tmp_path) -> None:
    ensure_free_space(tmp_path, 0, "install Component")


def test_required_extract_bytes_counts_new_changed_and_backup_bytes(tmp_path) -> None:
    archive_path = tmp_path / "component.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("root/new_file.bin", b"x" * 100)
        archive.writestr("root/changed_file.bin", b"y" * 200)
        archive.writestr("root/unchanged_file.bin", b"z" * 300)
        archive.writestr("root/thumbs.db", b"w" * 400)

    target_dir = tmp_path / "target"
    (target_dir / "root").mkdir(parents=True)
    (target_dir / "root" / "changed_file.bin").write_bytes(b"old" * 10)  # 30 bytes on disk
    (target_dir / "root" / "unchanged_file.bin").write_bytes(b"z" * 300)

    required = required_extract_bytes(archive_path, target_dir, ["root/changed_file.bin"])

    # new file (100) + changed replacement (200) + backup of existing changed file (30);
    # unchanged and Windows-system entries cost nothing.
    assert required == 100 + 200 + 30
