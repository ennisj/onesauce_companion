"""Games screen: paginated game catalog browser with filters."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.games import (
    GameManifestEntry,
    available_collections,
    build_collection_game_catalog,
    scan_installed_games,
)
from onesauce_companion.ui._constants import GAMES_SCREEN, GAMES_TABLE_COLUMNS
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_games_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("Games"))

    filters_row = QHBoxLayout()
    filters_row.setSpacing(12)
    self.games_name_filter = QLineEdit()
    self.games_name_filter.setPlaceholderText("Filter by game name")
    self.games_name_filter.textChanged.connect(self._reset_games_page_and_refresh)
    self.games_collection_filter = QComboBox()
    self.games_collection_filter.addItem("All Collections", "")
    for collection_name in self._collection_options:
        self.games_collection_filter.addItem(collection_name, collection_name)
    self.games_collection_filter.currentIndexChanged.connect(self._reset_games_page_and_refresh)
    self.games_status_filter = QComboBox()
    self.games_status_filter.addItem("All Statuses", "")
    self.games_status_filter.addItem("Installed", "Installed")
    self.games_status_filter.addItem("Not Installed", "Not Installed")
    self.games_status_filter.currentIndexChanged.connect(self._reset_games_page_and_refresh)

    filters_row.addWidget(QLabel("Game Name"))
    filters_row.addWidget(self.games_name_filter, stretch=2)
    filters_row.addWidget(QLabel("Collection"))
    filters_row.addWidget(self.games_collection_filter, stretch=1)
    filters_row.addWidget(QLabel("Status"))
    filters_row.addWidget(self.games_status_filter, stretch=1)
    layout.addLayout(filters_row)

    games_group = QGroupBox("Games")
    games_layout = QVBoxLayout(games_group)
    self.games_table = QTableWidget(0, 4)
    self.games_table.setObjectName("GamesTable")
    self.games_table.setHorizontalHeaderLabels(["#", "Game Name", "Collection", "Status"])
    self.games_table.horizontalHeader().setStretchLastSection(False)
    self.games_table.horizontalHeader().setSectionsClickable(True)
    self.games_table.horizontalHeader().setSortIndicatorShown(True)
    self.games_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.games_table.horizontalHeader().sectionClicked.connect(self._handle_games_header_clicked)
    self.games_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.games_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    self.games_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    self.games_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.games_table.setColumnWidth(0, 72)
    self.games_table.verticalHeader().setVisible(False)
    self.games_table.verticalHeader().setDefaultSectionSize(46)
    self.games_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.games_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.games_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.games_table.setAlternatingRowColors(True)
    games_layout.addWidget(self.games_table)
    layout.addWidget(games_group, stretch=1)

    pagination_row = QHBoxLayout()
    pagination_row.setSpacing(12)
    self.games_results_label = QLabel("")
    self.games_first_button = QPushButton("First")
    self.games_first_button.setMinimumWidth(90)
    self.games_first_button.clicked.connect(lambda: self._set_games_page(1))
    self.games_previous_button = QPushButton("Previous")
    self.games_previous_button.setMinimumWidth(100)
    self.games_previous_button.clicked.connect(lambda: self._set_games_page(self._games_current_page - 1))
    self.games_page_label = QLabel("Page 1 of 1")
    self.games_next_button = QPushButton("Next")
    self.games_next_button.setMinimumWidth(90)
    self.games_next_button.clicked.connect(lambda: self._set_games_page(self._games_current_page + 1))
    self.games_last_button = QPushButton("Last")
    self.games_last_button.setMinimumWidth(90)
    self.games_last_button.clicked.connect(self._go_to_last_games_page)
    self.games_page_size_combo = QComboBox()
    self.games_page_size_combo.addItem("50 / page", 50)
    self.games_page_size_combo.addItem("100 / page", 100)
    self.games_page_size_combo.addItem("250 / page", 250)
    self.games_page_size_combo.addItem("500 / page", 500)
    self.games_page_size_combo.setCurrentIndex(1)
    self.games_page_size_combo.currentIndexChanged.connect(self._change_games_page_size)

    pagination_row.addWidget(self.games_results_label)
    pagination_row.addStretch(1)
    pagination_row.addWidget(self.games_first_button)
    pagination_row.addWidget(self.games_previous_button)
    pagination_row.addWidget(self.games_page_label)
    pagination_row.addWidget(self.games_next_button)
    pagination_row.addWidget(self.games_last_button)
    pagination_row.addWidget(self.games_page_size_combo)
    layout.addLayout(pagination_row)
    return screen


def refresh_games_table(self: "MainWindow") -> None:
    refresh_games_catalog(self)
    installed_games = installed_games_for_current_target(self)
    filtered_entries = sorted_filtered_games(self, installed_games)
    page_size = self._games_page_size
    total_items = len(filtered_entries)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    self._games_current_page = max(1, min(self._games_current_page, total_pages))

    start_index = (self._games_current_page - 1) * page_size
    end_index = start_index + page_size
    page_entries = filtered_entries[start_index:end_index]

    self.games_table.setUpdatesEnabled(False)
    self.games_table.setRowCount(len(page_entries))
    for row, entry in enumerate(page_entries):
        status = "Installed" if entry.installed_key in installed_games else "Not Installed"
        result_index = start_index + row
        self._set_item(
            self.games_table,
            row,
            GAMES_TABLE_COLUMNS["index"],
            str(result_index + 1),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        set_games_name_cell(self, row, entry, status, filtered_entries, result_index, installed_games)
        self._set_item(self.games_table, row, GAMES_TABLE_COLUMNS["collection"], entry.collection_name)
        self._set_item(self.games_table, row, GAMES_TABLE_COLUMNS["status"], status)
    self.games_table.setUpdatesEnabled(True)
    self.games_table.horizontalHeader().setSortIndicator(self._games_sort_column, self._games_sort_order)
    self.games_table.horizontalHeader().setSortIndicatorShown(True)
    update_games_pagination(self, total_items, total_pages)
    if self.stack.currentIndex() == GAMES_SCREEN:
        target = self._target_dir()
        if target is None:
            self._push_status_message("Select a target folder to scan installed games.")
        else:
            self._push_status_message(f"Loaded {total_items} games for {target}")


def installed_games_for_current_target(self: "MainWindow") -> set[tuple[str, str]]:
    target = self._target_dir()
    target_key = str(target) if target is not None else ""
    if self._games_installed_target == target_key:
        return self._installed_games_cache
    self._games_installed_target = target_key
    self._installed_games_cache = scan_installed_games(target)
    return self._installed_games_cache


def sorted_filtered_games(
    self: "MainWindow",
    installed_games: set[tuple[str, str]],
) -> list:
    name_filter = self.games_name_filter.text().strip().casefold()
    collection_filter = str(self.games_collection_filter.currentData() or "")
    status_filter = str(self.games_status_filter.currentData() or "")

    filtered_entries = []
    for entry in self._game_entries:
        status = "Installed" if entry.installed_key in installed_games else "Not Installed"
        if name_filter and name_filter not in entry.game_name.casefold():
            continue
        if collection_filter and entry.collection_name != collection_filter and collection_filter not in entry.subcollections:
            continue
        if status_filter and status != status_filter:
            continue
        filtered_entries.append(entry)

    reverse = self._games_sort_order == Qt.SortOrder.DescendingOrder
    return sorted(filtered_entries, key=lambda entry: games_sort_key(self, entry, installed_games), reverse=reverse)


def games_sort_key(self: "MainWindow", entry: GameManifestEntry, installed_games: set[tuple[str, str]]) -> Any:
    if self._games_sort_column == GAMES_TABLE_COLUMNS["game_name"]:
        return (entry.game_name.casefold(), entry.collection_name.casefold(), entry.rom_path.casefold())
    if self._games_sort_column == GAMES_TABLE_COLUMNS["collection"]:
        return (entry.collection_name.casefold(), entry.game_name.casefold(), entry.rom_path.casefold())
    if self._games_sort_column == GAMES_TABLE_COLUMNS["status"]:
        installed = entry.installed_key in installed_games
        return (0 if installed else 1, entry.game_name.casefold(), entry.collection_name.casefold())
    return (entry.game_name.casefold(), entry.collection_name.casefold(), entry.rom_path.casefold())


def refresh_games_catalog(self: "MainWindow") -> None:
    target = self._target_dir()
    target_key = str(target) if target is not None else ""
    if self._games_catalog_target == target_key:
        return
    self._games_catalog_target = target_key
    self._game_entries = build_collection_game_catalog(target, self._base_game_entries)
    self._collection_options = available_collections(target)
    sync_games_collection_filter(self)


def sync_games_collection_filter(self: "MainWindow") -> None:
    if not hasattr(self, "games_collection_filter"):
        return
    selected = str(self.games_collection_filter.currentData() or "")
    self.games_collection_filter.blockSignals(True)
    self.games_collection_filter.clear()
    self.games_collection_filter.addItem("All Collections", "")
    for collection_name in self._collection_options:
        self.games_collection_filter.addItem(collection_name, collection_name)
    index = max(0, self.games_collection_filter.findData(selected))
    self.games_collection_filter.setCurrentIndex(index)
    self.games_collection_filter.blockSignals(False)


def set_games_name_cell(
    self: "MainWindow",
    row: int,
    entry: GameManifestEntry,
    status: str,
    navigation_entries: list[GameManifestEntry],
    navigation_index: int,
    installed_games: set[tuple[str, str]],
) -> None:
    button = QPushButton(entry.game_name)
    button.setObjectName("gameLink")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(
        lambda _checked=False, game_entry=entry, installed=(status == "Installed"), entries=navigation_entries, index=navigation_index, installed_keys=set(installed_games): self._open_game_details_dialog(
            game_entry,
            installed,
            entries,
            index,
            installed_keys,
        )
    )
    self.games_table.setCellWidget(row, GAMES_TABLE_COLUMNS["game_name"], button)


def handle_games_header_clicked(self: "MainWindow", section: int) -> None:
    if section == GAMES_TABLE_COLUMNS["index"]:
        return
    if self._games_sort_column == section:
        self._games_sort_order = (
            Qt.SortOrder.DescendingOrder
            if self._games_sort_order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
    else:
        self._games_sort_column = section
        self._games_sort_order = Qt.SortOrder.AscendingOrder
    self._games_current_page = 1
    self._refresh_games_table()


def reset_games_page_and_refresh(self: "MainWindow", *_args: Any) -> None:
    self._games_current_page = 1
    self._refresh_games_table()


def set_games_page(self: "MainWindow", page: int) -> None:
    self._games_current_page = max(1, page)
    self._refresh_games_table()


def go_to_last_games_page(self: "MainWindow") -> None:
    installed_games = installed_games_for_current_target(self)
    total_items = len(sorted_filtered_games(self, installed_games))
    total_pages = max(1, (total_items + self._games_page_size - 1) // self._games_page_size)
    self._games_current_page = total_pages
    self._refresh_games_table()


def change_games_page_size(self: "MainWindow", *_args: Any) -> None:
    self._games_page_size = int(self.games_page_size_combo.currentData() or 100)
    self._games_current_page = 1
    self._refresh_games_table()


def update_games_pagination(self: "MainWindow", total_items: int, total_pages: int) -> None:
    self.games_results_label.setText(f"{total_items:,} games")
    self.games_page_label.setText(f"Page {self._games_current_page} of {total_pages}")
    self.games_first_button.setEnabled(self._games_current_page > 1)
    self.games_previous_button.setEnabled(self._games_current_page > 1)
    self.games_next_button.setEnabled(self._games_current_page < total_pages)
    self.games_last_button.setEnabled(self._games_current_page < total_pages)
