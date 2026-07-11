"""Install guard: OnesaUCE screens swap to a warning when no install folder is available."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from onesauce_companion.ui._constants import COLLECTIONS_SCREEN, GAMES_SCREEN
from onesauce_companion.ui.screens.install_guard import (
    install_target_missing,
    sync_install_guard,
    sync_install_guards,
    wrap_with_install_guard,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _window(target: Path | None = None) -> SimpleNamespace:
    _app()
    window = SimpleNamespace(
        _install_guard_stacks={},
        _install_guard_panels={},
        _change_screen=lambda index: None,
    )
    window.target = target
    window._target_dir = lambda: window.target
    return window


# ---------------------------------------------------------------------------
# install_target_missing
# ---------------------------------------------------------------------------

def test_install_target_missing_when_not_configured():
    assert install_target_missing(_window(None))


def test_install_target_missing_when_folder_absent(tmp_path):
    assert install_target_missing(_window(tmp_path / "gone"))


def test_install_target_present(tmp_path):
    assert not install_target_missing(_window(tmp_path))


# ---------------------------------------------------------------------------
# wrap_with_install_guard / sync_install_guard
# ---------------------------------------------------------------------------

def test_wrap_shows_warning_without_target():
    window = _window(None)
    guard = wrap_with_install_guard(window, GAMES_SCREEN, QWidget())
    assert guard.currentIndex() == 1


def test_wrap_shows_content_with_target(tmp_path):
    window = _window(tmp_path)
    content = QWidget()
    guard = wrap_with_install_guard(window, GAMES_SCREEN, content)
    assert guard.currentIndex() == 0
    assert guard.currentWidget() is content


def test_sync_follows_target_changes(tmp_path):
    window = _window(None)
    guard = wrap_with_install_guard(window, COLLECTIONS_SCREEN, QWidget())
    assert guard.currentIndex() == 1

    window.target = tmp_path
    sync_install_guard(window, COLLECTIONS_SCREEN)
    assert guard.currentIndex() == 0

    window.target = tmp_path / "unplugged"
    sync_install_guard(window, COLLECTIONS_SCREEN)
    assert guard.currentIndex() == 1


def test_sync_ignores_screens_that_are_not_built():
    window = _window(None)
    sync_install_guard(window, GAMES_SCREEN)  # must not raise


# ---------------------------------------------------------------------------
# InstallRequiredPanel messaging
# ---------------------------------------------------------------------------

def test_panel_message_for_unconfigured_target_mentions_settings_and_cabinet_link():
    window = _window(None)
    wrap_with_install_guard(window, GAMES_SCREEN, QWidget())
    message = window._install_guard_panels[GAMES_SCREEN]._message.text()
    assert "Settings" in message
    assert "Cabinet Link" in message


def test_panel_message_names_the_missing_folder(tmp_path):
    missing = tmp_path / "gone"
    window = _window(missing)
    wrap_with_install_guard(window, GAMES_SCREEN, QWidget())
    assert str(missing) in window._install_guard_panels[GAMES_SCREEN]._message.text()


# ---------------------------------------------------------------------------
# sync_install_guards (all screens + Logs banner)
# ---------------------------------------------------------------------------

def test_sync_install_guards_toggles_logs_banner(tmp_path):
    window = _window(None)
    banner = QWidget()
    banner.hide()
    window.logs_no_install_banner = banner

    sync_install_guards(window)
    assert not banner.isHidden()

    window.target = tmp_path
    sync_install_guards(window)
    assert banner.isHidden()


def test_sync_install_guards_updates_every_wrapped_screen(tmp_path):
    window = _window(None)
    games_guard = wrap_with_install_guard(window, GAMES_SCREEN, QWidget())
    collections_guard = wrap_with_install_guard(window, COLLECTIONS_SCREEN, QWidget())
    assert games_guard.currentIndex() == 1
    assert collections_guard.currentIndex() == 1

    window.target = tmp_path
    sync_install_guards(window)
    assert games_guard.currentIndex() == 0
    assert collections_guard.currentIndex() == 0
