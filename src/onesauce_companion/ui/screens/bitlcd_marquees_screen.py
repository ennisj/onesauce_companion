"""BitLCD Marquees screen: marquee image component table."""
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

from onesauce_companion.ui._constants import BITLCD_MARQUEES_SCREEN
from onesauce_companion.ui._table_widgets import CheckBoxHeader
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_bitlcd_marquees_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    self.bitlcd_summary_warning_icon = QLabel()
    self.bitlcd_summary_warning_icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(18, 18))
    self.bitlcd_summary_warning_icon.hide()
    self.bitlcd_summary_label = QLabel()
    self.bitlcd_summary_label.setWordWrap(True)
    self.bitlcd_refresh_button = QPushButton("Refresh")
    self.bitlcd_refresh_button.setMinimumWidth(140)
    self.bitlcd_refresh_button.clicked.connect(self._handle_refresh_requested)
    self.bitlcd_install_button = QPushButton("Download Selected")
    self.bitlcd_install_button.setMinimumWidth(220)
    self.bitlcd_install_button.clicked.connect(lambda: self._start_install_for_screen(BITLCD_MARQUEES_SCREEN))
    layout.addWidget(
        build_screen_header_row(
            "BitLCD Marquees",
            self.bitlcd_summary_label,
            leading_widgets=(self.bitlcd_summary_warning_icon,),
            trailing_widgets=(self.bitlcd_refresh_button, self.bitlcd_install_button),
        )
    )

    status_group = QGroupBox("BitLCD Marquees")
    status_layout = QVBoxLayout(status_group)

    self.bitlcd_table = QTableWidget(len(self._bitlcd_specs), 7)
    self.bitlcd_table.setObjectName("ComponentsTable")
    self.bitlcd_header = CheckBoxHeader()
    self.bitlcd_header.toggled.connect(lambda checked: self._toggle_all_component_rows(BITLCD_MARQUEES_SCREEN, checked))
    self.bitlcd_table.setHorizontalHeader(self.bitlcd_header)
    self.bitlcd_table.setHorizontalHeaderLabels(["", "Marquee", "Installed", "Available", "Downloaded", "Size", "Status"])
    self.bitlcd_table.horizontalHeader().setStretchLastSection(False)
    self.bitlcd_table.horizontalHeader().setSectionsClickable(True)
    self.bitlcd_table.horizontalHeader().setSortIndicatorShown(True)
    self.bitlcd_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.bitlcd_table.horizontalHeader().sectionClicked.connect(
        lambda section: self._handle_table_header_clicked(BITLCD_MARQUEES_SCREEN, section)
    )
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    self.bitlcd_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
    self.bitlcd_table.setColumnWidth(0, 42)
    self.bitlcd_table.setColumnWidth(1, 260)
    self.bitlcd_table.setColumnWidth(5, 110)
    self.bitlcd_table.verticalHeader().setVisible(False)
    self.bitlcd_table.verticalHeader().setDefaultSectionSize(64)
    self.bitlcd_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.bitlcd_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.bitlcd_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.bitlcd_table.setAlternatingRowColors(True)
    self.bitlcd_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._initialize_status_cells(self._bitlcd_specs)
    status_layout.addWidget(self.bitlcd_table)
    layout.addWidget(status_group, stretch=2)

    return screen
