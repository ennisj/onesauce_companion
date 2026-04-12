"""Queue screen: installation queue table and live log output."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QSize

from onesauce_companion.models import QueueEntry
from onesauce_companion.ui._constants import QUEUE_SCREEN, QUEUE_TABLE_COLUMNS
from onesauce_companion.ui._table_widgets import ComponentStatusCell
from onesauce_companion.ui._utils import _assets_dir, build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_queue_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    self.queue_summary_label = QLabel("Queued component updates start automatically and can be reordered below.")
    self.queue_pause_button = QPushButton("Pause")
    self.queue_pause_button.setMinimumWidth(140)
    self.queue_pause_button.clicked.connect(self._toggle_pause)
    self.queue_clear_button = QPushButton("Clear")
    self.queue_clear_button.setMinimumWidth(120)
    self.queue_clear_button.clicked.connect(self._clear_queue)
    layout.addWidget(
        build_screen_header_row(
            "Queue",
            self.queue_summary_label,
            trailing_widgets=(self.queue_pause_button, self.queue_clear_button),
        )
    )

    queue_group = QGroupBox("Queue")
    queue_layout = QVBoxLayout(queue_group)
    self.queue_table = QTableWidget(0, 6)
    self.queue_table.setObjectName("QueueTable")
    self.queue_table.setHorizontalHeaderLabels(["", "Component", "Source", "Available", "Size", "Status"])
    self.queue_table.horizontalHeader().setStretchLastSection(False)
    self.queue_table.horizontalHeader().setSectionsClickable(True)
    self.queue_table.horizontalHeader().setSortIndicatorShown(True)
    self.queue_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.queue_table.horizontalHeader().sectionClicked.connect(
        lambda section: self._handle_table_header_clicked(QUEUE_SCREEN, section)
    )
    self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    self.queue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
    self.queue_table.setColumnWidth(0, 108)
    self.queue_table.setColumnWidth(4, 110)
    self.queue_table.setColumnWidth(5, 320)
    self.queue_table.verticalHeader().setVisible(False)
    self.queue_table.verticalHeader().setDefaultSectionSize(64)
    self.queue_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.queue_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.queue_table.setAlternatingRowColors(True)
    queue_layout.addWidget(self.queue_table)
    layout.addWidget(queue_group, stretch=2)

    log_group = QGroupBox("Queue Log")
    log_layout = QVBoxLayout(log_group)
    self.queue_log_output = QPlainTextEdit()
    self.queue_log_output.setReadOnly(True)
    self.queue_log_output.setMaximumBlockCount(2000)
    self.queue_log_output.setFont(QFont("Consolas", 10))
    log_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    log_group.setFixedHeight(190)
    log_layout.addWidget(self.queue_log_output)
    layout.addWidget(log_group, stretch=1)
    self._refresh_queue_table()
    return screen


def refresh_queue_table(self: "MainWindow") -> None:
    self.queue_table.setUpdatesEnabled(False)
    self.queue_table.setRowCount(len(self._queue_entries))
    self._queue_status_widgets.clear()
    for row, entry in enumerate(self._queue_entries):
        set_queue_actions_widget(self, row, entry)
        self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["component"], entry.spec.display_name)
        self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["source"], entry.source_label)
        self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["available"], entry.spec.available_display)
        self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["size"], self._component_size_display(entry.spec))
        widget = ComponentStatusCell()
        widget.set_status(self._display_component_status(entry.spec.key, entry.status), entry.percent)
        self._queue_status_widgets[entry.spec.key] = widget
        self.queue_table.setCellWidget(row, QUEUE_TABLE_COLUMNS["status"], widget)
    self.queue_table.setUpdatesEnabled(True)
    self._apply_sort_indicator(QUEUE_SCREEN)
    update_queue_buttons(self)


def update_queue_buttons(self: "MainWindow") -> None:
    has_queue = bool(self._queue_entries)
    busy = self._controller is not None
    self.queue_clear_button.setEnabled(has_queue and not busy)
    self.queue_pause_button.setEnabled(has_queue)
    if not has_queue:
        self.queue_pause_button.setText("Pause")
    elif busy:
        self.queue_pause_button.setText("Resume" if self._controller is not None and self._controller.is_paused else "Pause")
    else:
        self.queue_pause_button.setText("Resume Queue")


def set_queue_actions_widget(self: "MainWindow", row: int, entry: QueueEntry) -> None:
    assets_dir = _assets_dir()
    up_icon = QIcon(str(assets_dir / "chevron_up_white.svg"))
    down_icon = QIcon(str(assets_dir / "chevron_down_white.svg"))
    remove_icon = QIcon(str(assets_dir / "queue_remove_red.svg"))
    can_reorder = self._controller is None or self._controller.is_paused

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    up_button = QToolButton()
    up_button.setProperty("queueAction", True)
    up_button.setIcon(up_icon)
    up_button.setIconSize(QSize(14, 14))
    up_button.setEnabled(can_reorder and row > 0)
    up_button.clicked.connect(lambda _=False, key=entry.spec.key: self._move_queue_entry(key, -1))

    down_button = QToolButton()
    down_button.setProperty("queueAction", True)
    down_button.setIcon(down_icon)
    down_button.setIconSize(QSize(14, 14))
    down_button.setEnabled(can_reorder and row < len(self._queue_entries) - 1)
    down_button.clicked.connect(lambda _=False, key=entry.spec.key: self._move_queue_entry(key, 1))

    remove_button = QToolButton()
    remove_button.setProperty("queueAction", True)
    remove_button.setIcon(remove_icon)
    remove_button.setIconSize(QSize(18, 18))
    remove_button.setEnabled(True)
    remove_button.clicked.connect(lambda _=False, key=entry.spec.key: self._remove_queue_entry(key))

    layout.addStretch(1)
    layout.addWidget(up_button)
    layout.addWidget(down_button)
    layout.addWidget(remove_button)
    layout.addStretch(1)
    self.queue_table.setCellWidget(row, 0, container)


def set_queue_controls_enabled(self: "MainWindow", enabled: bool) -> None:
    if not enabled:
        self.queue_clear_button.setEnabled(False)
        self.queue_pause_button.setEnabled(bool(self._queue_entries))
        refresh_queue_table(self)
        return
    update_queue_buttons(self)
    refresh_queue_table(self)


def move_queue_entry(self: "MainWindow", component_key: str, offset: int) -> None:
    if self._controller is not None and not self._controller.is_paused:
        self._push_status_message("Pause the queue before reordering items.")
        return
    row = next((index for index, entry in enumerate(self._queue_entries) if entry.spec.key == component_key), -1)
    if row < 0:
        return
    new_row = row + offset
    if new_row < 0 or new_row >= len(self._queue_entries):
        return
    self._queue_entries[row], self._queue_entries[new_row] = self._queue_entries[new_row], self._queue_entries[row]
    self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
    refresh_queue_table(self)
    self._save_settings()


def remove_queue_entry(self: "MainWindow", component_key: str) -> None:
    if self._controller is not None:
        self._controller.skip_component(component_key)
    self._queue_entries = [entry for entry in self._queue_entries if entry.spec.key != component_key]
    self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
    refresh_queue_table(self)
    self._save_settings()


def clear_queue(self: "MainWindow") -> None:
    self._queue_entries.clear()
    self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
    refresh_queue_table(self)
    self._save_settings()


def update_queue_status(self: "MainWindow", component_key: str, status: str, percent: float) -> None:
    widget = self._queue_status_widgets.get(component_key)
    if widget is not None:
        widget.set_status(self._display_component_status(component_key, status), percent)
    for entry in self._queue_entries:
        if entry.spec.key == component_key:
            entry.status = status
            entry.percent = percent
            break


def sort_queue_entries(self: "MainWindow") -> None:
    column, order = self._sort_states[QUEUE_SCREEN]
    if column < 0:
        return
    if column == QUEUE_TABLE_COLUMNS["size"]:
        self._queue_entries = self._sort_by_size(
            self._queue_entries,
            key_fn=lambda entry: self._component_size_bytes(entry.spec),
            descending=order == Qt.SortOrder.DescendingOrder,
        )
        return
    reverse = order == Qt.SortOrder.DescendingOrder
    self._queue_entries.sort(key=lambda entry: queue_entry_sort_key(self, column, entry), reverse=reverse)


def queue_entry_sort_key(self: "MainWindow", column: int, entry: QueueEntry) -> Any:
    if column == QUEUE_TABLE_COLUMNS["component"]:
        return entry.spec.display_name.casefold()
    if column == QUEUE_TABLE_COLUMNS["source"]:
        return entry.source_label.casefold()
    if column == QUEUE_TABLE_COLUMNS["available"]:
        return self._version_sort_key(entry.spec.available_version)
    if column == QUEUE_TABLE_COLUMNS["size"]:
        return self._size_sort_key(
            self._component_size_bytes(entry.spec),
            self._component_size_display(entry.spec),
        )
    if column == QUEUE_TABLE_COLUMNS["status"]:
        return self._status_sort_key(entry.status, entry.percent)
    return entry.spec.display_name.casefold()
