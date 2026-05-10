"""Collections screen: paginated collection browser with filter."""
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

from onesauce_companion.services.collection_catalog import (
    CollectionCatalogEntry,
    build_collection_catalog,
)
from onesauce_companion.ui._constants import COLLECTIONS_SCREEN, COLLECTIONS_TABLE_COLUMNS, GAMES_SCREEN
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_collections_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("Collections"))

    filters_row = QHBoxLayout()
    filters_row.setSpacing(12)
    self.collections_name_filter = QLineEdit()
    self.collections_name_filter.setPlaceholderText("Filter by collection name")
    self.collections_name_filter.textChanged.connect(self._reset_collections_page_and_refresh)
    filters_row.addWidget(QLabel("Collection Name"))
    filters_row.addWidget(self.collections_name_filter, stretch=1)
    layout.addLayout(filters_row)

    collections_group = QGroupBox("Collections")
    collections_layout = QVBoxLayout(collections_group)
    self.collections_table = QTableWidget(0, 4)
    self.collections_table.setObjectName("GamesTable")
    self.collections_table.setHorizontalHeaderLabels(["#", "Collection Name", "Parent Collections", "# of Games"])
    self.collections_table.horizontalHeader().setStretchLastSection(False)
    self.collections_table.horizontalHeader().setSectionsClickable(True)
    self.collections_table.horizontalHeader().setSortIndicatorShown(True)
    self.collections_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    self.collections_table.horizontalHeader().sectionClicked.connect(self._handle_collections_header_clicked)
    self.collections_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    self.collections_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
    self.collections_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    self.collections_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    self.collections_table.setColumnWidth(0, 72)
    self.collections_table.setColumnWidth(1, 360)
    self.collections_table.verticalHeader().setVisible(False)
    self.collections_table.verticalHeader().setDefaultSectionSize(46)
    self.collections_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    self.collections_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.collections_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    self.collections_table.setAlternatingRowColors(True)
    collections_layout.addWidget(self.collections_table)
    layout.addWidget(collections_group, stretch=1)

    pagination_row = QHBoxLayout()
    pagination_row.setSpacing(12)
    self.collections_results_label = QLabel("")
    self.collections_first_button = QPushButton("First")
    self.collections_first_button.setMinimumWidth(90)
    self.collections_first_button.clicked.connect(lambda: self._set_collections_page(1))
    self.collections_previous_button = QPushButton("Previous")
    self.collections_previous_button.setMinimumWidth(100)
    self.collections_previous_button.clicked.connect(lambda: self._set_collections_page(self._collections_current_page - 1))
    self.collections_page_label = QLabel("Page 1 of 1")
    self.collections_next_button = QPushButton("Next")
    self.collections_next_button.setMinimumWidth(90)
    self.collections_next_button.clicked.connect(lambda: self._set_collections_page(self._collections_current_page + 1))
    self.collections_last_button = QPushButton("Last")
    self.collections_last_button.setMinimumWidth(90)
    self.collections_last_button.clicked.connect(self._go_to_last_collections_page)
    self.collections_page_size_combo = QComboBox()
    self.collections_page_size_combo.addItem("50 / page", 50)
    self.collections_page_size_combo.addItem("100 / page", 100)
    self.collections_page_size_combo.addItem("250 / page", 250)
    self.collections_page_size_combo.addItem("500 / page", 500)
    self.collections_page_size_combo.setCurrentIndex(1)
    self.collections_page_size_combo.currentIndexChanged.connect(self._change_collections_page_size)

    pagination_row.addWidget(self.collections_results_label)
    pagination_row.addStretch(1)
    pagination_row.addWidget(self.collections_first_button)
    pagination_row.addWidget(self.collections_previous_button)
    pagination_row.addWidget(self.collections_page_label)
    pagination_row.addWidget(self.collections_next_button)
    pagination_row.addWidget(self.collections_last_button)
    pagination_row.addWidget(self.collections_page_size_combo)
    layout.addLayout(pagination_row)
    return screen


def refresh_collections_catalog(self: "MainWindow") -> None:
    target = self._target_dir()
    target_key = str(target) if target is not None else ""
    if self._collections_catalog_target == target_key:
        return
    self._collections_catalog_target = target_key
    self._collection_entries = build_collection_catalog(target)


def refresh_collections_table(self: "MainWindow") -> None:
    refresh_collections_catalog(self)
    filtered_entries = sorted_filtered_collections(self)
    page_size = self._collections_page_size
    total_items = len(filtered_entries)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    self._collections_current_page = max(1, min(self._collections_current_page, total_pages))

    start_index = (self._collections_current_page - 1) * page_size
    end_index = start_index + page_size
    page_entries = filtered_entries[start_index:end_index]

    self.collections_table.setUpdatesEnabled(False)
    self.collections_table.setRowCount(len(page_entries))
    for row, entry in enumerate(page_entries):
        result_index = start_index + row
        self._set_item(
            self.collections_table,
            row,
            COLLECTIONS_TABLE_COLUMNS["index"],
            str(result_index + 1),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        set_collection_name_cell(self, row, entry, filtered_entries, result_index)
        set_collection_parent_cell(self, row, entry)
        set_collection_game_count_cell(self, row, entry)
    self.collections_table.setUpdatesEnabled(True)
    self.collections_table.horizontalHeader().setSortIndicator(self._collections_sort_column, self._collections_sort_order)
    self.collections_table.horizontalHeader().setSortIndicatorShown(True)
    update_collections_pagination(self, total_items, total_pages)
    if self.stack.currentIndex() == COLLECTIONS_SCREEN:
        target = self._target_dir()
        if target is None:
            self._push_status_message("Select a target folder to scan collections.")
        else:
            self._push_status_message(f"Loaded {total_items} collections for {target}")


def sorted_filtered_collections(self: "MainWindow") -> list[CollectionCatalogEntry]:
    name_filter = self.collections_name_filter.text().strip().casefold()
    filtered_entries = [
        entry
        for entry in self._collection_entries
        if not name_filter or name_filter in entry.name.casefold()
    ]
    reverse = self._collections_sort_order == Qt.SortOrder.DescendingOrder
    return sorted(filtered_entries, key=lambda e: collections_sort_key(self, e), reverse=reverse)


def collections_sort_key(self: "MainWindow", entry: CollectionCatalogEntry) -> Any:
    if self._collections_sort_column == COLLECTIONS_TABLE_COLUMNS["collection_name"]:
        return (entry.name.casefold(),)
    if self._collections_sort_column == COLLECTIONS_TABLE_COLUMNS["parent_collections"]:
        return (len(entry.parent_collections), tuple(parent.casefold() for parent in entry.parent_collections), entry.name.casefold())
    if self._collections_sort_column == COLLECTIONS_TABLE_COLUMNS["game_count"]:
        return (entry.game_count, entry.name.casefold())
    return (entry.name.casefold(),)


def set_collection_name_cell(
    self: "MainWindow",
    row: int,
    entry: CollectionCatalogEntry,
    navigation_entries: list[CollectionCatalogEntry],
    navigation_index: int,
) -> None:
    button = QPushButton(entry.name)
    button.setObjectName("gameLink")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(
        lambda _checked=False, collection_entry=entry, entries=navigation_entries, index=navigation_index: self._open_collection_details_dialog(
            collection_entry,
            entries,
            index,
        )
    )
    self.collections_table.setCellWidget(row, COLLECTIONS_TABLE_COLUMNS["collection_name"], button)


def set_collection_parent_cell(self: "MainWindow", row: int, entry: CollectionCatalogEntry) -> None:
    if not entry.parent_collections:
        self._set_item(self.collections_table, row, COLLECTIONS_TABLE_COLUMNS["parent_collections"], "")
        return
    label = QLabel()
    label.setObjectName("collectionLinks")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setOpenExternalLinks(False)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setText(" | ".join(f'<a href="{parent_name}">{parent_name}</a>' for parent_name in entry.parent_collections))
    label.linkActivated.connect(self._open_collection_details_by_name)
    self.collections_table.setCellWidget(row, COLLECTIONS_TABLE_COLUMNS["parent_collections"], label)
    content_width = max(220, self.collections_table.columnWidth(COLLECTIONS_TABLE_COLUMNS["parent_collections"]) - 12)
    self.collections_table.setRowHeight(row, max(46, label.heightForWidth(content_width) + 12))


def set_collection_game_count_cell(self: "MainWindow", row: int, entry: CollectionCatalogEntry) -> None:
    button = QPushButton(f"{entry.game_count:,}")
    button.setObjectName("gameLink")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda _checked=False, name=entry.name: self._show_games_for_collection(name))
    self.collections_table.setCellWidget(row, COLLECTIONS_TABLE_COLUMNS["game_count"], button)


def open_collection_details_by_name(self: "MainWindow", collection_name: str) -> None:
    filtered_entries = sorted_filtered_collections(self)
    for index, entry in enumerate(filtered_entries):
        if entry.name == collection_name:
            self._open_collection_details_dialog(entry, filtered_entries, index)
            return


def show_games_for_collection(self: "MainWindow", collection_name: str) -> None:
    # Build the Games screen if it hasn't been visited yet — its filter
    # widget needs to exist before we set its selection.
    self._ensure_screen_built(GAMES_SCREEN)
    index = self.games_collection_filter.findData(collection_name)
    if index == -1:
        self.games_collection_filter.blockSignals(True)
        self.games_collection_filter.addItem(collection_name, collection_name)
        self.games_collection_filter.blockSignals(False)
        index = self.games_collection_filter.findData(collection_name)
    self.games_collection_filter.setCurrentIndex(max(0, index))
    self._games_current_page = 1
    self._change_screen(GAMES_SCREEN)
    self._refresh_games_table()


def handle_collections_header_clicked(self: "MainWindow", section: int) -> None:
    if section == COLLECTIONS_TABLE_COLUMNS["index"]:
        return
    if self._collections_sort_column == section:
        self._collections_sort_order = (
            Qt.SortOrder.DescendingOrder
            if self._collections_sort_order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
    else:
        self._collections_sort_column = section
        self._collections_sort_order = Qt.SortOrder.AscendingOrder
    self._collections_current_page = 1
    self._refresh_collections_table()


def reset_collections_page_and_refresh(self: "MainWindow", *_args: Any) -> None:
    self._collections_current_page = 1
    self._refresh_collections_table()


def set_collections_page(self: "MainWindow", page: int) -> None:
    self._collections_current_page = max(1, page)
    self._refresh_collections_table()


def go_to_last_collections_page(self: "MainWindow") -> None:
    total_items = len(sorted_filtered_collections(self))
    total_pages = max(1, (total_items + self._collections_page_size - 1) // self._collections_page_size)
    self._collections_current_page = total_pages
    self._refresh_collections_table()


def change_collections_page_size(self: "MainWindow", *_args: Any) -> None:
    self._collections_page_size = int(self.collections_page_size_combo.currentData() or 100)
    self._collections_current_page = 1
    self._refresh_collections_table()


def update_collections_pagination(self: "MainWindow", total_items: int, total_pages: int) -> None:
    self.collections_results_label.setText(f"{total_items:,} collections")
    self.collections_page_label.setText(f"Page {self._collections_current_page} of {total_pages}")
    self.collections_first_button.setEnabled(self._collections_current_page > 1)
    self.collections_previous_button.setEnabled(self._collections_current_page > 1)
    self.collections_next_button.setEnabled(self._collections_current_page < total_pages)
    self.collections_last_button.setEnabled(self._collections_current_page < total_pages)
