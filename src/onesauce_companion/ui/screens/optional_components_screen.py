"""Optional Components screen: optional add-on components table."""
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

from onesauce_companion.ui._constants import OPTIONAL_COMPONENTS_SCREEN
from onesauce_companion.ui._table_widgets import CheckBoxHeader
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_optional_components_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    self.optional_components_summary_warning_icon = QLabel()
    self.optional_components_summary_warning_icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(18, 18))
    self.optional_components_summary_warning_icon.hide()
    self.optional_components_summary_label = QLabel()
    self.optional_components_summary_label.setWordWrap(True)
    self.optional_components_refresh_button = QPushButton("Refresh")
    self.optional_components_refresh_button.setMinimumWidth(140)
    self.optional_components_refresh_button.clicked.connect(self._handle_refresh_requested)
    self.optional_components_install_button = QPushButton("Download Selected")
    self.optional_components_install_button.setMinimumWidth(220)
    self.optional_components_install_button.clicked.connect(lambda: self._start_install_for_screen(OPTIONAL_COMPONENTS_SCREEN))
    layout.addWidget(
        build_screen_header_row(
            "Optional Components",
            self.optional_components_summary_label,
            leading_widgets=(self.optional_components_summary_warning_icon,),
            trailing_widgets=(self.optional_components_refresh_button, self.optional_components_install_button),
        )
    )

    status_group = QGroupBox("Optional Components")
    status_layout = QVBoxLayout(status_group)

    self.optional_components_table = QTableWidget(len(self._optional_specs), 8)
    self.optional_components_table.setObjectName("ComponentsTable")
    self.optional_components_header = CheckBoxHeader()
    self.optional_components_header.toggled.connect(lambda checked: self._toggle_all_component_rows(OPTIONAL_COMPONENTS_SCREEN, checked))
    self.optional_components_table.setHorizontalHeader(self.optional_components_header)
    self.optional_components_table.setHorizontalHeaderLabels(["", "Component", "Type", "Installed", "Available", "Downloaded", "Size", "Status"])
    self.optional_components_table.horizontalHeader().setStretchLastSection(False)
    self.optional_components_table.horizontalHeader().setSectionsClickable(True)
    self.optional_components_table.horizontalHeader().setSortIndicatorShown(True)
    self.optional_components_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.optional_components_table.horizontalHeader().sectionClicked.connect(
        lambda section: self._handle_table_header_clicked(OPTIONAL_COMPONENTS_SCREEN, section)
    )
    self.optional_components_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
    self.optional_components_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
    self.optional_components_table.setColumnWidth(0, 42)
    self.optional_components_table.setColumnWidth(1, 280)
    self.optional_components_table.setColumnWidth(6, 110)
    self.optional_components_table.verticalHeader().setVisible(False)
    self.optional_components_table.verticalHeader().setDefaultSectionSize(64)
    self.optional_components_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.optional_components_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.optional_components_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.optional_components_table.setAlternatingRowColors(True)
    self.optional_components_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._initialize_status_cells(self._optional_specs)
    status_layout.addWidget(self.optional_components_table)
    layout.addWidget(status_group, stretch=2)

    return screen
