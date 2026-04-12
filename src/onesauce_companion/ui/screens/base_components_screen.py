"""Base Components screen: required OnesaUCE components table."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.ui._constants import BASE_COMPONENTS_SCREEN
from onesauce_companion.ui._table_widgets import CheckBoxHeader
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_base_components_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    self.base_summary_warning_icon = QLabel()
    self.base_summary_warning_icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(18, 18))
    self.base_summary_warning_icon.hide()
    self.base_summary_label = QLabel()
    self.base_summary_label.setWordWrap(True)
    self.refresh_button = QPushButton("Refresh")
    self.refresh_button.setMinimumWidth(140)
    self.refresh_button.clicked.connect(self._handle_refresh_requested)
    self.install_button = QPushButton("Download Selected")
    self.install_button.setMinimumWidth(220)
    self.install_button.clicked.connect(lambda: self._start_install_for_screen(BASE_COMPONENTS_SCREEN))
    layout.addWidget(
        build_screen_header_row(
            "Base Components",
            self.base_summary_label,
            leading_widgets=(self.base_summary_warning_icon,),
            trailing_widgets=(self.refresh_button, self.install_button),
        )
    )

    status_group = QGroupBox("Required Components")
    status_layout = QVBoxLayout(status_group)

    self.table = QTableWidget(len(self._required_specs), 7)
    self.table.setObjectName("ComponentsTable")
    self.base_header = CheckBoxHeader()
    self.base_header.toggled.connect(lambda checked: self._toggle_all_component_rows(BASE_COMPONENTS_SCREEN, checked))
    self.table.setHorizontalHeader(self.base_header)
    self.table.setHorizontalHeaderLabels(["", "Component", "Installed", "Available", "Downloaded", "Size", "Status"])
    self.table.horizontalHeader().setStretchLastSection(False)
    self.table.horizontalHeader().setSectionsClickable(True)
    self.table.horizontalHeader().setSortIndicatorShown(True)
    self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.table.horizontalHeader().sectionClicked.connect(
        lambda section: self._handle_table_header_clicked(BASE_COMPONENTS_SCREEN, section)
    )
    self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
    self.table.setColumnWidth(0, 42)
    self.table.setColumnWidth(1, 260)
    self.table.setColumnWidth(5, 110)
    self.table.verticalHeader().setVisible(False)
    self.table.verticalHeader().setDefaultSectionSize(64)
    self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.table.setAlternatingRowColors(True)
    self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._initialize_status_cells(self._required_specs)
    status_layout.addWidget(self.table)
    layout.addWidget(status_group, stretch=2)

    return screen
