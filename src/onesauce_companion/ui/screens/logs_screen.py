"""Logs screen: log file selector, filter checkboxes, and syntax-highlighted viewer."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.app_logging import LOG_FILE_NAME
from onesauce_companion.services.settings import SettingsStore
from onesauce_companion.ui._log_widgets import LogColorDialog, LogSyntaxHighlighter
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_logs_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("Logs"))

    logs_group = QGroupBox("Logs")
    logs_layout = QVBoxLayout(logs_group)

    selector_panel = QWidget()
    selector_layout = QVBoxLayout(selector_panel)
    selector_layout.setContentsMargins(0, 0, 0, 0)
    selector_layout.setSpacing(8)
    selector_panel.setMinimumWidth(180)
    selector_panel.setMaximumWidth(220)

    self.log_buttons = {}
    for key, label in (
        ("retrofe", "RetroFE"),
        ("scripter", "Scripter"),
        ("sunshine", "Sunshine"),
        ("retroarch", "Retroarch"),
        ("companion", "Companion"),
    ):
        button = QPushButton(label)
        button.setObjectName("logSelectorButton")
        button.setCheckable(True)
        button.clicked.connect(lambda _checked=False, log_key=key: self._select_log(log_key))
        selector_layout.addWidget(button)
        self.log_buttons[key] = button
    selector_layout.addStretch(1)

    viewer_panel = QFrame()
    viewer_panel.setObjectName("logsViewerFrame")
    viewer_layout = QVBoxLayout(viewer_panel)
    viewer_layout.setContentsMargins(12, 12, 12, 12)
    viewer_layout.setSpacing(12)

    filters_row = QHBoxLayout()
    filters_row.setSpacing(14)
    self.log_filter_checkboxes = {}
    for key, label in (
        ("info", "Info"),
        ("debug", "Debug"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("critical", "Critical"),
        ("fatal", "Fatal"),
        ("other", "Other"),
    ):
        checkbox = QCheckBox(label)
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(lambda _state, _key=key: self._refresh_logs_screen())
        filters_row.addWidget(checkbox)
        self.log_filter_checkboxes[key] = checkbox
    filters_row.addStretch(1)
    self.log_wrap_checkbox = QCheckBox("Wrap Lines")
    self.log_wrap_checkbox.setChecked(False)
    self.log_wrap_checkbox.stateChanged.connect(self._handle_log_wrap_toggled)
    filters_row.addWidget(self.log_wrap_checkbox)
    self.log_change_colors_button = QPushButton("Change Colors")
    self.log_change_colors_button.clicked.connect(self._change_log_colors)
    filters_row.addWidget(self.log_change_colors_button)
    viewer_layout.addLayout(filters_row)

    self.logs_content_stack = QStackedWidget()
    self.logs_empty_label = QLabel("Select a log file from the left to view its contents")
    self.logs_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.logs_missing_label = QLabel("Log file is not present")
    self.logs_missing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.logs_viewer = QPlainTextEdit()
    self.logs_viewer.setReadOnly(True)
    self.logs_viewer.setFont(QFont("Consolas", 10))
    self.logs_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    self.logs_highlighter = LogSyntaxHighlighter(self.logs_viewer.document(), self._log_highlight_colors)
    self.logs_content_stack.addWidget(self.logs_empty_label)
    self.logs_content_stack.addWidget(self.logs_missing_label)
    self.logs_content_stack.addWidget(self.logs_viewer)
    self.logs_content_stack.setCurrentWidget(self.logs_empty_label)
    viewer_layout.addWidget(self.logs_content_stack, stretch=1)
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.addWidget(selector_panel)
    splitter.addWidget(viewer_panel)
    splitter.setChildrenCollapsible(False)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setSizes([200, 900])
    logs_layout.addWidget(splitter, stretch=1)

    layout.addWidget(logs_group, stretch=1)
    return screen


def refresh_logs_screen(self: "MainWindow") -> None:
    if self._selected_log_key is None:
        self.logs_content_stack.setCurrentWidget(self.logs_empty_label)
        return
    show_log_contents(self, self._selected_log_key)


def select_log(self: "MainWindow", log_key: str) -> None:
    self._selected_log_key = log_key
    for key, button in self.log_buttons.items():
        button.blockSignals(True)
        button.setChecked(key == log_key)
        button.blockSignals(False)
    show_log_contents(self, log_key)


def show_log_contents(self: "MainWindow", log_key: str) -> None:
    log_path = log_file_paths(self).get(log_key)
    if log_path is None or not log_path.exists():
        self.logs_content_stack.setCurrentWidget(self.logs_missing_label)
        return
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        self.logs_content_stack.setCurrentWidget(self.logs_missing_label)
        return
    self.logs_viewer.setPlainText(filtered_log_content(self, content))
    self.logs_content_stack.setCurrentWidget(self.logs_viewer)


def log_file_paths(self: "MainWindow") -> dict[str, Path]:
    target = self._target_dir()
    paths: dict[str, Path] = {
        "companion": SettingsStore().config_dir / LOG_FILE_NAME,
    }
    if target is None:
        return paths
    paths.update(
        {
            "retrofe": target / "retrofe.log",
            "scripter": target / "scripter.log",
            "sunshine": target / "sunshine.log",
            "retroarch": target / "appdata" / "retroarch" / "logs" / "retroarch.log",
        }
    )
    return paths


def update_log_wrap_mode(self: "MainWindow") -> None:
    self.logs_viewer.setLineWrapMode(
        QPlainTextEdit.LineWrapMode.WidgetWidth
        if self.log_wrap_checkbox.isChecked()
        else QPlainTextEdit.LineWrapMode.NoWrap
    )


def handle_log_wrap_toggled(self: "MainWindow", _state: int) -> None:
    update_log_wrap_mode(self)
    self._save_settings()


def change_log_colors(self: "MainWindow") -> None:
    dialog = LogColorDialog(self._log_highlight_colors, self)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    self._log_highlight_colors = dialog.color_map()
    self.logs_highlighter.set_color_map(self._log_highlight_colors)
    self._save_settings()
    self._refresh_logs_screen()


def filtered_log_content(self: "MainWindow", content: str) -> str:
    enabled_filters = {
        key
        for key, checkbox in self.log_filter_checkboxes.items()
        if checkbox.isChecked()
    }
    return "\n".join(
        line
        for line in content.splitlines()
        if log_level_for_line(line) in enabled_filters
    )


def log_level_for_line(line: str) -> str:
    level_patterns = (
        ("critical", r"\bCRITICAL\b|\bCritical\b|\[critical\]|\[CRITICAL\]"),
        ("fatal", r"\bFATAL\b|\bFatal\b|\[fatal\]|\[FATAL\]"),
        ("error", r"\bERROR\b|\bError\b|\[error\]|\[ERROR\]|\bTraceback\b|\bException\b"),
        ("warning", r"\bWARNING\b|\bWARN\b|\bWarning\b|\bWarn\b|\[warning\]|\[warn\]|\[WARNING\]|\[WARN\]"),
        ("info", r"\bINFO\b|\bInfo\b|\[info\]|\[INFO\]"),
        ("debug", r"\bDEBUG\b|\bDebug\b|\[debug\]|\[DEBUG\]"),
    )
    for level, pattern in level_patterns:
        if re.search(pattern, line):
            return level
    return "other"
