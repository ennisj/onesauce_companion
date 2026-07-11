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
from onesauce_companion.ui.screens.install_guard import install_target_missing
from onesauce_companion.ui.workers import LogLoadWorker

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


LOG_TAIL_BYTES = 2 * 1024 * 1024  # 2 MB tail-load by default
ALL_LOG_LEVELS = frozenset({"info", "debug", "warning", "error", "critical", "fatal", "other"})


def build_logs_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("Logs"))

    self.logs_no_install_banner = self._build_target_warning(
        "The OnesaUCE install folder is not available, so only the Companion log can be "
        "shown. The RetroFE, Scripter, Sunshine, and Retroarch logs live on the OnesaUCE "
        "install drive."
    )
    layout.addWidget(self.logs_no_install_banner)

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
    self.log_wrap_checkbox.stateChanged.connect(self._handle_log_wrap_toggled)
    filters_row.addWidget(self.log_wrap_checkbox)
    self.log_reverse_checkbox.stateChanged.connect(self._handle_log_reverse_toggled)
    filters_row.addWidget(self.log_reverse_checkbox)
    self.log_change_colors_button = QPushButton("Change Colors")
    self.log_change_colors_button.clicked.connect(self._change_log_colors)
    filters_row.addWidget(self.log_change_colors_button)
    viewer_layout.addLayout(filters_row)

    self.logs_truncation_banner = QFrame()
    self.logs_truncation_banner.setObjectName("logsTruncationBanner")
    truncation_layout = QHBoxLayout(self.logs_truncation_banner)
    truncation_layout.setContentsMargins(8, 6, 8, 6)
    truncation_layout.setSpacing(10)
    self.logs_truncation_label = QLabel("")
    self.logs_truncation_label.setWordWrap(True)
    self.logs_load_full_button = QPushButton("Load full file")
    self.logs_load_full_button.clicked.connect(self._load_full_log)
    truncation_layout.addWidget(self.logs_truncation_label, 1)
    truncation_layout.addWidget(self.logs_load_full_button)
    self.logs_truncation_banner.hide()
    viewer_layout.addWidget(self.logs_truncation_banner)

    self.logs_content_stack = QStackedWidget()
    self.logs_empty_label = QLabel("Select a log file from the left to view its contents")
    self.logs_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.logs_missing_label = QLabel("Log file is not present")
    self.logs_missing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.logs_loading_label = QLabel("Loading log… Please Wait")
    self.logs_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.logs_viewer = QPlainTextEdit()
    self.logs_viewer.setReadOnly(True)
    self.logs_viewer.setFont(QFont("Consolas", 10))
    self.logs_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    self.logs_highlighter = LogSyntaxHighlighter(self.logs_viewer.document(), self._log_highlight_colors)
    self.logs_content_stack.addWidget(self.logs_empty_label)
    self.logs_content_stack.addWidget(self.logs_missing_label)
    self.logs_content_stack.addWidget(self.logs_loading_label)
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
    self.logs_no_install_banner.setVisible(install_target_missing(self))
    if self._selected_log_key is None:
        self.logs_content_stack.setCurrentWidget(self.logs_empty_label)
        self.logs_truncation_banner.hide()
        return
    if self._loaded_log_key == self._selected_log_key and self._loaded_log_raw_content is not None:
        # Just re-filter the cached raw content; no re-read.
        _apply_loaded_log_content(self)
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
        self.logs_truncation_banner.hide()
        self._loaded_log_key = None
        self._loaded_log_raw_content = None
        return
    _start_log_load(self, log_key, log_path, max_bytes=LOG_TAIL_BYTES)


def load_full_log(self: "MainWindow") -> None:
    log_key = self._selected_log_key
    if log_key is None:
        return
    log_path = log_file_paths(self).get(log_key)
    if log_path is None or not log_path.exists():
        return
    _start_log_load(self, log_key, log_path, max_bytes=None)


def _start_log_load(self: "MainWindow", log_key: str, log_path: Path, max_bytes: int | None) -> None:
    self.logs_content_stack.setCurrentWidget(self.logs_loading_label)
    self.logs_truncation_banner.hide()

    worker = LogLoadWorker(log_key, log_path, max_bytes)
    # Bound-method slots run on the GUI thread (queued connection), which is
    # required to safely mutate widgets. Stale results are discarded by the
    # log_key check in the handlers, so a superseding load is safe.
    worker.finished.connect(self._handle_log_load_finished)
    worker.failed.connect(self._handle_log_load_failed)
    self._log_load_handle.start(
        worker,
        finish_signals=(worker.finished, worker.failed),
        on_cleared=self._finalize_close_if_ready,
    )


def on_log_load_finished(self: "MainWindow", log_key: str, content: str, truncated: bool) -> None:
    if log_key != self._selected_log_key:
        return  # user moved on; discard stale result
    self._loaded_log_key = log_key
    self._loaded_log_raw_content = content
    self._loaded_log_was_truncated = truncated
    _apply_loaded_log_content(self)


def on_log_load_failed(self: "MainWindow", log_key: str) -> None:
    if log_key != self._selected_log_key:
        return
    self._loaded_log_key = None
    self._loaded_log_raw_content = None
    self.logs_content_stack.setCurrentWidget(self.logs_missing_label)
    self.logs_truncation_banner.hide()


def _apply_loaded_log_content(self: "MainWindow") -> None:
    content = self._loaded_log_raw_content or ""
    rendered = filtered_log_content(self, content)
    if self.log_reverse_checkbox.isChecked():
        rendered = "\n".join(reversed(rendered.split("\n")))
    self.logs_viewer.setPlainText(rendered)
    self.logs_content_stack.setCurrentWidget(self.logs_viewer)
    if self._loaded_log_was_truncated:
        size_mb = len(content.encode("utf-8", errors="replace")) / (1024 * 1024)
        self.logs_truncation_label.setText(
            f"Showing the last ~{size_mb:.1f} MB of this log. Click \"Load full file\" to load everything."
        )
        self.logs_truncation_banner.show()
    else:
        self.logs_truncation_banner.hide()


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


def handle_log_reverse_toggled(self: "MainWindow", _state: int) -> None:
    if self._loaded_log_raw_content is not None and self._loaded_log_key == self._selected_log_key:
        _apply_loaded_log_content(self)
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
    if enabled_filters >= ALL_LOG_LEVELS:
        return content
    return "\n".join(
        line
        for line in content.splitlines()
        if log_level_for_line(line) in enabled_filters
    )


_LEVEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("critical", re.compile(r"\bCRITICAL\b|\bCritical\b|\[critical\]|\[CRITICAL\]")),
    ("fatal", re.compile(r"\bFATAL\b|\bFatal\b|\[fatal\]|\[FATAL\]")),
    ("error", re.compile(r"\bERROR\b|\bError\b|\[error\]|\[ERROR\]|\bTraceback\b|\bException\b")),
    ("warning", re.compile(r"\bWARNING\b|\bWARN\b|\bWarning\b|\bWarn\b|\[warning\]|\[warn\]|\[WARNING\]|\[WARN\]")),
    ("info", re.compile(r"\bINFO\b|\bInfo\b|\[info\]|\[INFO\]")),
    ("debug", re.compile(r"\bDEBUG\b|\bDebug\b|\[debug\]|\[DEBUG\]")),
)


def log_level_for_line(line: str) -> str:
    for level, pattern in _LEVEL_PATTERNS:
        if pattern.search(line):
            return level
    return "other"
