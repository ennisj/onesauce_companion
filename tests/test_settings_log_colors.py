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
