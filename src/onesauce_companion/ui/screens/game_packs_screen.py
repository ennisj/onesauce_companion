"""Game Packs screen: system packs component table."""
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

from onesauce_companion.ui._constants import GAME_PACKS_SCREEN
from onesauce_companion.ui._table_widgets import CheckBoxHeader
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_game_packs_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)

    self.game_packs_summary_warning_icon = QLabel()
    self.game_packs_summary_warning_icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(18, 18))
    self.game_packs_summary_warning_icon.hide()
    self.game_packs_summary_label = QLabel()
    self.game_packs_summary_label.setWordWrap(True)
    self.game_packs_refresh_button = QPushButton("Refresh")
    self.game_packs_refresh_button.setMinimumWidth(140)
    self.game_packs_refresh_button.clicked.connect(self._handle_refresh_requested)
    self.game_packs_install_button = QPushButton("Download Selected")
    self.game_packs_install_button.setMinimumWidth(220)
    self.game_packs_install_button.clicked.connect(lambda: self._start_install_for_screen(GAME_PACKS_SCREEN))
    layout.addWidget(
        build_screen_header_row(
            "System Packs",
            self.game_packs_summary_label,
            leading_widgets=(self.game_packs_summary_warning_icon,),
            trailing_widgets=(self.game_packs_refresh_button, self.game_packs_install_button),
        )
    )

    status_group = QGroupBox("System Packs")
    status_layout = QVBoxLayout(status_group)

    self.game_packs_table = QTableWidget(len(self._game_pack_specs), 7)
    self.game_packs_table.setObjectName("ComponentsTable")
    self.game_packs_header = CheckBoxHeader()
    self.game_packs_header.toggled.connect(lambda checked: self._toggle_all_component_rows(GAME_PACKS_SCREEN, checked))
    self.game_packs_table.setHorizontalHeader(self.game_packs_header)
    self.game_packs_table.setHorizontalHeaderLabels(["", "Pack", "Installed", "Available", "Downloaded", "Size", "Status"])
    self.game_packs_table.horizontalHeader().setStretchLastSection(False)
    self.game_packs_table.horizontalHeader().setSectionsClickable(True)
    self.game_packs_table.horizontalHeader().setSortIndicatorShown(True)
    self.game_packs_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.game_packs_table.horizontalHeader().sectionClicked.connect(
        lambda section: self._handle_table_header_clicked(GAME_PACKS_SCREEN, section)
    )
    self.game_packs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.game_packs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    self.game_packs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.game_packs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.game_packs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    self.game_packs_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    self.game_packs_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
    self.game_packs_table.setColumnWidth(0, 42)
    self.game_packs_table.setColumnWidth(1, 260)
    self.game_packs_table.setColumnWidth(5, 110)
    self.game_packs_table.verticalHeader().setVisible(False)
    self.game_packs_table.verticalHeader().setDefaultSectionSize(64)
    self.game_packs_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.game_packs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.game_packs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.game_packs_table.setAlternatingRowColors(True)
    self.game_packs_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._initialize_status_cells(self._game_pack_specs)
    status_layout.addWidget(self.game_packs_table)
    layout.addWidget(status_group, stretch=2)

    return screen
