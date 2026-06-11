from __future__ import annotations

from onesauce_companion.services.tweaks import (
    AUTOSTART_STATUS_ENABLED,
    AUTOSTART_STATUS_NOT_ENABLED,
    AUTOSTART_STATUS_PENDING,
    detect_autostart_state,
    detect_onesauce_settings_state,
    detect_settings_tweaks_state,
    disable_autostart,
    enable_autostart,
    enable_legends_pinball_micro_rotation_fix,
    ensure_main_starting_collection,
    install_autostart_fix,
    update_onesauce_setting,
)


def test_detect_autostart_requires_onesauce_install(tmp_path):
    state = detect_autostart_state(tmp_path)

    assert not state.onesauce_installed
    assert state.status == AUTOSTART_STATUS_NOT_ENABLED


def test_detect_autostart_pending_when_install_script_exists(tmp_path):
    version_file = tmp_path / "OneSauce" / "OneSauce version.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text("Build v2.0b6", encoding="utf-16")
    install_script = tmp_path / "OneSauce" / "scripter" / "00_install_autostart.sh"
    install_script.parent.mkdir(parents=True, exist_ok=True)
    install_script.write_text("#!/bin/sh\n", encoding="utf-8")

    state = detect_autostart_state(tmp_path)

    assert state.onesauce_installed
    assert state.status == AUTOSTART_STATUS_PENDING


def test_detect_autostart_enabled_when_autostart_folder_exists(tmp_path):
    version_file = tmp_path / "OneSauce" / "OneSauce version.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text("Build v2.0b6", encoding="utf-16")
    autostart_dir = tmp_path / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)

    state = detect_autostart_state(tmp_path)

    assert state.status == AUTOSTART_STATUS_ENABLED


def test_enable_autostart_copies_install_script(tmp_path):
    script_source = tmp_path / "scripts" / "00_install_autostart.sh"
    script_source.parent.mkdir(parents=True, exist_ok=True)
    script_source.write_text("#!/bin/sh\n", encoding="utf-8")

    enable_autostart(tmp_path, script_source)

    assert (tmp_path / "OneSauce" / "scripter" / "00_install_autostart.sh").exists()


def test_disable_autostart_backs_up_and_removes_autostart(tmp_path):
    version_file = tmp_path / "OneSauce" / "OneSauce version.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text("Build v2.0b6", encoding="utf-16")
    autostart_dir = tmp_path / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    (autostart_dir / "boot.sh").write_text("echo hi", encoding="utf-8")
    install_script = tmp_path / "OneSauce" / "scripter" / "00_install_autostart.sh"
    install_script.parent.mkdir(parents=True, exist_ok=True)
    install_script.write_text("#!/bin/sh\n", encoding="utf-8")

    backup_dir = disable_autostart(tmp_path)

    assert backup_dir is not None
    assert (backup_dir / "boot.sh").exists()
    assert not autostart_dir.exists()
    assert not install_script.exists()


def test_install_autostart_fix_copies_fix_script(tmp_path):
    script_source = tmp_path / "scripts" / "00_init_menu.sh"
    script_source.parent.mkdir(parents=True, exist_ok=True)
    script_source.write_text("#!/bin/sh\n", encoding="utf-8")

    install_autostart_fix(tmp_path, script_source)

    assert (tmp_path / "autostart" / "00_init_menu.sh").exists()


def test_detect_settings_tweak_disabled_when_target_file_is_missing(tmp_path):
    source = tmp_path / "conf" / "settings_HA8819.conf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "# Overrides for ALP Micro\n\nhorizontal1 = 1920\nvertical1 = 1080\nrotation1 = 270\n\n"
        "# some platforms may have trouble to switch resolutions reliably. Turn this off in that case.\n"
        "enableResolutionChange = false\n",
        encoding="utf-8",
    )

    state = detect_settings_tweaks_state(tmp_path, source)

    assert not state.legends_pinball_micro_rotation_fix_enabled


def test_detect_settings_tweak_enabled_only_when_both_sections_match(tmp_path):
    source = tmp_path / "conf" / "settings_HA8819.conf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source_text = (
        "# Overrides for ALP Micro\n\nhorizontal1 = 1920\nvertical1 = 1080\nrotation1 = 270\n\n"
        "# some platforms may have trouble to switch resolutions reliably. Turn this off in that case.\n"
        "enableResolutionChange = false\n"
    )
    source.write_text(source_text, encoding="utf-8")
    target = tmp_path / "appdata" / "retrofe" / "settings_HA8819.conf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source_text, encoding="utf-8")

    state = detect_settings_tweaks_state(tmp_path, source)

    assert state.legends_pinball_micro_rotation_fix_enabled


def test_enable_legends_micro_fix_copies_source_when_target_missing(tmp_path):
    source = tmp_path / "conf" / "settings_HA8819.conf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source_text = (
        "# Overrides for ALP Micro\n\nhorizontal1 = 1920\nvertical1 = 1080\nrotation1 = 270\n\n"
        "# some platforms may have trouble to switch resolutions reliably. Turn this off in that case.\n"
        "enableResolutionChange = false\n"
    )
    source.write_text(source_text, encoding="utf-8")

    enable_legends_pinball_micro_rotation_fix(tmp_path, source)

    target = tmp_path / "appdata" / "retrofe" / "settings_HA8819.conf"
    assert target.read_text(encoding="utf-8") == source_text


def test_enable_legends_micro_fix_updates_existing_target_sections(tmp_path):
    source = tmp_path / "conf" / "settings_HA8819.conf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "# Overrides for ALP Micro\n\nhorizontal1 = 1920\nvertical1 = 1080\nrotation1 = 270\n\n"
        "# some platforms may have trouble to switch resolutions reliably. Turn this off in that case.\n"
        "enableResolutionChange = false\n",
        encoding="utf-8",
    )
    target = tmp_path / "appdata" / "retrofe" / "settings_HA8819.conf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "language = en\n\n"
        "# Overrides for ALP Micro\n\nhorizontal1 = 1111\nvertical1 = 2222\nrotation1 = 0\n\n"
        "# some platforms may have trouble to switch resolutions reliably. Turn this off in that case.\n"
        "enableResolutionChange = true\n",
        encoding="utf-8",
    )

    enable_legends_pinball_micro_rotation_fix(tmp_path, source)

    updated = target.read_text(encoding="utf-8")
    assert "horizontal1 = 1920" in updated
    assert "vertical1 = 1080" in updated
    assert "rotation1 = 270" in updated
    assert "enableResolutionChange = false" in updated


def test_detect_onesauce_settings_requires_appdata_and_base_assets(tmp_path):
    state = detect_onesauce_settings_state(tmp_path)

    assert not state.available


def test_detect_onesauce_settings_reads_current_values_without_modifying_file(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    original_content = (
        "layout = Simple Blue\nfirstCollection = Commodore 64\nrememberMenu = yes\nvideoEnable = no\ndefaultVolume = 0.5\n"
    )
    settings_path.write_text(original_content, encoding="utf-8")
    (tmp_path / "base_assets" / "layouts" / "Simple Blue").mkdir(parents=True, exist_ok=True)
    (tmp_path / "base_assets" / "layouts" / "Default").mkdir(parents=True, exist_ok=True)

    state = detect_onesauce_settings_state(tmp_path)

    assert state.available
    assert state.values["layout"] == "Simple Blue"
    assert state.values["firstCollection"] == "Commodore 64"
    assert state.values["rememberMenu"] == "yes"
    assert state.values["defaultVolume"] == "0.5"
    assert "Simple Blue" in state.themes
    assert settings_path.read_text(encoding="utf-8") == original_content


def test_ensure_main_starting_collection_repairs_drifted_value(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("layout = Default\nfirstCollection = Commodore 64\n", encoding="utf-8")

    assert ensure_main_starting_collection(tmp_path) is True
    assert "firstCollection = Main" in settings_path.read_text(encoding="utf-8")


def test_ensure_main_starting_collection_adds_missing_value(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("layout = Default\nrememberMenu = yes\n", encoding="utf-8")

    assert ensure_main_starting_collection(tmp_path) is True
    assert "firstCollection = Main" in settings_path.read_text(encoding="utf-8")


def test_ensure_main_starting_collection_is_noop_when_already_main(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    original_content = "layout = Default\nfirstCollection = Main\n"
    settings_path.write_text(original_content, encoding="utf-8")

    assert ensure_main_starting_collection(tmp_path) is False
    assert settings_path.read_text(encoding="utf-8") == original_content


def test_ensure_main_starting_collection_is_noop_without_settings_file(tmp_path):
    assert ensure_main_starting_collection(tmp_path) is False
    assert ensure_main_starting_collection(None) is False
    assert not (tmp_path / "appdata").exists()


def test_update_onesauce_setting_rewrites_existing_line(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("layout = Default\nfirstCollection = MAME\n", encoding="utf-8")

    update_onesauce_setting(tmp_path, "layout", "Simple Blue")

    updated = settings_path.read_text(encoding="utf-8")
    assert "layout = Simple Blue" in updated
    assert "firstCollection = MAME" in updated


def test_update_onesauce_setting_uncomments_existing_attribute(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("# writeLauncherLog = yes\n", encoding="utf-8")

    update_onesauce_setting(tmp_path, "writeLauncherLog", "no")

    updated = settings_path.read_text(encoding="utf-8")
    assert "writeLauncherLog = no" in updated
    assert "# writeLauncherLog = yes" not in updated


def test_update_onesauce_setting_removes_duplicate_commented_and_uncommented_entries(tmp_path):
    settings_path = tmp_path / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "# writeLauncherLog = yes\n"
        "writeLauncherLog = no\n"
        "layout = Default\n",
        encoding="utf-8",
    )

    update_onesauce_setting(tmp_path, "writeLauncherLog", "yes")

    updated = settings_path.read_text(encoding="utf-8")
    assert updated.count("writeLauncherLog = yes") == 1
    assert "writeLauncherLog = no" not in updated
    assert "# writeLauncherLog = yes" not in updated
