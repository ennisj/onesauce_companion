"""Install guard: swaps OnesaUCE screens for a warning when no install folder is available.

Cabinet Link made a local OnesaUCE install optional (users can push downloads
straight to the cabinet), but the screens in the OnesaUCE sidebar section
browse the local install. Each of those screens is wrapped in a QStackedWidget
holding the real screen and an :class:`InstallRequiredPanel`; the sync helpers
pick which page shows based on the configured Target Folder.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.ui._constants import (
    COLLECTIONS_SCREEN,
    GAMES_SCREEN,
    SETTINGS_SCREEN,
    THEMES_SCREEN,
    TWEAKS_SCREEN,
)
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


INSTALL_GUARDED_SCREEN_TITLES = {
    GAMES_SCREEN: "Games",
    COLLECTIONS_SCREEN: "Collections",
    THEMES_SCREEN: "Themes",
    TWEAKS_SCREEN: "OnesaUCE Settings",
}

_NOT_CONFIGURED_MESSAGE = (
    "No OnesaUCE install folder is configured. If you only download components and "
    "push them to your cabinet with Cabinet Link, you don't need one — but this "
    "screen browses a local OnesaUCE installation and can't be used without it.\n\n"
    "To use this screen, choose your OnesaUCE Target Folder in Settings."
)


class InstallRequiredPanel(QWidget):
    """Full-page warning shown in place of a screen that needs a local install."""

    def __init__(self, window: "MainWindow", screen_title: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(build_screen_header_row(screen_title))

        card = QWidget()
        card.setObjectName("warningBanner")
        card.setMaximumWidth(640)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(14)

        icon_label = QLabel()
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(44, 44))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(icon_label)

        headline = QLabel("OnesaUCE installation not found")
        headline.setObjectName("installRequiredTitle")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setWordWrap(True)
        card_layout.addWidget(headline)

        self._message = QLabel("")
        self._message.setObjectName("warningMessage")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        card_layout.addWidget(self._message)

        settings_button = QPushButton("Go to Settings")
        settings_button.setMinimumWidth(160)
        settings_button.clicked.connect(lambda: window._change_screen(SETTINGS_SCREEN))
        card_layout.addWidget(settings_button, 0, Qt.AlignmentFlag.AlignHCenter)

        card_row = QHBoxLayout()
        card_row.addStretch(1)
        card_row.addWidget(card)
        card_row.addStretch(1)

        layout.addStretch(2)
        layout.addLayout(card_row)
        layout.addStretch(3)

    def set_state(self, target: Path | None) -> None:
        if target is None:
            self._message.setText(_NOT_CONFIGURED_MESSAGE)
            return
        self._message.setText(
            f"The configured OnesaUCE install folder can't be found:\n\n{target}\n\n"
            "Reconnect the drive, or choose a different Target Folder in Settings."
        )


def install_target_missing(self: "MainWindow") -> bool:
    target = self._target_dir()
    return target is None or not target.is_dir()


def wrap_with_install_guard(self: "MainWindow", screen_index: int, content: QWidget) -> QStackedWidget:
    panel = InstallRequiredPanel(self, INSTALL_GUARDED_SCREEN_TITLES[screen_index])
    guard = QStackedWidget()
    guard.addWidget(content)  # page 0 — the real screen
    guard.addWidget(panel)  # page 1 — the warning
    self._install_guard_stacks[screen_index] = guard
    self._install_guard_panels[screen_index] = panel
    sync_install_guard(self, screen_index)
    return guard


def sync_install_guard(self: "MainWindow", screen_index: int) -> None:
    guard = self._install_guard_stacks.get(screen_index)
    panel = self._install_guard_panels.get(screen_index)
    if guard is None or panel is None:
        return
    if install_target_missing(self):
        panel.set_state(self._target_dir())
        guard.setCurrentIndex(1)
    else:
        guard.setCurrentIndex(0)


def sync_install_guards(self: "MainWindow") -> None:
    for screen_index in tuple(self._install_guard_stacks):
        sync_install_guard(self, screen_index)
    # The Logs screen stays usable without an install (the Companion log is
    # local), but shows a banner explaining why the drive logs are absent.
    banner = getattr(self, "logs_no_install_banner", None)
    if banner is not None:
        banner.setVisible(install_target_missing(self))
