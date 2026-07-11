from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
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
    "size": 1,
    "type": 2,
    "available": 3,
    "downloaded": 4,
    "installed": 5,
    "status": 6,
    "cabinet_version": 7,
    "cabinet_status": 8,
    "actions": 9,
}

# Columns rendered under a group band in the two-tier header.
DOWNLOADS_HEADER_GROUPS = {
    DOWNLOADS_TABLE_COLUMNS["downloaded"]: "Local",
    DOWNLOADS_TABLE_COLUMNS["installed"]: "Local",
    DOWNLOADS_TABLE_COLUMNS["status"]: "Local",
    DOWNLOADS_TABLE_COLUMNS["cabinet_version"]: "Cabinet",
    DOWNLOADS_TABLE_COLUMNS["cabinet_status"]: "Cabinet",
}

DOWNLOADS_COLUMN_KEYS = {index: key for key, index in DOWNLOADS_TABLE_COLUMNS.items()}

# Starting widths for the all-Interactive header; the user's adjustments are
# persisted in settings. Status/Cabinet Status host ComponentStatusCell
# progress bars — keep them wide enough for the bar.
DOWNLOADS_DEFAULT_COLUMN_WIDTHS = {
    "component": 300,
    "size": 90,
    "type": 150,
    "available": 110,
    "downloaded": 190,
    "installed": 190,
    "status": 340,
    "cabinet_version": 170,
    "cabinet_status": 210,
    "actions": 100,
}


def _groups_contiguous(groups: list[str]) -> bool:
    """True when no group label re-appears after a different label broke its run."""
    seen: set[str] = set()
    previous = ""
    for group in groups:
        if group and group != previous and group in seen:
            return False
        if group:
            seen.add(group)
        previous = group
    return True


def downloads_column_order_valid(order: list[str]) -> bool:
    """A saved column order is usable when it covers every column exactly once
    and keeps each header group ("Local", "Cabinet") contiguous."""
    if sorted(order) != sorted(DOWNLOADS_TABLE_COLUMNS):
        return False
    return _groups_contiguous(
        [DOWNLOADS_HEADER_GROUPS.get(DOWNLOADS_TABLE_COLUMNS[key], "") for key in order]
    )


def downloads_header_groups_contiguous(header: QHeaderView) -> bool:
    return _groups_contiguous(
        [DOWNLOADS_HEADER_GROUPS.get(header.logicalIndex(visual), "") for visual in range(header.count())]
    )

_HEADER_BACKGROUND = QColor("#242424")
_HEADER_TEXT = QColor("#ffffff")
_HEADER_DIVIDER = QColor("#555555")


class GroupedHeaderView(QHeaderView):
    """Horizontal header with a group band above the column labels.

    Columns listed in ``groups`` get a shared label ("Local", "Cabinet")
    drawn across their contiguous span in a band above the normal column
    labels; ungrouped columns keep a single full-height label. Sections may
    be reordered, so group spans are computed in visual order. Sorted
    columns get an arrow marker (with a rank number when several columns
    participate in the sort).
    """

    def __init__(self, groups: dict[int, str], parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._groups = groups
        self._sort_columns: list[tuple[int, bool]] = []

    def set_sort_columns(self, columns: list[tuple[int, bool]]) -> None:
        """(logical index, ascending) per sort key, primary first."""
        self._sort_columns = list(columns)
        self.viewport().update()

    def _band_height(self) -> int:
        return self.fontMetrics().height() + 8

    def sizeHint(self):  # noqa: N802 - Qt override
        hint = super().sizeHint()
        hint.setHeight(hint.height() + self._band_height())
        return hint

    def _group_at_visual(self, visual: int) -> str:
        return self._groups.get(self.logicalIndex(visual), "")

    def _paint_sort_marker(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:  # noqa: N803
        for rank, (column, ascending) in enumerate(self._sort_columns):
            if column == logicalIndex:
                break
        else:
            return
        arrow = "▲" if ascending else "▼"
        text = arrow if len(self._sort_columns) == 1 else f"{arrow}{rank + 1}"
        painter.save()
        font = painter.font()
        font.setPointSize(max(6, font.pointSize() - 2))
        painter.setFont(font)
        painter.setPen(_HEADER_TEXT)
        painter.drawText(
            rect.adjusted(0, 0, -6, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.restore()

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:  # noqa: N802,N803
        group = self._groups.get(logicalIndex, "")
        if not group:
            super().paintSection(painter, rect, logicalIndex)
            self._paint_sort_marker(painter, rect, logicalIndex)
            return
        band = self._band_height()
        label_rect = QRect(rect.left(), rect.top() + band, rect.width(), rect.height() - band)
        painter.save()
        super().paintSection(painter, label_rect, logicalIndex)
        painter.restore()
        self._paint_sort_marker(painter, label_rect, logicalIndex)

        # Group band: fill this section's slice, then draw the label centered
        # across the whole contiguous visual span (clipping confines it to
        # the slice).
        visual = self.visualIndex(logicalIndex)
        first = visual
        while first > 0 and self._group_at_visual(first - 1) == group:
            first -= 1
        last = visual
        while last < self.count() - 1 and self._group_at_visual(last + 1) == group:
            last += 1
        band_rect = QRect(rect.left(), rect.top(), rect.width(), band)
        painter.save()
        painter.fillRect(band_rect, _HEADER_BACKGROUND)
        span_left = self.sectionViewportPosition(self.logicalIndex(first))
        span_width = sum(self.sectionSize(self.logicalIndex(position)) for position in range(first, last + 1))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(_HEADER_TEXT)
        painter.drawText(
            QRect(span_left, rect.top(), span_width, band),
            Qt.AlignmentFlag.AlignCenter,
            group,
        )
        painter.setPen(_HEADER_DIVIDER)
        painter.drawLine(band_rect.left(), band_rect.bottom(), band_rect.right(), band_rect.bottom())
        if visual == last:
            painter.drawLine(band_rect.right(), band_rect.top(), band_rect.right(), band_rect.bottom())
        painter.restore()


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

    filters_layout.addWidget(QLabel("Local Status"), 0, 2)
    self.downloads_status_filter = QComboBox()
    self.downloads_status_filter.addItem("Any Status")
    self.downloads_status_filter.currentIndexChanged.connect(self._handle_downloads_filter_changed)
    filters_layout.addWidget(self.downloads_status_filter, 0, 3)

    filters_layout.addWidget(QLabel("Cabinet Status"), 0, 4)
    self.downloads_cabinet_status_filter = QComboBox()
    self.downloads_cabinet_status_filter.addItem("Any Cabinet Status")
    self.downloads_cabinet_status_filter.currentIndexChanged.connect(self._handle_downloads_filter_changed)
    filters_layout.addWidget(self.downloads_cabinet_status_filter, 0, 5)

    filters_layout.addWidget(QLabel("Component Name"), 0, 6)
    self.downloads_name_filter = QLineEdit()
    self.downloads_name_filter.setPlaceholderText("Filter by component name")
    self.downloads_name_filter.textChanged.connect(self._handle_downloads_filter_changed)
    filters_layout.addWidget(self.downloads_name_filter, 0, 7)
    filters_layout.setColumnStretch(1, 1)
    filters_layout.setColumnStretch(3, 1)
    filters_layout.setColumnStretch(5, 1)
    filters_layout.setColumnStretch(7, 2)
    layout.addWidget(filters_group)

    table_group = QGroupBox("Components")
    table_layout = QVBoxLayout(table_group)
    self.downloads_table = QTableWidget(0, len(DOWNLOADS_TABLE_COLUMNS))
    self.downloads_table.setObjectName("ComponentsTable")
    self.downloads_table.setHorizontalHeader(
        GroupedHeaderView(DOWNLOADS_HEADER_GROUPS, self.downloads_table)
    )
    self.downloads_table.setHorizontalHeaderLabels(
        [
            "Component",
            "Size",
            "Type",
            "Available",
            "Downloaded",
            "Installed",
            "Status",
            "Version",
            "Status",
            "Actions",
        ]
    )
    _configure_downloads_table(self.downloads_table)
    header = self.downloads_table.horizontalHeader()
    header.sectionClicked.connect(self._handle_downloads_header_clicked)
    header.sectionMoved.connect(self._handle_downloads_section_moved)
    header.sectionResized.connect(self._handle_downloads_section_resized)
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
    header.setSectionsClickable(True)
    header.setSectionsMovable(True)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setMinimumSectionSize(80)
    # Every column is Interactive so the user can resize it; widths and the
    # visual order are restored from settings after the UI is built.
    for key, column in DOWNLOADS_TABLE_COLUMNS.items():
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(column, DOWNLOADS_DEFAULT_COLUMN_WIDTHS[key])
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
