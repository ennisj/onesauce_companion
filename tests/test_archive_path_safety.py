from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from onesauce_companion.services.archive import (
    _extended_length_path,
    _safe_member_parts,
    changed_files_for_archive,
    extract_archive,
)


@pytest.mark.parametrize(
    "member_name",
    [
        "../evil.txt",
        "content/../../evil.txt",
        "..\\evil.txt",
        "/etc/evil.txt",
        "\\evil.txt",
        "C:/evil.txt",
        "C:\\evil.txt",
        "content/file.txt:stream",
    ],
)
def test_safe_member_parts_rejects_escaping_names(member_name: str) -> None:
    with pytest.raises(ValueError, match="escapes target directory"):
        _safe_member_parts(member_name)


@pytest.mark.parametrize(
    ("member_name", "expected"),
    [
        ("content/keep.txt", ("content", "keep.txt")),
        ("content\\keep.txt", ("content", "keep.txt")),
        ("./content/./keep.txt", ("content", "keep.txt")),
        ("content//keep.txt", ("content", "keep.txt")),
    ],
)
def test_safe_member_parts_normalizes_valid_names(member_name: str, expected: tuple[str, ...]) -> None:
    assert _safe_member_parts(member_name) == expected


def test_extract_archive_rejects_traversal_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.txt", b"payload")

    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="escapes target directory"):
        extract_archive(archive_path, target)

    assert not (tmp_path / "evil.txt").exists()


def test_changed_files_rejects_traversal_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("..\\evil.txt", b"payload")

    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError, match="escapes target directory"):
        changed_files_for_archive(archive_path, target)


def test_extract_archive_handles_long_paths(tmp_path: Path) -> None:
    # Build a member whose absolute target path comfortably exceeds MAX_PATH.
    deep_member = "/".join(["directory-segment-" + str(index) for index in range(12)]) + "/file.txt"
    assert len(str(tmp_path)) + len(deep_member) > 260

    archive_path = tmp_path / "deep.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(deep_member, b"deep content")

    extract_archive(archive_path, tmp_path)

    destination = _extended_length_path(tmp_path.resolve().joinpath(*deep_member.split("/")))
    assert destination.read_bytes() == b"deep content"


def test_extended_length_path_handles_unc_and_short_paths() -> None:
    import os

    short = Path("C:/short/path.txt")
    assert _extended_length_path(short) == short

    if os.name == "nt":
        long_tail = "x" * 300
        long_local = Path("C:/data/" + long_tail)
        assert str(_extended_length_path(long_local)).startswith("\\\\?\\C:")
        long_unc = Path("//server/share/" + long_tail)
        assert str(_extended_length_path(long_unc)).startswith("\\\\?\\UNC\\")
