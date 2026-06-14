from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from onesauce_companion.services.games import GameManifestEntry
from onesauce_companion.ui.screens import themes_screen


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _build_window() -> SimpleNamespace:
    _app()
    collection_filter = QComboBox()
    collection_filter.addItem("Arcade", "Arcade")
    themes = SimpleNamespace(
        selected_game_key=None,
        selected_collection_name="Arcade",
        preview_previous_stopped_game_key="stale",
        preview_last_stopped_game_key="stale",
    )
    return SimpleNamespace(
        _themes=themes,
        themes_collection_filter=collection_filter,
        themes_game_filter=QComboBox(),
    )


def _entry(name: str, rom_path: str) -> GameManifestEntry:
    return GameManifestEntry(
        game_name=name,
        collection_name="Arcade",
        rom_path=rom_path,
        source_pack="Arcade",
        install_collection_name="Arcade",
    )


def test_sync_themes_game_filter_selects_first_game_when_none_selected(monkeypatch) -> None:
    window = _build_window()
    first = _entry("Alpha", "alpha.zip")
    second = _entry("Bravo", "bravo.zip")
    monkeypatch.setattr(themes_screen, "_theme_games_for_collection", lambda *_args: (first, second))

    themes_screen._sync_themes_game_filter(window)

    assert window.themes_game_filter.count() == 2
    assert window.themes_game_filter.itemText(0) == "Alpha"
    assert window.themes_game_filter.currentIndex() == 0
    assert window.themes_game_filter.currentData() == first
    assert window._themes.selected_game_key == first.key
    assert window._themes.preview_previous_stopped_game_key is None
    assert window._themes.preview_last_stopped_game_key == first.key


def test_sync_themes_game_filter_keeps_matching_selection(monkeypatch) -> None:
    window = _build_window()
    first = _entry("Alpha", "alpha.zip")
    second = _entry("Bravo", "bravo.zip")
    window._themes.selected_game_key = second.key
    monkeypatch.setattr(themes_screen, "_theme_games_for_collection", lambda *_args: (first, second))

    themes_screen._sync_themes_game_filter(window)

    assert window.themes_game_filter.currentIndex() == 1
    assert window.themes_game_filter.currentData() == second
    assert window._themes.selected_game_key == second.key


def test_sync_themes_game_filter_shows_static_option_only_when_empty(monkeypatch) -> None:
    window = _build_window()
    monkeypatch.setattr(themes_screen, "_theme_games_for_collection", lambda *_args: tuple())

    themes_screen._sync_themes_game_filter(window)

    assert window.themes_game_filter.count() == 1
    assert window.themes_game_filter.itemText(0) == "No games available"
    assert window.themes_game_filter.currentData() is None
    assert window._themes.selected_game_key is None
