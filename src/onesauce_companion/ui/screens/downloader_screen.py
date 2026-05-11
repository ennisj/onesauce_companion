from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


DOWNLOADS_TABLE_COLUMNS = {
    "component": 0,
    "type": 1,
    "available": 2,
    "downloaded": 3,
    "installed": 4,
    "size": 5,
    "status": 6,
    "actions": 7,
}


def build_downloader_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    self.downloads_intro_label = QLabel("Download and install various OnesaUCE components")
    self.downloads_intro_label.setWordWrap(True)

    self.downloads_refresh_button = self._build_downloads_icon_button("Refresh", "refresh", True)
    self.downloads_refresh_button.clicked.connect(self._handle_downloads_refresh_requested)
    self.downloader_refresh_button = self.downloads_refresh_button

    self.downloads_updates_button = self._build_downloads_icon_button("Download Updates", "download", True)
    self.downloads_updates_button.clicked.connect(self._handle_downloads_batch_download_updates)

    self.downloads_all_button = self._build_downloads_icon_button("Download All", "download-all", True)
    self.downloads_all_button.clicked.connect(self._handle_downloads_batch_download_all)

    self.downloads_install_ready_button = self._build_downloads_icon_button("Install Ready", "install", True)
    self.downloads_install_ready_button.clicked.connect(self._handle_downloads_batch_install_ready)

    self.downloads_pause_all_button = self._build_downloads_icon_button("Pause All", "pause", True)
    self.downloads_pause_all_button.clicked.connect(self._handle_downloads_batch_pause_all)

    self.downloads_resume_all_button = self._build_downloads_icon_button("Resume All", "resume", True)
    self.downloads_resume_all_button.clicked.connect(self._handle_downloads_batch_resume_all)

    self.downloads_cancel_all_button = self._build_downloads_icon_button("Cancel All", "cancel", True)
    self.downloads_cancel_all_button.clicked.connect(self._handle_downloads_batch_cancel_all)
    self.downloads_all_components_label = QLabel("All Components:")
    self.downloads_all_components_label.setObjectName("screenIntro")

    layout.addWidget(
        build_screen_header_row(
            "Downloads",
            self.downloads_intro_label,
            trailing_widgets=(
                self.downloads_all_components_label,
                self.downloads_refresh_button,
                self.downloads_updates_button,
                self.downloads_all_button,
                self.downloads_install_ready_button,
                self.downloads_pause_all_button,
                self.downloads_resume_all_button,
                self.downloads_cancel_all_button,
            ),
        )
    )

    filters_group = QGroupBox("Filters")
    filters_layout = QGridLayout(filters_group)
    filters_layout.setContentsMargins(16, 16, 16, 16)
    filters_layout.setHorizontalSpacing(12)
    filters_layout.setVerticalSpacing(8)

    filters_layout.addWidget(QLabel("Component Type"), 0, 0)
    self.downloads_type_filter = QComboBox()
    self.downloads_type_filter.addItem("Any Component Type")
    self.downloads_type_filter.currentIndexChanged.connect(self._handle_downloads_filter_changed)
    filters_layout.addWidget(self.downloads_type_filter, 0, 1)

    filters_layout.addWidget(QLabel("Status"), 0, 2)
    self.downloads_status_filter = QComboBox()
    self.downloads_status_filter.addItem("Any Status")
    self.downloads_status_filter.currentIndexChanged.connect(self._handle_downloads_filter_changed)
    filters_layout.addWidget(self.downloads_status_filter, 0, 3)

    filters_layout.addWidget(QLabel("Component Name"), 0, 4)
    self.downloads_name_filter = QLineEdit()
    self.downloads_name_filter.setPlaceholderText("Filter by component name")
    self.downloads_name_filter.textChanged.connect(self._handle_downloads_filter_changed)
    filters_layout.addWidget(self.downloads_name_filter, 0, 5)
    filters_layout.setColumnStretch(1, 1)
    filters_layout.setColumnStretch(3, 1)
    filters_layout.setColumnStretch(5, 2)
    layout.addWidget(filters_group)

    table_group = QGroupBox("Components")
    table_layout = QVBoxLayout(table_group)
    self.downloads_table = QTableWidget(0, len(DOWNLOADS_TABLE_COLUMNS))
    self.downloads_table.setObjectName("ComponentsTable")
    self.downloads_table.setHorizontalHeaderLabels(
        ["Component", "Type", "Available", "Downloaded", "Installed", "Size", "Status", "Actions"]
    )
    _configure_downloads_table(self.downloads_table)
    table_layout.addWidget(self.downloads_table)
    table_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout.addWidget(table_group, stretch=1)

    log_group = QGroupBox("Download Log")
    log_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    log_group.setFixedHeight(190)
    log_layout = QVBoxLayout(log_group)
    self.downloads_log_output = QPlainTextEdit()
    self.downloads_log_output.setReadOnly(True)
    self.downloads_log_output.setMaximumBlockCount(2000)
    self.downloads_log_output.setFont(QFont("Consolas", 10))
    self.queue_log_output = self.downloads_log_output
    log_layout.addWidget(self.downloads_log_output)
    layout.addWidget(log_group)
    return screen


def _configure_downloads_table(table: QTableWidget) -> None:
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionsClickable(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for column in DOWNLOADS_TABLE_COLUMNS.values():
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(DOWNLOADS_TABLE_COLUMNS["component"], QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(DOWNLOADS_TABLE_COLUMNS["status"], QHeaderView.ResizeMode.Interactive)
    table.setColumnWidth(DOWNLOADS_TABLE_COLUMNS["status"], 340)
    table.horizontalHeader().setMinimumSectionSize(80)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(56)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setAlternatingRowColors(True)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setWordWrap(False)


def update_downloader_table_height(table: QTableWidget) -> None:
    row_count = table.rowCount()
    header_height = table.horizontalHeader().height()
    frame_height = table.frameWidth() * 2
    if row_count <= 0:
        table.setFixedHeight(header_height + frame_height)
        return
    last_row = row_count - 1
    content_height = table.rowViewportPosition(last_row) + table.rowHeight(last_row)
    table.setFixedHeight(header_height + content_height + frame_height)
