"""Shared path and state helpers for the ui package."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


def _scripts_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "scripts"
    return Path(__file__).resolve().parents[3] / "scripts"


def _conf_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "conf"
    return Path(__file__).resolve().parents[3] / "conf"


def _default_video_value_to_percent(value: str) -> int:
    try:
        numeric = float(value.strip())
    except (AttributeError, ValueError):
        return 0
    numeric = max(0.0, min(1.0, numeric))
    return int(round(numeric * 100))


def _percent_to_default_video_value(value: int) -> str:
    numeric = max(0, min(100, value)) / 100.0
    text = f"{numeric:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _is_checked_state(state: int | Qt.CheckState) -> bool:
    return getattr(state, "value", state) == getattr(Qt.CheckState.Checked, "value", Qt.CheckState.Checked)


def build_screen_header_row(
    title: str,
    info_label: QLabel | None = None,
    *,
    leading_widgets: tuple[QWidget, ...] = (),
    trailing_widgets: tuple[QWidget, ...] = (),
) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    title_label = QLabel(title)
    title_label.setObjectName("screenHeader")
    title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignVCenter)

    if leading_widgets or info_label is not None:
        layout.addSpacing(4)
        for widget in leading_widgets:
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        if info_label is not None:
            info_label.setObjectName("screenIntro")
            info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(info_label, 1)
    else:
        layout.addStretch(1)

    for widget in trailing_widgets:
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    return row
