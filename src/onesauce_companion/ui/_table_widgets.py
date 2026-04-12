"""Reusable table header and cell widgets used across component screens."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class CheckBoxHeader(QHeaderView):
    toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self._checked = False
        self._syncing = False
        self._checkbox = QCheckBox(self.viewport())
        self._checkbox.setObjectName("headerSelector")
        self._checkbox.toggled.connect(self._on_checkbox_toggled)
        self.sectionResized.connect(lambda *_: self._position_checkbox())
        self.geometriesChanged.connect(self._position_checkbox)

    def set_checked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        self._syncing = True
        self._checkbox.setChecked(checked)
        self._syncing = False
        self._position_checkbox()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.logicalIndexAt(event.pos()) == 0:
            event.accept()
            return
        super().mousePressEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._position_checkbox()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_checkbox()

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self._checked = checked
        if self._syncing:
            return
        self.toggled.emit(checked)

    def _position_checkbox(self) -> None:
        if self.isSectionHidden(0):
            self._checkbox.hide()
            return
        x = self.sectionViewportPosition(0)
        width = self.sectionSize(0)
        if width <= 0:
            self._checkbox.hide()
            return
        size = self._checkbox.sizeHint()
        y = max(0, (self.height() - size.height()) // 2)
        left = x + max(0, (width - size.width()) // 2)
        self._checkbox.setGeometry(left, y, size.width(), size.height())
        self._checkbox.show()


class ComponentStatusCell(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)
        self._percent = 0.0

        self.label = QLabel("Pending")
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        self.set_status("Pending", 0)

    def set_status(self, text: str, percent: float) -> None:
        clamped_percent = max(0.0, min(100.0, float(percent)))
        self._percent = clamped_percent
        paused_suffix = " (Paused)"
        paused = text.endswith(paused_suffix)
        base_text = text[:-len(paused_suffix)] if paused else text
        active = base_text in {"Downloading", "Preparing", "Backing Up", "Installing"}

        self.label.setText(text)
        self.label.setVisible(not active)

        self.progress.setVisible(active)
        self.progress.setValue(int(round(clamped_percent)))
        self.progress.setFormat(f"{base_text} {clamped_percent:.1f}%{' (Paused)' if paused else ''}")

    def percent(self) -> float:
        return self._percent
