from __future__ import annotations

import zipfile
from dataclasses import replace
from pathlib import Path

from onesauce_companion.manifest import GAME_PACKS, HA8800_BACKGROUND_BASELINE, REQUIRED_COMPONENTS
from onesauce_companion.services.archive import changed_files_for_archive, extract_archive, primary_collection_root_for_archive
from onesauce_companion.services.installer import Installer


def test_extract_archive_skips_windows_system_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Thumbs.db", b"system")
        archive.writestr("content/keep.txt", b"hello")

    extract_archive(archive_path, tmp_path)

    assert not (tmp_path / "Thumbs.db").exists()
    assert (tmp_path / "content" / "keep.txt").read_text() == "hello"


def test_changed_files_for_archive_ignores_windows_system_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Thumbs.db", b"zip-version")
        archive.writestr("content/keep.txt", b"hello")

    (tmp_path / "Thumbs.db").write_bytes(b"different-on-disk")
    content_path = tmp_path / "content"
    content_path.mkdir()
    (content_path / "keep.txt").write_text("HELLO")

    changed = changed_files_for_archive(archive_path, tmp_path)

    assert "Thumbs.db" not in changed
    assert "content/keep.txt" in changed


def test_changed_files_for_archive_reports_progress(tmp_path: Path) -> None:
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content/one.txt", b"one")
        archive.writestr("content/two.txt", b"two")

    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "one.txt").write_text("ONE")

    progress_updates: list[tuple[int, int]] = []
    changed = changed_files_for_archive(
        archive_path,
        tmp_path,
        progress_callback=lambda current, total: progress_updates.append((current, total)),
    )

    assert "content/one.txt" in changed
    assert progress_updates
    assert progress_updates[-1] == (2, 2)


def test_extract_archive_does_not_delete_unrelated_content_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "content.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content/content version.txt", "Build v2.0b2".encode("utf-16"))

    protected = tmp_path / "content" / "retrofe" / "collections" / "Arcade" / "Arcade version.txt"
    protected.parent.mkdir(parents=True)
    protected.write_bytes("Build v2.0b4".encode("utf-16"))

    extract_archive(archive_path, tmp_path)

    assert protected.exists()


def test_installer_detects_game_pack_version_in_collection_path(tmp_path: Path) -> None:
    spec = next(component for component in GAME_PACKS if component.display_name == "Arcade")
    version_file = tmp_path / "content" / "retrofe" / "collections" / spec.install_root / "Arcade version.txt"
    version_file.parent.mkdir(parents=True)
    version_file.write_bytes("Build v2.0b4".encode("utf-16"))

    installer = Installer((spec,))
    statuses = installer.scan_target(tmp_path)

    assert len(statuses) == 1
    assert statuses[0].status == "Installed"
    assert statuses[0].installed_version == "v2.0b4"


def _ha8800_background_spec():
    return next(component for component in REQUIRED_COMPONENTS if component.key == "ha8800_background")


def test_ha8800_background_presence_assumes_baseline(tmp_path: Path) -> None:
    # Ships with no version file: presence reports the assumed baseline (not
    # the always-current "installed" sentinel), matching one_saucier.
    spec = _ha8800_background_spec()
    (tmp_path / "ha8800_background").mkdir()
    (tmp_path / "ha8800_background" / "bg1.jpg").write_bytes(b"JPEG")

    statuses = Installer((spec,)).scan_target(tmp_path)

    assert statuses[0].installed_version == HA8800_BACKGROUND_BASELINE
    assert statuses[0].status == "Installed"


def test_ha8800_background_newer_catalog_classifies_as_update(tmp_path: Path) -> None:
    # The whole point of the assumed baseline: a future versioned release is
    # no longer masked as installed.
    spec = replace(_ha8800_background_spec(), available_version="v2.0b3")
    (tmp_path / "ha8800_background").mkdir()
    (tmp_path / "ha8800_background" / "bg1.jpg").write_bytes(b"JPEG")

    statuses = Installer((spec,)).scan_target(tmp_path)

    assert statuses[0].installed_version == HA8800_BACKGROUND_BASELINE
    assert statuses[0].status == "Update Available"


def test_ha8800_background_real_version_file_wins(tmp_path: Path) -> None:
    # If a future update ships a version file, detection uses it and the
    # baseline assumption stops applying.
    spec = replace(_ha8800_background_spec(), available_version="v2.0b3")
    root = tmp_path / "ha8800_background"
    root.mkdir()
    (root / "bg1.jpg").write_bytes(b"JPEG")
    (root / "ha8800_background version.txt").write_bytes("Build v2.0b3".encode("utf-16"))

    statuses = Installer((spec,)).scan_target(tmp_path)

    assert statuses[0].installed_version == "v2.0b3"
    assert statuses[0].status == "Installed"


def test_primary_collection_root_for_archive_detects_collection_folder(tmp_path: Path) -> None:
    archive_path = tmp_path / "Arcade v2.0b5.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("content/retrofe/collections/MAME/Arcade version.txt", b"x")
        archive.writestr("appdata/retrofe/collections/MAME/settings.conf", b"list.extensions = zip")

    assert primary_collection_root_for_archive(archive_path) == "MAME"

