from __future__ import annotations

from onesauce_companion.services.settings import AppSettings, SettingsStore


def test_settings_store_round_trips_log_highlight_colors(tmp_path):
    store = SettingsStore(tmp_path)
    settings = AppSettings(log_highlight_colors={"timestamp": "#123456", "path": "#abcdef"})
    store.save(settings)

    loaded = store.load()

    assert loaded.log_highlight_colors == {"timestamp": "#123456", "path": "#abcdef"}


def test_settings_store_round_trips_log_wrap_lines(tmp_path):
    store = SettingsStore(tmp_path)
    settings = AppSettings(log_wrap_lines=True)
    store.save(settings)

    loaded = store.load()

    assert loaded.log_wrap_lines is True


def test_settings_store_defaults_themes_preview_feature_flag_to_disabled(tmp_path):
    store = SettingsStore(tmp_path)

    loaded = store.load()

    assert loaded.enable_themes_preview is False


def test_settings_store_round_trips_themes_preview_feature_flag(tmp_path):
    store = SettingsStore(tmp_path)
    settings = AppSettings(enable_themes_preview=True)
    store.save(settings)

    loaded = store.load()

    assert loaded.enable_themes_preview is True


def test_settings_store_defaults_auto_install_after_download_to_enabled(tmp_path):
    store = SettingsStore(tmp_path)

    loaded = store.load()

    assert loaded.auto_install_components_after_download is True


def test_settings_store_round_trips_auto_install_after_download(tmp_path):
    store = SettingsStore(tmp_path)
    settings = AppSettings(auto_install_components_after_download=False)
    store.save(settings)

    loaded = store.load()

    assert loaded.auto_install_components_after_download is False
