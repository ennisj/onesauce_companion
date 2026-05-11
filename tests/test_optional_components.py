from __future__ import annotations

from dataclasses import replace

from onesauce_companion.manifest import OPTIONAL_COMPONENTS
from onesauce_companion.services.installer import Installer


def test_optional_component_detects_installed_version(tmp_path):
    version_path = tmp_path / "base_assets" / "Simple Blue version.txt"
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text("Build v2.0b5", encoding="utf-16")

    installer = Installer(OPTIONAL_COMPONENTS)
    statuses = installer.scan_target(tmp_path)

    simple_blue = next(status for status in statuses if status.spec.display_name == "Simple Blue Theme")
    assert simple_blue.installed_version == "v2.0b5"
    assert simple_blue.status == "Installed"


def test_optional_theme_without_version_file_uses_base_assets_version(tmp_path):
    theme_root = tmp_path / "base_assets" / "layouts" / "Simple Blue"
    theme_root.mkdir(parents=True, exist_ok=True)
    (theme_root / "theme.xml").write_text("<theme />", encoding="utf-8")
    base_assets_version_path = tmp_path / "base_assets" / "base_assets version.txt"
    base_assets_version_path.write_text("Build v2.0b18", encoding="utf-16")

    installer = Installer(OPTIONAL_COMPONENTS)
    statuses = installer.scan_target(tmp_path)

    simple_blue = next(status for status in statuses if status.spec.display_name == "Simple Blue Theme")
    assert simple_blue.installed_version == "v2.0b18"
    assert simple_blue.status == "Installed"


def test_optional_theme_version_file_overrides_base_assets_version(tmp_path):
    theme_root = tmp_path / "base_assets" / "layouts" / "Simple Blue"
    theme_root.mkdir(parents=True, exist_ok=True)
    (theme_root / "theme.xml").write_text("<theme />", encoding="utf-8")
    (tmp_path / "base_assets" / "base_assets version.txt").write_text("Build v2.0b18", encoding="utf-16")
    (tmp_path / "base_assets" / "Simple Blue version.txt").write_text("Build v2.0b5", encoding="utf-16")

    installer = Installer(OPTIONAL_COMPONENTS)
    statuses = installer.scan_target(tmp_path)

    simple_blue = next(status for status in statuses if status.spec.display_name == "Simple Blue Theme")
    assert simple_blue.installed_version == "v2.0b5"
    assert simple_blue.status == "Installed"


def test_optional_video_component_creates_version_file_and_can_detect_future_update(tmp_path):
    video_spec = next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_ha8800_screensaver_attract")
    install_root = tmp_path / "ha8800_screensaver"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "000 - Frosty's Arcade.mp4").write_bytes(b"demo")

    installer = Installer((video_spec,))
    statuses = installer.scan_target(tmp_path)

    version_file = install_root / "ha8800_screensaver Attract Version.txt"
    assert version_file.exists()
    assert statuses[0].installed_version == video_spec.available_version
    assert statuses[0].status == "Installed"

    newer_spec = replace(
        video_spec,
        filename="ha8800_screensaver Attract v2.0b7.zip",
        available_version="v2.0b7",
    )
    updated_statuses = Installer((newer_spec,)).scan_target(tmp_path)

    assert updated_statuses[0].installed_version == video_spec.available_version
    assert updated_statuses[0].status == "Update Available"


def test_optional_jukebox_component_detects_letter_range_and_creates_version_file(tmp_path):
    video_spec = next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_ha8800_screensaver_k_mg")
    install_root = tmp_path / "ha8800_screensaver"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "Maze Craze.mp4").write_bytes(b"demo")

    statuses = Installer((video_spec,)).scan_target(tmp_path)

    version_file = install_root / "ha8800_screensaver K-Mg Version.txt"
    assert version_file.exists()
    assert statuses[0].installed_version == video_spec.available_version
    assert statuses[0].status == "Installed"


def test_optional_num_a_jukebox_ignores_attract_mode_files(tmp_path):
    video_spec = next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_ha8800_screensaver_num_a")
    install_root = tmp_path / "ha8800_screensaver"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "000 - Frosty's Arcade.mp4").write_bytes(b"demo")

    statuses = Installer((video_spec,)).scan_target(tmp_path)

    assert statuses[0].installed_version is None
    assert statuses[0].status == "Missing"


def test_optional_num_a_jukebox_detects_a_titles(tmp_path):
    video_spec = next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_ha8800_screensaver_num_a")
    install_root = tmp_path / "ha8800_screensaver"
    install_root.mkdir(parents=True, exist_ok=True)
    (install_root / "Abba - Dancing Queen.mp4").write_bytes(b"demo")

    statuses = Installer((video_spec,)).scan_target(tmp_path)

    assert statuses[0].installed_version == video_spec.available_version
    assert statuses[0].status == "Installed"


def test_optional_video_removes_stale_version_file_when_content_is_missing(tmp_path):
    video_spec = next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_ha8800_screensaver_attract")
    install_root = tmp_path / "ha8800_screensaver"
    install_root.mkdir(parents=True, exist_ok=True)
    version_file = install_root / "ha8800_screensaver Attract Version.txt"
    version_file.write_bytes("Build v2.0b6".encode("utf-16"))

    statuses = Installer((video_spec,)).scan_target(tmp_path)

    assert statuses[0].installed_version is None
    assert statuses[0].status == "Missing"
    assert not version_file.exists()
