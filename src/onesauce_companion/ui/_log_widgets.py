"""Log viewer widgets: syntax highlighter and color-picker dialog."""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_LOG_HIGHLIGHT_COLORS = {
    "timestamp": "#c792ea",
    "info": "#8ad4ff",
    "debug": "#7ed0c3",
    "warning": "#f2c14e",
    "error": "#ff7d7d",
    "bracket": "#7fb3ff",
    "path": "#b6d78c",
}

LOG_HIGHLIGHT_LABELS = (
    ("timestamp", "Timestamps and Dates"),
    ("info", "Info"),
    ("debug", "Debug"),
    ("warning", "Warning"),
    ("error", "Error / Exception"),
    ("bracket", "Other Bracketed Text"),
    ("path", "Paths"),
)


class LogSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document, color_map: dict[str, str] | None = None) -> None:
        super().__init__(document)
        self._color_map = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
        if color_map:
            self._color_map.update(color_map)
        self._formats: list[tuple[str, QTextCharFormat]] = []
        self._rebuild_formats()

    def set_color_map(self, color_map: dict[str, str]) -> None:
        self._color_map = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
        self._color_map.update(color_map)
        self._rebuild_formats()
        self.rehighlight()

    def _rebuild_formats(self) -> None:
        self._formats.clear()

        timestamp_format = QTextCharFormat()
        timestamp_format.setForeground(QColor(self._color_map["timestamp"]))
        self._formats.append((r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\b", timestamp_format))
        self._formats.append((r"\b\d{2}/\d{2}/\d{4}(?: \d{2}:\d{2}:\d{2})?\b", timestamp_format))
        self._formats.append((r"\b\d{2}-\d{2}-\d{4}(?: \d{2}:\d{2}:\d{2})?\b", timestamp_format))
        self._formats.append((r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2} \d{4}\b", timestamp_format))
        self._formats.append((r"\[\d{2}:\d{2}:\d{2}\]", timestamp_format))
        self._formats.append((r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\]", timestamp_format))
        self._formats.append((r"\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2} \d{4}\]", timestamp_format))
        self._formats.append((r"\b\d{4}-\d{2}-\d{2}\b", timestamp_format))
        self._formats.append((r"\b\d{2}/\d{2}/\d{4}\b", timestamp_format))
        self._formats.append((r"\b\d{2}-\d{2}-\d{4}\b", timestamp_format))

        info_format = QTextCharFormat()
        info_format.setForeground(QColor(self._color_map["info"]))
        info_format.setFontWeight(QFont.Weight.DemiBold)
        self._formats.append((r"\bINFO\b|\bInfo\b|\[info\]|\[INFO\]", info_format))

        debug_format = QTextCharFormat()
        debug_format.setForeground(QColor(self._color_map["debug"]))
        debug_format.setFontWeight(QFont.Weight.DemiBold)
        self._formats.append((r"\bDEBUG\b|\bDebug\b|\[debug\]|\[DEBUG\]", debug_format))

        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor(self._color_map["warning"]))
        warning_format.setFontWeight(QFont.Weight.Bold)
        self._formats.append((r"\bWARNING\b|\bWARN\b|\bWarning\b|\bWarn\b|\[warning\]|\[warn\]|\[WARNING\]|\[WARN\]", warning_format))

        error_format = QTextCharFormat()
        error_format.setForeground(QColor(self._color_map["error"]))
        error_format.setFontWeight(QFont.Weight.Bold)
        self._formats.append(
            (
                r"\bERROR\b|\bCRITICAL\b|\bFATAL\b|\bError\b|\bCritical\b|\bFatal\b|\[error\]|\[critical\]|\[fatal\]|\[ERROR\]|\[CRITICAL\]|\[FATAL\]|\bTraceback\b|\bException\b",
                error_format,
            )
        )

        bracket_format = QTextCharFormat()
        bracket_format.setForeground(QColor(self._color_map["bracket"]))
        self._formats.append(
            (
                r"\[(?!(?:\d{2}:\d{2}:\d{2}\]|"
                r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\]|"
                r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2} \d{4}\]|"
                r"(?i:info|debug|warning|warn|error|critical|fatal)\]))[^\]\r\n]+\]",
                bracket_format,
            )
        )

        path_format = QTextCharFormat()
        path_format.setForeground(QColor(self._color_map["path"]))
        self._formats.append((r"[A-Za-z]:\\[^\s]+", path_format))
        self._formats.append(
            (
                r"(?:[A-Za-z]:\\|\.{1,2}[\\/]|[\\/])(?:[^\\/\r\n]+(?: [^\\/\r\n]+)*[\\/])*[^\\/\r\n]+(?: [^\\/\r\n]+)*",
                path_format,
            )
        )

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        for pattern, text_format in self._formats:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), text_format)


class LogColorDialog(QDialog):
    def __init__(self, color_map: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Log Colors")
        self._color_map = dict(color_map)
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for row, (key, label_text) in enumerate(LOG_HIGHLIGHT_LABELS):
            label = QLabel(label_text)
            button = QPushButton(self._color_map[key])
            button.setMinimumWidth(110)
            button.clicked.connect(lambda _checked=False, color_key=key: self._choose_color(color_key))
            self._buttons[key] = button
            self._sync_color_button(color_key=key)
            grid.addWidget(label, row, 0)
            grid.addWidget(button, row, 1)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        actions.addWidget(cancel_button)
        actions.addWidget(save_button)
        layout.addLayout(actions)

    def color_map(self) -> dict[str, str]:
        return dict(self._color_map)

    def _choose_color(self, color_key: str) -> None:
        selected = QColorDialog.getColor(QColor(self._color_map[color_key]), self, "Choose Log Highlight Color")
        if not selected.isValid():
            return
        self._color_map[color_key] = selected.name()
        self._sync_color_button(color_key)

    def _sync_color_button(self, color_key: str) -> None:
        button = self._buttons[color_key]
        color_value = self._color_map[color_key]
        button.setText(color_value.upper())
        button.setStyleSheet(
            f"background: {color_value}; color: {'#1f1f1f' if QColor(color_value).lightnessF() > 0.6 else '#ffffff'};"
        )
