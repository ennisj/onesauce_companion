"""Unit tests for the self-update service (release parsing, asset selection,
zip staging safety, and the Windows apply-script generation)."""
from __future__ import annotations

import zipfile

import pytest

from onesauce_companion.services.self_update import (
    ReleaseAsset,
    ReleaseInfo,
    build_windows_apply_script,
    install_root,
    release_from_payload,
    select_platform_asset,
    stage_windows_zip,
)

_ASSETS = (
    ReleaseAsset(name="OnesaUCECompanion-windows.zip", url="https://x/win.zip", size=10),
    ReleaseAsset(name="OnesaUCECompanion-macos-arm64.dmg", url="https://x/mac.dmg", size=20),
)


def test_release_from_payload_parses_tag_and_assets() -> None:
    release = release_from_payload({
        "tag_name": "v0.4.1",
        "assets": [
            {"name": "OnesaUCECompanion-windows.zip",
             "browser_download_url": "https://x/win.zip", "size": 123},
            {"name": "", "browser_download_url": "https://x/skip"},
            "not-a-dict",
        ],
    })
    assert release is not None
    assert release.tag == "v0.4.1"
    assert [a.name for a in release.assets] == ["OnesaUCECompanion-windows.zip"]
    assert release.assets[0].size == 123


def test_release_from_payload_rejects_missing_tag() -> None:
    assert release_from_payload({"assets": []}) is None
    assert release_from_payload("nope") is None


def test_select_platform_asset() -> None:
    release = ReleaseInfo(tag="v1", assets=_ASSETS)
    assert select_platform_asset(release, "win32").name.endswith("-windows.zip")
    assert select_platform_asset(release, "darwin").name.endswith("-macos-arm64.dmg")
    assert select_platform_asset(ReleaseInfo(tag="v1", assets=()), "win32") is None


def test_install_root_is_none_when_running_from_source() -> None:
    assert install_root() is None


def _make_zip(path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_stage_windows_zip_returns_app_folder(tmp_path) -> None:
    zip_path = tmp_path / "update.zip"
    _make_zip(zip_path, {
        "OnesaUCECompanion/OnesaUCECompanion.exe": b"exe",
        "OnesaUCECompanion/assets/logo.png": b"png",
    })
    staged = stage_windows_zip(zip_path, tmp_path / "staged")
    assert staged.name == "OnesaUCECompanion"
    assert (staged / "OnesaUCECompanion.exe").read_bytes() == b"exe"
    assert (staged / "assets" / "logo.png").is_file()


def test_stage_windows_zip_rejects_archive_without_exe(tmp_path) -> None:
    zip_path = tmp_path / "bad.zip"
    _make_zip(zip_path, {"OnesaUCECompanion/readme.txt": b"hi"})
    with pytest.raises(ValueError):
        stage_windows_zip(zip_path, tmp_path / "staged")


def test_stage_windows_zip_rejects_path_traversal(tmp_path) -> None:
    zip_path = tmp_path / "evil.zip"
    _make_zip(zip_path, {
        "OnesaUCECompanion/OnesaUCECompanion.exe": b"exe",
        "../evil.txt": b"boom",
    })
    with pytest.raises(ValueError):
        stage_windows_zip(zip_path, tmp_path / "staged")
    assert not (tmp_path / "evil.txt").exists()


def test_build_windows_apply_script_contents(tmp_path) -> None:
    staged = tmp_path / "staged" / "OnesaUCECompanion"
    install = tmp_path / "install"
    script = build_windows_apply_script(staged, install, pid=4242)
    assert "Wait-Process -Id 4242" in script
    assert f'"{staged}"' in script
    assert f'"{install}"' in script
    assert "/MIR" in script
    assert "OnesaUCECompanion.exe" in script
