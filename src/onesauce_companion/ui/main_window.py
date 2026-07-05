from __future__ import annotations

import ctypes
import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, QTimer, Qt, Slot
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QCheckBox,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.manifest import BITLCD_MARQUEES, GAME_PACKS, OPTIONAL_COMPONENTS, REQUIRED_COMPONENTS
from onesauce_companion import __version__
from onesauce_companion.models import ComponentSpec, ComponentStatus, InstallProgress, QueueEntry
from onesauce_companion.services.archive_metadata import ArchiveMetadataService
from onesauce_companion.services.archive_org import ArchiveOrgCredentials
from onesauce_companion.services.collection_catalog import (
    CollectionCatalogEntry,
)
from onesauce_companion.services.component_catalogs import (
    ArchiveBackedComponentCatalog,
    build_bitlcd_component_specs,
    build_optional_component_specs,
    build_required_component_specs,
)
from onesauce_companion.services.control import OperationController
from onesauce_companion.services.download_cache import (
    CacheCleanupResult,
    cached_download_version,
    clear_downloads_dir,
    default_downloads_dir,
    enforce_download_cache_policy,
    list_cached_archive_files,
)
from onesauce_companion.services.games import (
    GameManifestEntry,
    available_collections,
    load_game_manifest,
)
from onesauce_companion.services.github_releases import RELEASES_PAGE_URL
from onesauce_companion.services.downloader import Downloader
from onesauce_companion.services.installer import Installer
from onesauce_companion.services.settings import AppSettings, SettingsStore
from onesauce_companion.services.system_packs import SystemPackCatalogService
from onesauce_companion.services.tweaks import detect_autostart_state
from onesauce_companion.ui.downloads_controller import DownloadsController
from onesauce_companion.ui.themes_controller import ThemesController
from onesauce_companion.ui.screens.cabinet_screen import CabinetScreen
from onesauce_companion.ui.screens.collection_details_screen import CollectionDetailsScreen
from onesauce_companion.ui.screens.game_details_screen import GameDetailsScreen
from onesauce_companion.ui._worker_handle import WorkerHandle
from onesauce_companion.ui.workers import (
    CatalogRefreshWorker,
    InstalledStatusWorker,
    InstallWorker,
    ReleaseCheckWorker,
    RemoteSizesWorker,
    ValidateCredentialsWorker,
)
from onesauce_companion.ui._constants import (
    SETTINGS_SCREEN,
    BASE_COMPONENTS_SCREEN,
    GAME_PACKS_SCREEN,
    BITLCD_MARQUEES_SCREEN,
    OPTIONAL_COMPONENTS_SCREEN,
    QUEUE_SCREEN,
    GAMES_SCREEN,
    COLLECTIONS_SCREEN,
    TWEAKS_SCREEN,
    LOGS_SCREEN,
    THEMES_SCREEN,
    DOWNLOADER_SCREEN,
    GAME_DETAILS_SCREEN,
    COLLECTION_DETAILS_SCREEN,
    CABINET_SCREEN,
    BASE_TABLE_COLUMNS,
    OPTIONAL_TABLE_COLUMNS,
    QUEUE_TABLE_COLUMNS,
    GAMES_TABLE_COLUMNS,
    COLLECTIONS_TABLE_COLUMNS,
)
from onesauce_companion.ui._log_widgets import DEFAULT_LOG_HIGHLIGHT_COLORS
from onesauce_companion.ui._table_widgets import ComponentStatusCell
from onesauce_companion.ui.screens.settings_screen import build_settings_screen
from onesauce_companion.ui.screens.base_components_screen import build_base_components_screen
from onesauce_companion.ui.screens.game_packs_screen import build_game_packs_screen
from onesauce_companion.ui.screens.bitlcd_marquees_screen import build_bitlcd_marquees_screen
from onesauce_companion.ui.screens.optional_components_screen import build_optional_components_screen
from onesauce_companion.ui.screens.downloader_screen import build_downloader_screen, update_downloader_table_height
from onesauce_companion.ui.screens.logs_screen import (
    build_logs_screen,
    change_log_colors,
    filtered_log_content,
    handle_log_reverse_toggled,
    handle_log_wrap_toggled,
    load_full_log,
    log_file_paths,
    log_level_for_line,
    on_log_load_failed,
    on_log_load_finished,
    refresh_logs_screen,
    select_log,
    show_log_contents,
    update_log_wrap_mode,
)
from onesauce_companion.ui.screens.tweaks_screen import (
    build_tweaks_screen,
    handle_attract_mode_next_time_changed,
    handle_attract_mode_time_changed,
    handle_auto_scan_collections_toggled,
    handle_autostart_primary_action,
    handle_default_theme_changed,
    handle_default_video_value_changed,
    handle_install_autostart_fix,
    handle_legends_micro_fix_toggled,
    handle_remember_menu_toggled,
    handle_video_enable_toggled,
    handle_video_loop_changed,
    handle_write_launcher_log_toggled,
    refresh_tweaks_screen,
)
from onesauce_companion.ui.screens.games_screen import (
    build_games_screen,
    change_games_page_size,
    games_sort_key,
    go_to_last_games_page,
    handle_games_header_clicked,
    installed_games_for_current_target,
    refresh_games_catalog,
    refresh_games_table,
    reset_games_page_and_refresh,
    set_games_name_cell,
    set_games_page,
    sorted_filtered_games,
    sync_games_collection_filter,
    update_games_pagination,
)
from onesauce_companion.ui.screens.collections_screen import (
    build_collections_screen,
    change_collections_page_size,
    collections_sort_key,
    go_to_last_collections_page,
    handle_collections_header_clicked,
    open_collection_details_by_name,
    refresh_collections_catalog,
    refresh_collections_table,
    reset_collections_page_and_refresh,
    set_collection_game_count_cell,
    set_collection_name_cell,
    set_collection_parent_cell,
    set_collections_page,
    show_games_for_collection,
    sorted_filtered_collections,
    update_collections_pagination,
)
from onesauce_companion.ui.screens.themes_screen import (
    build_themes_screen,
    on_theme_catalog_finished,
    on_theme_entry_ready,
    refresh_themes_screen,
    dispose_all_theme_preview_video_sessions,
)
from onesauce_companion.ui.screens.queue_screen import (
    build_queue_screen,
    clear_queue,
    move_queue_entry,
    queue_entry_sort_key,
    refresh_queue_table,
    remove_queue_entry,
    set_queue_actions_widget,
    set_queue_controls_enabled,
    sort_queue_entries,
    update_queue_buttons,
    update_queue_status,
)
from onesauce_companion.ui._style import build_stylesheet
from onesauce_companion.ui._utils import (
    _assets_dir,
)
from shiboken6 import isValid


LOGGER = logging.getLogger(__name__)

APP_VERSION = f"v{__version__}"


@dataclass(frozen=True)
class DownloadsRowView:
    spec: ComponentSpec
    component_type: str
    available_version: str
    downloaded_version: str | None
    installed_version: str | None
    status: str


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._required_specs = REQUIRED_COMPONENTS
        self._game_pack_specs = GAME_PACKS
        self._bitlcd_specs = BITLCD_MARQUEES
        self._optional_specs = OPTIONAL_COMPONENTS
        self._shared_downloader = Downloader()
        self.base_installer = Installer(self._required_specs, downloader=self._shared_downloader)
        self.game_packs_installer = Installer(self._game_pack_specs, downloader=self._shared_downloader)
        self.bitlcd_installer = Installer(self._bitlcd_specs, downloader=self._shared_downloader)
        self.optional_components_installer = Installer(self._optional_specs, downloader=self._shared_downloader)
        self.archive_metadata = ArchiveMetadataService()
        self.required_component_catalog = ArchiveBackedComponentCatalog(self._required_specs, build_required_component_specs)
        self.system_pack_catalog = SystemPackCatalogService()
        self.bitlcd_catalog = ArchiveBackedComponentCatalog(self._bitlcd_specs, build_bitlcd_component_specs)
        self.optional_component_catalog = ArchiveBackedComponentCatalog(self._optional_specs, build_optional_component_specs)
        self.settings_store = SettingsStore()
        # Paired One Saucier cabinet (persisted via AppSettings; the CabinetScreen
        # reads/writes these and _save_settings round-trips them).
        self._cabinet_host = ""
        self._cabinet_device_id = ""
        self._cabinet_name = ""
        self._install_handle = WorkerHandle(self)
        self._validate_handle = WorkerHandle(self)
        self._release_check_handle = WorkerHandle(self)
        self._catalog_refresh_handle = WorkerHandle(self)
        self._catalog_refresh_user_initiated = False
        self._catalog_refresh_completed = 0
        self._catalog_refresh_total = 0
        self._catalog_refresh_failed_keys: set[str] = set()
        self._remote_sizes_handle = WorkerHandle(self)
        self._remote_sizes_restart_pending = False
        self._remote_sizes_completed = 0
        self._remote_sizes_total = 0
        self._installed_status_handle = WorkerHandle(self)
        self._installed_status_restart_pending = False
        self._installed_status_completed = 0
        self._installed_status_total = 0
        self._installed_status_pending_keys: set[str] = set()
        self._themes = ThemesController(self)
        self._screen_loading_label: str | None = None
        self._controller: OperationController | None = None
        self._loading_settings = False
        self._loading_tweaks_settings = False
        self._closing = False
        self._close_after_workers = False
        self._last_video_loop_value = "0"
        self._last_attract_mode_time_value = "0"
        self._last_attract_mode_next_time_value = "0"
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(350)
        self._scan_timer.timeout.connect(self._refresh_all_tables)
        self._startup_refresh_timer = QTimer(self)
        self._startup_refresh_timer.setSingleShot(True)
        self._startup_refresh_timer.timeout.connect(self._run_next_startup_refresh)
        self._startup_refresh_queue: deque[int] = deque()
        self._defer_screen_refresh = True
        self._initialized_component_screens: set[int] = set()
        self._status_widgets: dict[str, ComponentStatusCell] = {}
        self._status_state: dict[str, tuple[str, float]] = {}
        self._remote_size_overrides: dict[str, tuple[str, int | None]] = {}
        self._cached_download_versions: dict[str, str | None] = {}
        self._active_components: set[str] = set()
        self._all_components_by_key: dict[str, ComponentSpec] = {}
        self._default_source_label_by_key: dict[str, str] = {}
        self._rebuild_component_registry()
        self._selected_component_keys: dict[int, set[str]] = {
            BASE_COMPONENTS_SCREEN: set(),
            GAME_PACKS_SCREEN: set(),
            BITLCD_MARQUEES_SCREEN: set(),
            OPTIONAL_COMPONENTS_SCREEN: set(),
        }
        self._disabled_component_keys: dict[int, set[str]] = {
            BASE_COMPONENTS_SCREEN: set(),
            GAME_PACKS_SCREEN: set(),
            BITLCD_MARQUEES_SCREEN: set(),
            OPTIONAL_COMPONENTS_SCREEN: set(),
        }
        self._selection_sync = False
        self._logo_pixmap = QPixmap()
        self._active_operation_screen: int | None = None
        self._queue_entries: list[QueueEntry] = []
        self._queue_status_widgets: dict[str, ComponentStatusCell] = {}
        self._downloads = DownloadsController(self)
        self._downloads_visible_keys: list[str] = []
        self._downloads_filtering = False
        self._downloads_prompt_dialogs: list[QMessageBox] = []
        self._downloads_status_widgets: dict[str, ComponentStatusCell] = {}
        self._downloads_status_state: dict[str, tuple[str, float]] = {}
        self._downloads_table_refresh_pending = False
        self._cached_downloads_installed_statuses: dict[str, ComponentStatus] = {}
        self._downloads_action_widgets: dict[str, tuple[QWidget, QPushButton, QPushButton, QPushButton, QPushButton]] = {}
        self._downloads_filter_debounce_timer = QTimer(self)
        self._downloads_filter_debounce_timer.setSingleShot(True)
        self._downloads_filter_debounce_timer.setInterval(200)
        self._downloads_filter_debounce_timer.timeout.connect(self._refresh_downloads_table)
        self._game_entries_override: tuple[GameManifestEntry, ...] | None = None
        self._collection_options_override: tuple[str, ...] | None = None
        self._games_catalog_target: str | None = None
        self._games_installed_target: str | None = None
        self._installed_games_cache: set[tuple[str, str]] = set()
        self._games_excluded_target: str | None = None
        self._excluded_games_cache: set[tuple[str, str]] = set()
        self._games_current_page = 1
        self._games_page_size = 100
        self._games_sort_column = GAMES_TABLE_COLUMNS["game_name"]
        self._games_sort_order = Qt.SortOrder.AscendingOrder
        self._collection_entries: tuple[CollectionCatalogEntry, ...] = tuple()
        self._collections_catalog_target: str | None = None
        self._collections_current_page = 1
        self._collections_page_size = 100
        self._collections_sort_column = COLLECTIONS_TABLE_COLUMNS["collection_name"]
        self._collections_sort_order = Qt.SortOrder.AscendingOrder
        self._selected_log_key: str | None = None
        self._loaded_log_key: str | None = None
        self._loaded_log_raw_content: str | None = None
        self._loaded_log_was_truncated: bool = False
        self._log_load_handle = WorkerHandle(self)
        self._log_level_filters = ("info", "debug", "warning", "error", "critical", "fatal", "other")
        self._log_highlight_colors = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
        self._sort_states: dict[int, tuple[int, Qt.SortOrder]] = {
            BASE_COMPONENTS_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            GAME_PACKS_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            BITLCD_MARQUEES_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            OPTIONAL_COMPONENTS_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            QUEUE_SCREEN: (-1, Qt.SortOrder.AscendingOrder),
        }
        self._force_required_catalog_refresh = False
        self._force_system_pack_catalog_refresh = False
        self._force_bitlcd_catalog_refresh = False
        self._force_optional_catalog_refresh = False

        self.themes_show_wireframes_checkbox = QCheckBox("Show Wireframes")
        self.themes_show_wireframes_checkbox.setChecked(True)
        self.themes_show_media_checkbox = QCheckBox("Show Media")
        self.themes_show_media_checkbox.setChecked(True)
        self.themes_show_text_checkbox = QCheckBox("Show Text")
        self.themes_show_text_checkbox.setChecked(True)
        self.log_wrap_checkbox = QCheckBox("Wrap Lines")
        self.log_wrap_checkbox.setChecked(False)
        self.log_reverse_checkbox = QCheckBox("Reverse Order")
        self.log_reverse_checkbox.setChecked(True)

        self.setWindowTitle("OnesaUCE Companion")
        self.resize(1280, 980)
        self.setMinimumWidth(1000)
        self.setMinimumHeight(720)
        self._build_ui()
        self._apply_style()
        self._update_component_summary_labels()
        self._load_settings()
        self._connect_setting_signals()
        self._show_initial_screen()
        QTimer.singleShot(0, self._start_release_check)
        QTimer.singleShot(0, self._begin_startup_refresh)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        sidebar = QWidget()
        sidebar.setObjectName("sidebarCard")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 16)
        sidebar_layout.setSpacing(12)

        title = QLabel()
        title.setObjectName("titleLogo")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._title_logo = title
        sidebar_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self.settings_nav_button = QPushButton("Settings")
        self.settings_nav_button.setObjectName("navButton")
        self.settings_nav_button.setCheckable(True)
        self.settings_nav_button.clicked.connect(lambda: self._change_screen(SETTINGS_SCREEN))

        self.tweaks_nav_button = QPushButton("OnesaUCE Settings")
        self.tweaks_nav_button.setObjectName("navButton")
        self.tweaks_nav_button.setCheckable(True)
        self.tweaks_nav_button.clicked.connect(lambda: self._change_screen(TWEAKS_SCREEN))

        self.downloader_nav_button = QPushButton("Downloads")
        self.downloader_nav_button.setObjectName("navButton")
        self.downloader_nav_button.setCheckable(True)
        self.downloader_nav_button.clicked.connect(lambda: self._change_screen(DOWNLOADER_SCREEN))

        self.base_components_nav_button = QPushButton("Base Components")
        self.base_components_nav_button.setObjectName("navButton")
        self.base_components_nav_button.setCheckable(True)
        self.base_components_nav_button.clicked.connect(lambda: self._change_screen(BASE_COMPONENTS_SCREEN))

        self.game_packs_nav_button = QPushButton("System Packs")
        self.game_packs_nav_button.setObjectName("navButton")
        self.game_packs_nav_button.setCheckable(True)
        self.game_packs_nav_button.clicked.connect(lambda: self._change_screen(GAME_PACKS_SCREEN))

        self.bitlcd_nav_button = QPushButton("BitLCD Marquees")
        self.bitlcd_nav_button.setObjectName("navButton")
        self.bitlcd_nav_button.setCheckable(True)
        self.bitlcd_nav_button.clicked.connect(lambda: self._change_screen(BITLCD_MARQUEES_SCREEN))

        self.optional_components_nav_button = QPushButton("Optional Components")
        self.optional_components_nav_button.setObjectName("navButton")
        self.optional_components_nav_button.setCheckable(True)
        self.optional_components_nav_button.clicked.connect(lambda: self._change_screen(OPTIONAL_COMPONENTS_SCREEN))

        self.games_nav_button = QPushButton("Games")
        self.games_nav_button.setObjectName("navButton")
        self.games_nav_button.setCheckable(True)
        self.games_nav_button.clicked.connect(lambda: self._change_screen(GAMES_SCREEN))

        self.collections_nav_button = QPushButton("Collections")
        self.collections_nav_button.setObjectName("navButton")
        self.collections_nav_button.setCheckable(True)
        self.collections_nav_button.clicked.connect(lambda: self._change_screen(COLLECTIONS_SCREEN))

        self.themes_nav_button = QPushButton("Themes")
        self.themes_nav_button.setObjectName("navButton")
        self.themes_nav_button.setCheckable(True)
        self.themes_nav_button.clicked.connect(lambda: self._change_screen(THEMES_SCREEN))

        self.logs_nav_button = QPushButton("Logs")
        self.logs_nav_button.setObjectName("navButton")
        self.logs_nav_button.setCheckable(True)
        self.logs_nav_button.clicked.connect(lambda: self._change_screen(LOGS_SCREEN))

        self.cabinet_nav_button = QPushButton("Cabinet")
        self.cabinet_nav_button.setObjectName("navButton")
        self.cabinet_nav_button.setCheckable(True)
        self.cabinet_nav_button.clicked.connect(lambda: self._change_screen(CABINET_SCREEN))

        sidebar_layout.addWidget(
            self._build_nav_section("Companion", self.settings_nav_button, self.downloader_nav_button)
        )
        sidebar_layout.addWidget(self._build_nav_section("OnesaUCE", self.games_nav_button, self.collections_nav_button, self.themes_nav_button, self.logs_nav_button, self.tweaks_nav_button, self.cabinet_nav_button))
        sidebar_layout.addStretch(1)
        version_row = QWidget()
        version_row.setObjectName("sidebarVersionRow")
        version_row_layout = QHBoxLayout(version_row)
        version_row_layout.setContentsMargins(0, 0, 0, 0)
        version_row_layout.setSpacing(0)
        version_row_layout.addStretch(1)
        self.sidebar_version_label = QLabel(APP_VERSION)
        self.sidebar_version_label.setObjectName("sidebarVersion")
        self.sidebar_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon = QLabel()
        self.sidebar_version_icon.setObjectName("sidebarVersionIcon")
        self.sidebar_version_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon.setContentsMargins(0, 6, 0, 0)
        self.sidebar_version_icon_2 = QLabel()
        self.sidebar_version_icon_2.setObjectName("sidebarVersionIcon")
        self.sidebar_version_icon_2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon_2.setContentsMargins(0, 6, 0, 0)
        self.sidebar_version_icon_3 = QLabel()
        self.sidebar_version_icon_3.setObjectName("sidebarVersionIcon")
        self.sidebar_version_icon_3.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon_3.setContentsMargins(0, 6, 0, 0)
        version_row_layout.addWidget(self.sidebar_version_label)
        version_row_layout.addSpacing(6)
        version_row_layout.addWidget(self.sidebar_version_icon)
        version_row_layout.addWidget(self.sidebar_version_icon_2)
        version_row_layout.addWidget(self.sidebar_version_icon_3)
        version_row_layout.addStretch(1)
        sidebar_layout.addWidget(version_row)
        self.sidebar_version_note = QLabel("")
        self.sidebar_version_note.setObjectName("sidebarVersionNote")
        self.sidebar_version_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_note.setWordWrap(True)
        self.sidebar_version_note.setOpenExternalLinks(True)
        self.sidebar_version_note.hide()
        sidebar_layout.addWidget(self.sidebar_version_note)
        main_layout.addWidget(sidebar)

        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, stretch=1)

        self.startup_loading_progress = QProgressBar()
        self.startup_loading_progress.setObjectName("startupLoading")
        self.startup_loading_progress.setTextVisible(True)
        self.startup_loading_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.startup_loading_progress.setFixedHeight(28)
        self.startup_loading_progress.hide()
        content_layout.addWidget(self.startup_loading_progress)

        main_layout.addWidget(content_container, stretch=1)

        self._pending_screen_builders: dict[int, Callable[[], QWidget]] = {
            BASE_COMPONENTS_SCREEN: self._build_base_components_screen,
            GAME_PACKS_SCREEN: self._build_game_packs_screen,
            BITLCD_MARQUEES_SCREEN: self._build_bitlcd_marquees_screen,
            OPTIONAL_COMPONENTS_SCREEN: self._build_optional_components_screen,
            GAMES_SCREEN: self._build_games_screen,
            COLLECTIONS_SCREEN: self._build_collections_screen,
            TWEAKS_SCREEN: self._build_tweaks_screen,
            LOGS_SCREEN: self._build_logs_screen,
            THEMES_SCREEN: self._build_themes_screen,
            CABINET_SCREEN: self._build_cabinet_screen,
        }
        self.stack.addWidget(self._build_settings_screen())
        self.stack.addWidget(QWidget())  # BASE_COMPONENTS_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # GAME_PACKS_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # BITLCD_MARQUEES_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # OPTIONAL_COMPONENTS_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # QUEUE_SCREEN placeholder
        self.stack.addWidget(QWidget())  # GAMES_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # COLLECTIONS_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # TWEAKS_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # LOGS_SCREEN — built on first nav
        self.stack.addWidget(QWidget())  # THEMES_SCREEN — built on first nav
        self.stack.addWidget(self._build_downloader_screen())
        self.stack.addWidget(QWidget())  # GAME_DETAILS_SCREEN — populated when a game is opened
        self.stack.addWidget(QWidget())  # COLLECTION_DETAILS_SCREEN — populated when a collection is opened
        self.stack.addWidget(QWidget())  # CABINET_SCREEN — built on first nav

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_message_queue: deque[tuple[str, int]] = deque()
        self._status_message_timer = QTimer(self)
        self._status_message_timer.setSingleShot(True)
        self._status_message_timer.timeout.connect(self._show_next_status_message)
        self._current_status_message: str | None = None
        self._push_status_message("Ready")

        self.menuBar().hide()
        QTimer.singleShot(0, self._load_sidebar_assets)

    def _build_nav_group(self, *buttons: QPushButton) -> QWidget:
        container = QWidget()
        container.setObjectName("navGroup")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 18, 6, 6)
        layout.setSpacing(4)
        for button in buttons:
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout.addWidget(button)
        return container

    def _build_nav_section(self, title: str, *buttons: QPushButton) -> QWidget:
        container = QWidget()
        container.setObjectName("navSectionContainer")
        label = QLabel(title, container)
        label.setObjectName("navSectionLabel")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.ensurePolished()
        label_width = max(label.sizeHint().width(), label.fontMetrics().horizontalAdvance(title) + 24)
        label.setFixedSize(label_width, label.sizeHint().height())
        label.move(14, 0)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, max(1, label.sizeHint().height() // 3), 0, 0)
        layout.setSpacing(0)
        nav_group = self._build_nav_group(*buttons)
        layout.addWidget(nav_group)
        label.raise_()
        return container

    def _build_settings_screen(self) -> QWidget:
        return build_settings_screen(self)

    def _build_tweaks_screen(self) -> QWidget:
        return build_tweaks_screen(self)

    def _build_base_components_screen(self) -> QWidget:
        return build_base_components_screen(self)

    def _build_game_packs_screen(self) -> QWidget:
        return build_game_packs_screen(self)

    def _build_bitlcd_marquees_screen(self) -> QWidget:
        return build_bitlcd_marquees_screen(self)

    def _build_optional_components_screen(self) -> QWidget:
        return build_optional_components_screen(self)

    def _build_queue_screen(self) -> QWidget:
        return build_queue_screen(self)

    def _build_games_screen(self) -> QWidget:
        return build_games_screen(self)

    def _build_collections_screen(self) -> QWidget:
        return build_collections_screen(self)

    def _build_logs_screen(self) -> QWidget:
        return build_logs_screen(self)

    def _build_themes_screen(self) -> QWidget:
        return build_themes_screen(self)

    def _build_downloader_screen(self) -> QWidget:
        return build_downloader_screen(self)

    def _apply_style(self) -> None:
        self.setStyleSheet(build_stylesheet(_assets_dir()))

    def _connect_setting_signals(self) -> None:
        self.target_edit.editingFinished.connect(self._commit_install_target_settings)
        self.bitlcd_target_edit.editingFinished.connect(self._commit_bitlcd_target_settings)
        self.downloads_path_edit.editingFinished.connect(self._commit_downloads_path_settings)
        self.downloads_retention_combo.currentIndexChanged.connect(self._sync_download_retention_controls)
        self.downloads_retention_combo.currentIndexChanged.connect(self._save_settings)
        self.downloads_retention_days_spin.editingFinished.connect(self._save_settings)
        self.downloads_retention_max_gb_spin.editingFinished.connect(self._save_settings)
        self.parallel_downloads_spin.editingFinished.connect(self._save_settings)
        self.auto_resume_downloads_checkbox.stateChanged.connect(self._save_settings)
        self.auto_install_after_download_checkbox.stateChanged.connect(self._save_settings)
        self.segmented_downloads_checkbox.stateChanged.connect(self._save_settings)
        self.segmented_download_min_size_spin.editingFinished.connect(self._save_settings)
        self.segmented_download_segments_spin.editingFinished.connect(self._save_settings)
        self.enable_themes_preview_checkbox.stateChanged.connect(self._handle_enable_themes_preview_changed)

    def _load_settings(self) -> None:
        self._loading_settings = True
        try:
            settings = self.settings_store.load()
            self.target_edit.setText(settings.install_target)
            self.bitlcd_target_edit.setText(settings.bitlcd_target)
            self.downloads_path_edit.setText(settings.downloads_path)
            index = max(0, self.downloads_retention_combo.findData(settings.downloads_retention_mode))
            self.downloads_retention_combo.setCurrentIndex(index)
            self.downloads_retention_days_spin.setValue(settings.downloads_retention_days)
            self.downloads_retention_max_gb_spin.setValue(settings.downloads_retention_max_gb)
            self.auto_resume_downloads_checkbox.setChecked(settings.auto_resume_downloads_on_start)
            self.auto_install_after_download_checkbox.setChecked(settings.auto_install_components_after_download)
            self.segmented_downloads_checkbox.setChecked(settings.segmented_downloads_enabled)
            self.segmented_download_min_size_spin.setValue(settings.segmented_download_min_size_mb)
            self.segmented_download_segments_spin.setValue(settings.segmented_download_segments)
            self.archive_email_edit.setText(settings.archive_email)
            self.archive_password_edit.setText(settings.archive_password)
            self.parallel_downloads_spin.setValue(settings.parallel_downloads)
            self.log_wrap_checkbox.setChecked(settings.log_wrap_lines)
            self.log_reverse_checkbox.setChecked(settings.log_reverse_order)
            self.enable_themes_preview_checkbox.setChecked(settings.enable_themes_preview)
            self._log_highlight_colors = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
            self._log_highlight_colors.update(settings.log_highlight_colors)
            if getattr(self, "logs_highlighter", None) is not None:
                self.logs_highlighter.set_color_map(self._log_highlight_colors)
            self._apply_download_settings_to_installers(settings)
            self.resize(settings.window_width, settings.window_height)
            if settings.window_x is not None and settings.window_y is not None:
                self.move(settings.window_x, settings.window_y)
            self._downloads.load_operations(settings)
            self._themes.selected_name = settings.theme_selected_theme or None
            self._themes.selected_collection_name = settings.theme_selected_collection or None
            self._themes.selected_game_key = settings.theme_selected_game_key or None
            self.themes_show_wireframes_checkbox.setChecked(settings.theme_show_wireframes)
            self.themes_show_media_checkbox.setChecked(settings.theme_show_media)
            self.themes_show_text_checkbox.setChecked(settings.theme_show_text)
            self._cabinet_host = settings.cabinet_host
            self._cabinet_device_id = settings.cabinet_device_id
            self._cabinet_name = settings.cabinet_name
            self._sync_themes_nav_visibility()
        finally:
            self._loading_settings = False
        self._refresh_target_validation()
        self._refresh_tweaks_screen()
        self._sync_download_retention_controls()
        self._update_component_summary_labels()
        QTimer.singleShot(0, self._enforce_download_cache_policy)

    def _save_settings(self) -> None:
        if self._loading_settings:
            return
        settings = AppSettings(
            install_target=self.target_edit.text().strip(),
            bitlcd_target=self.bitlcd_target_edit.text().strip(),
            downloads_path=self.downloads_path_edit.text().strip() or str(default_downloads_dir()),
            downloads_retention_mode=str(self.downloads_retention_combo.currentData()),
            downloads_retention_days=self.downloads_retention_days_spin.value(),
            downloads_retention_max_gb=self.downloads_retention_max_gb_spin.value(),
            auto_resume_downloads_on_start=self.auto_resume_downloads_checkbox.isChecked(),
            auto_install_components_after_download=self.auto_install_after_download_checkbox.isChecked(),
            segmented_downloads_enabled=self.segmented_downloads_checkbox.isChecked(),
            segmented_download_min_size_mb=self.segmented_download_min_size_spin.value(),
            segmented_download_segments=self.segmented_download_segments_spin.value(),
            archive_email=self.archive_email_edit.text().strip(),
            archive_password=self.archive_password_edit.text(),
            parallel_downloads=self.parallel_downloads_spin.value(),
            window_width=self.width(),
            window_height=self.height(),
            window_x=self.x(),
            window_y=self.y(),
            log_wrap_lines=self.log_wrap_checkbox.isChecked(),
            log_reverse_order=self.log_reverse_checkbox.isChecked(),
            log_highlight_colors=self._log_highlight_colors,
            queue_entries=[],
            downloads_operations=self._downloads.serialized_operations(),
            enable_themes_preview=self.enable_themes_preview_checkbox.isChecked(),
            theme_selected_theme=self._themes.selected_name or "",
            theme_selected_collection=self._themes.selected_collection_name or "",
            theme_selected_game_key=list(self._themes.selected_game_key) if self._themes.selected_game_key else [],
            theme_show_wireframes=self.themes_show_wireframes_checkbox.isChecked(),
            theme_show_media=self.themes_show_media_checkbox.isChecked(),
            theme_show_text=self.themes_show_text_checkbox.isChecked(),
            cabinet_host=self._cabinet_host,
            cabinet_device_id=self._cabinet_device_id,
            cabinet_name=self._cabinet_name,
        )
        self.settings_store.save(settings)
        self._apply_download_settings_to_installers(settings)
        self._update_component_summary_labels()

    def _themes_feature_enabled(self) -> bool:
        return self.enable_themes_preview_checkbox.isChecked()

    def _sync_themes_nav_visibility(self) -> None:
        enabled = self._themes_feature_enabled()
        self.themes_nav_button.setVisible(enabled)
        if not enabled and self.stack.currentIndex() == THEMES_SCREEN:
            self._change_screen(SETTINGS_SCREEN)

    def _handle_enable_themes_preview_changed(self) -> None:
        if self._loading_settings:
            return
        self._sync_themes_nav_visibility()
        self._save_settings()

    def _start_validate_credentials(self) -> None:
        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password before validating.",
            )
            return

        self._set_action_buttons_enabled(False)
        self._set_queue_controls_enabled(False)
        self._push_status_message("Validating Archive.org credentials...")

        worker = ValidateCredentialsWorker(credentials)
        worker.finished.connect(self._validate_credentials_success)
        worker.error.connect(self._validate_credentials_error)
        self._validate_handle.start(
            worker,
            finish_signals=(worker.finished, worker.error),
            on_cleared=self._finalize_close_if_ready,
        )

    def _show_initial_screen(self) -> None:
        self._change_screen(DOWNLOADER_SCREEN)

    def _begin_startup_refresh(self) -> None:
        self._defer_screen_refresh = False
        self._startup_refresh_queue.clear()
        initial_screen = self.stack.currentIndex()
        if initial_screen == DOWNLOADER_SCREEN:
            self._startup_refresh_queue.append(DOWNLOADER_SCREEN)
        elif initial_screen in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            self._startup_refresh_queue.append(initial_screen)
        self._update_loading_indicator()
        self._run_next_startup_refresh()

    def _run_next_startup_refresh(self) -> None:
        if not self._startup_refresh_queue:
            self._update_loading_indicator()
            return
        screen_index = self._startup_refresh_queue.popleft()
        if screen_index == GAMES_SCREEN:
            self._refresh_games_table()
        elif screen_index == COLLECTIONS_SCREEN:
            self._refresh_collections_table()
        elif screen_index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            self._refresh_screen_table(screen_index)
            self._initialized_component_screens.add(screen_index)
        elif screen_index == DOWNLOADER_SCREEN:
            self._refresh_downloader_screen()
        self._startup_refresh_timer.start(40)

    def _ensure_screen_built(self, index: int) -> None:
        builder = self._pending_screen_builders.pop(index, None)
        if builder is None:
            return
        placeholder = self.stack.widget(index)
        new_widget = builder()
        self.stack.removeWidget(placeholder)
        self.stack.insertWidget(index, new_widget)
        if placeholder is not None:
            placeholder.deleteLater()
        if index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            self._update_component_summary_labels()

    def _build_cabinet_screen(self) -> QWidget:
        self.cabinet_screen = CabinetScreen(self)
        return self.cabinet_screen

    def _change_screen(self, index: int) -> None:
        if index < 0:
            return
        if index == THEMES_SCREEN and not self._themes_feature_enabled():
            index = SETTINGS_SCREEN
        # Stop media playback / collapse expanded preview when leaving the
        # Game Details or Collection Details screens.
        if (
            self.stack.currentIndex() == GAME_DETAILS_SCREEN
            and index != GAME_DETAILS_SCREEN
        ):
            current_details = self.stack.widget(GAME_DETAILS_SCREEN)
            if isinstance(current_details, GameDetailsScreen):
                current_details.dispose()
        if (
            self.stack.currentIndex() == COLLECTION_DETAILS_SCREEN
            and index != COLLECTION_DETAILS_SCREEN
        ):
            current_details = self.stack.widget(COLLECTION_DETAILS_SCREEN)
            if isinstance(current_details, CollectionDetailsScreen):
                current_details.dispose()
        self._ensure_screen_built(index)
        self.stack.setCurrentIndex(index)
        self.settings_nav_button.setChecked(index == SETTINGS_SCREEN)
        self.tweaks_nav_button.setChecked(index == TWEAKS_SCREEN)
        self.base_components_nav_button.setChecked(index == BASE_COMPONENTS_SCREEN)
        self.game_packs_nav_button.setChecked(index == GAME_PACKS_SCREEN)
        self.bitlcd_nav_button.setChecked(index == BITLCD_MARQUEES_SCREEN)
        self.optional_components_nav_button.setChecked(index == OPTIONAL_COMPONENTS_SCREEN)
        self.downloader_nav_button.setChecked(index == DOWNLOADER_SCREEN)
        self.games_nav_button.setChecked(index == GAMES_SCREEN)
        self.collections_nav_button.setChecked(index == COLLECTIONS_SCREEN)
        self.logs_nav_button.setChecked(index == LOGS_SCREEN)
        self.themes_nav_button.setChecked(index == THEMES_SCREEN)
        self.cabinet_nav_button.setChecked(index == CABINET_SCREEN)
        if self._defer_screen_refresh:
            return
        if index == TWEAKS_SCREEN:
            self._run_deferred_refresh("Settings", self._refresh_tweaks_screen)
        elif index == GAMES_SCREEN:
            self._run_deferred_refresh("Games", self._refresh_games_table)
        elif index == COLLECTIONS_SCREEN:
            self._run_deferred_refresh("Collections", self._refresh_collections_table)
        elif index == LOGS_SCREEN:
            self._run_deferred_refresh("Logs", self._refresh_logs_screen)
        elif index == THEMES_SCREEN:
            self._run_deferred_refresh("Themes", self._refresh_themes_screen)
        elif index == DOWNLOADER_SCREEN:
            self._run_deferred_refresh("Downloads", self._refresh_downloader_screen)
        elif index == CABINET_SCREEN:
            if self._cabinet_host:
                self._run_deferred_refresh("Cabinet", self.cabinet_screen.refresh)
        elif index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            if index not in self._initialized_component_screens:
                screen_label = {
                    BASE_COMPONENTS_SCREEN: "Base Components",
                    GAME_PACKS_SCREEN: "System Packs",
                    BITLCD_MARQUEES_SCREEN: "BitLCD Marquees",
                    OPTIONAL_COMPONENTS_SCREEN: "Optional Components",
                }[index]
                self._run_deferred_refresh(screen_label, lambda i=index: self._refresh_screen_table(i))

    def _run_deferred_refresh(self, label: str, refresh_fn) -> None:
        self._screen_loading_label = label
        self._update_loading_indicator()

        def execute() -> None:
            try:
                refresh_fn()
            finally:
                if self._screen_loading_label == label:
                    self._screen_loading_label = None
                    self._update_loading_indicator()

        QTimer.singleShot(50, execute)

    def _commit_install_target_settings(self) -> None:
        self._save_settings()
        self._schedule_scan()
        self._refresh_target_validation()

    def _commit_bitlcd_target_settings(self) -> None:
        self._save_settings()
        self._schedule_scan()
        self._refresh_target_validation()

    def _commit_downloads_path_settings(self) -> None:
        self._save_settings()

    def _browse_for_target(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose OnesaUCE target folder")
        if directory:
            self.target_edit.setText(directory)
            self._commit_install_target_settings()

    def _browse_for_bitlcd_target(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose BitLCD target folder")
        if directory:
            self.bitlcd_target_edit.setText(directory)
            self._commit_bitlcd_target_settings()

    def _browse_for_downloads_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose downloads cache folder")
        if directory:
            self.downloads_path_edit.setText(directory)
            self._commit_downloads_path_settings()

    def _sync_download_retention_controls(self) -> None:
        mode = str(self.downloads_retention_combo.currentData())
        show_days = mode == "days"
        show_space = mode == "space"
        self.downloads_retention_days_label.setVisible(show_days)
        self.downloads_retention_days_spin.setVisible(show_days)
        self.downloads_retention_days_spin.setEnabled(show_days)
        self.downloads_retention_max_gb_label.setVisible(show_space)
        self.downloads_retention_max_gb_spin.setVisible(show_space)
        self.downloads_retention_max_gb_spin.setEnabled(show_space)

    def _apply_download_settings_to_installers(self, settings: AppSettings) -> None:
        downloads_dir = Path(settings.downloads_path).expanduser()
        self._cached_download_versions.clear()
        self.base_installer.cache_dir = downloads_dir
        self.game_packs_installer.cache_dir = downloads_dir
        self.bitlcd_installer.cache_dir = downloads_dir
        self.optional_components_installer.cache_dir = downloads_dir
        self.base_installer.max_parallel_downloads = settings.parallel_downloads
        self.game_packs_installer.max_parallel_downloads = settings.parallel_downloads
        self.bitlcd_installer.max_parallel_downloads = settings.parallel_downloads
        self.optional_components_installer.max_parallel_downloads = settings.parallel_downloads
        self._shared_downloader.segmented_downloads_enabled = settings.segmented_downloads_enabled
        self._shared_downloader.segmented_download_min_size_bytes = settings.segmented_download_min_size_mb * 1024 * 1024
        self._shared_downloader.segmented_download_segments = settings.segmented_download_segments

    def _clear_downloads_now(self) -> None:
        result = clear_downloads_dir(self._downloads_dir())
        self._cached_download_versions.clear()
        self._push_status_message(f"Cleared {result.deleted_files} download file(s).")
        QMessageBox.information(
            self,
            "Downloads cleared",
            f"Removed {result.deleted_files} file(s) from the downloads cache.",
        )

    def _enforce_download_cache_policy(self) -> CacheCleanupResult:
        return enforce_download_cache_policy(
            self._downloads_dir(),
            str(self.downloads_retention_combo.currentData()),
            self._all_components_by_key.values(),
            days=self.downloads_retention_days_spin.value(),
            max_gb=self.downloads_retention_max_gb_spin.value(),
        )

    def _build_target_warning(self, message: str) -> QWidget:
        warning = QWidget()
        warning.setObjectName("warningBanner")
        layout = QHBoxLayout(warning)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(18, 18))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        message_label = QLabel(message)
        message_label.setObjectName("warningMessage")
        message_label.setWordWrap(True)

        layout.addWidget(icon_label)
        layout.addWidget(message_label, stretch=1)
        warning.hide()
        return warning

    def _refresh_target_validation(self) -> None:
        target = self._target_dir()
        if target is None:
            self.root_warning.hide()
            self.ntfs_warning.hide()
        else:
            self.root_warning.setVisible(not self._is_root_target(target))
            self.ntfs_warning.setVisible(not self._is_ntfs_target(target))

        bitlcd_target = self._bitlcd_target_dir()
        if bitlcd_target is None:
            self.bitlcd_warning.hide()
        else:
            self.bitlcd_warning.setVisible(not self._is_bitlcd_target(bitlcd_target))

    def _is_root_target(self, target: Path) -> bool:
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target
        anchor = resolved.anchor or target.anchor
        if not anchor:
            return False
        return resolved == Path(anchor)

    def _is_ntfs_target(self, target: Path) -> bool:
        filesystem = _filesystem_type_for_path(target)
        if filesystem is None:
            return False
        return filesystem.upper() == "NTFS"

    def _is_bitlcd_target(self, target: Path) -> bool:
        parts = [part.casefold() for part in target.parts if part not in {target.anchor, ""}]
        for index in range(len(parts) - 1):
            if parts[index] == "bitlcd" and parts[index + 1] == "thirdparty":
                return True
        return False

    def _update_logo_pixmap(self) -> None:
        if self._title_logo is None or self._logo_pixmap.isNull():
            return
        target_width = 212
        scaled = self._logo_pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
        self._title_logo.setPixmap(scaled)
        self._title_logo.setFixedSize(scaled.size())

    def _load_sidebar_assets(self) -> None:
        logo_path = _assets_dir() / "onesauce_companion_logo.png"
        self._logo_pixmap = QPixmap(str(logo_path))
        if self._logo_pixmap.isNull():
            if self._title_logo is not None:
                self._title_logo.setText("OnesaUCE")
                self._title_logo = None
        else:
            self._update_logo_pixmap()
        if hasattr(self, "sidebar_version_icon"):
            self.sidebar_version_icon.setPixmap(_cherry_icon_pixmap())
        if hasattr(self, "sidebar_version_icon_2"):
            self.sidebar_version_icon_2.setPixmap(_strawberry_icon_pixmap())
        if hasattr(self, "sidebar_version_icon_3"):
            self.sidebar_version_icon_3.setPixmap(_orange_icon_pixmap())

    def _schedule_scan(self) -> None:
        if self._loading_settings:
            return
        self._scan_timer.start()

    def _refresh_all_tables(self) -> None:
        self._games_catalog_target = None
        self._games_installed_target = None
        self._games_excluded_target = None
        self._collections_catalog_target = None
        self._cached_downloads_installed_statuses = {}
        self._downloads_action_widgets = {}
        self._start_installed_status_refresh()
        self._refresh_tweaks_screen()
        for component_screen in (BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN):
            if component_screen not in self._pending_screen_builders:
                self._refresh_screen_table(component_screen)
        self._refresh_downloader_screen()
        if GAMES_SCREEN not in self._pending_screen_builders:
            self._refresh_games_table()
        if COLLECTIONS_SCREEN not in self._pending_screen_builders:
            self._refresh_collections_table()

    def _handle_refresh_requested(self) -> None:
        button = self.sender()
        if isinstance(button, QPushButton):
            if button is getattr(self, "downloader_refresh_button", None):
                self._force_required_catalog_refresh = True
                self._force_system_pack_catalog_refresh = True
                self._force_bitlcd_catalog_refresh = True
                self._force_optional_catalog_refresh = True
            elif button is getattr(self, "refresh_button", None):
                self._force_required_catalog_refresh = True
            elif button is getattr(self, "game_packs_refresh_button", None):
                self._force_system_pack_catalog_refresh = True
            elif button is getattr(self, "bitlcd_refresh_button", None):
                self._force_bitlcd_catalog_refresh = True
            elif button is getattr(self, "optional_components_refresh_button", None):
                self._force_optional_catalog_refresh = True
            button.setText("Refreshing...")
            button.setEnabled(False)
            QApplication.processEvents()
            QTimer.singleShot(0, lambda btn=button: self._finish_manual_refresh(btn))
            return
        self._refresh_all_tables()

    def _finish_manual_refresh(self, button: QPushButton | None) -> None:
        try:
            self._refresh_all_tables()
        finally:
            if button is not None:
                button.setText("Refresh")
                button.setEnabled(True)

    def _refresh_screen_table(self, screen_index: int) -> None:
        if screen_index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            self._initialized_component_screens.add(screen_index)
        if screen_index == BASE_COMPONENTS_SCREEN:
            self._refresh_required_component_catalog(force_refresh=self._force_required_catalog_refresh)
            self._force_required_catalog_refresh = False
        elif screen_index == GAME_PACKS_SCREEN:
            self._refresh_system_pack_catalog(force_refresh=self._force_system_pack_catalog_refresh)
            self._force_system_pack_catalog_refresh = False
        elif screen_index == BITLCD_MARQUEES_SCREEN:
            self._refresh_bitlcd_catalog(force_refresh=self._force_bitlcd_catalog_refresh)
            self._force_bitlcd_catalog_refresh = False
        elif screen_index == OPTIONAL_COMPONENTS_SCREEN:
            self._refresh_optional_component_catalog(force_refresh=self._force_optional_catalog_refresh)
            self._force_optional_catalog_refresh = False
        table = self._table_for_screen(screen_index)
        components = self._components_for_screen(screen_index)
        installer = self._installer_for_screen(screen_index)
        target = self._target_dir_for_screen(screen_index)
        self._refresh_cached_download_versions_for_screen(screen_index)
        self._refresh_remote_sizes_for_screen(screen_index)
        if target is None:
            self._populate_missing_table(table, self._sorted_component_specs(screen_index, list(components)))
            self._update_primary_action(screen_index, [])
            self._sync_header_checkbox(screen_index)
            self._apply_sort_indicator(screen_index)
            if self.stack.currentIndex() == screen_index:
                if screen_index == BITLCD_MARQUEES_SCREEN:
                    self._push_status_message("Select a BitLCD target folder to scan.")
                else:
                    self._push_status_message("Select a target folder to scan.")
            return

        self._selection_sync = True
        statuses = self._sorted_component_statuses(screen_index, installer.scan_target(target))
        disabled_keys = {status.spec.key for status in statuses if status.status == "Installed"}
        self._disabled_component_keys[screen_index] = disabled_keys
        self._selected_component_keys.setdefault(screen_index, set()).difference_update(disabled_keys)
        table.setUpdatesEnabled(False)
        table.setRowCount(len(statuses))
        for row, status in enumerate(statuses):
            queue_entry = self._queue_entry_for_key(status.spec.key)
            if screen_index == OPTIONAL_COMPONENTS_SCREEN:
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["component"], status.spec.display_name)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["installed"], status.installed_version or "Not installed")
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["available"], status.spec.available_display)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["downloaded"], self._component_downloaded_display(status.spec))
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["size"], self._component_size_display(status.spec))
                self._set_status_cell(table, row, status.spec.key, OPTIONAL_TABLE_COLUMNS["status"])
                self._set_action_buttons_widget(table, row, status.spec, screen_index)
            else:
                self._set_item(table, row, BASE_TABLE_COLUMNS["component"], status.spec.display_name)
                self._set_item(table, row, BASE_TABLE_COLUMNS["installed"], status.installed_version or "Not installed")
                self._set_item(table, row, BASE_TABLE_COLUMNS["available"], status.spec.available_display)
                self._set_item(table, row, BASE_TABLE_COLUMNS["downloaded"], self._component_downloaded_display(status.spec))
                self._set_item(table, row, BASE_TABLE_COLUMNS["size"], self._component_size_display(status.spec))
                self._set_status_cell(table, row, status.spec.key, BASE_TABLE_COLUMNS["status"])
                self._set_action_buttons_widget(table, row, status.spec, screen_index)
            if queue_entry is not None:
                self._set_status_widget(status.spec.key, queue_entry.status, queue_entry.percent)
            elif status.spec.key not in self._active_components:
                self._set_status_widget(status.spec.key, status.status, 100 if status.status == "Installed" else 0)
        self._selection_sync = False
        table.setUpdatesEnabled(True)
        update_downloader_table_height(table)
        self._update_primary_action(screen_index, statuses)
        self._apply_sort_indicator(screen_index)
        if self.stack.currentIndex() == screen_index:
            self._push_status_message(f"Scanned {target}")

    def _populate_missing_table(self, table: QTableWidget, components: list[ComponentSpec]) -> None:
        screen_index = self._screen_for_table(table)
        self._disabled_component_keys[screen_index] = set()
        self._selection_sync = True
        table.setUpdatesEnabled(False)
        table.setRowCount(len(components))
        for row, spec in enumerate(components):
            queue_entry = self._queue_entry_for_key(spec.key)
            if screen_index == OPTIONAL_COMPONENTS_SCREEN:
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["component"], spec.display_name)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["installed"], "Not scanned")
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["available"], spec.available_display)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["downloaded"], self._component_downloaded_display(spec))
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["size"], self._component_size_display(spec))
                self._set_status_cell(table, row, spec.key, OPTIONAL_TABLE_COLUMNS["status"])
                self._set_action_buttons_widget(table, row, spec, screen_index)
            else:
                self._set_item(table, row, BASE_TABLE_COLUMNS["component"], spec.display_name)
                self._set_item(table, row, BASE_TABLE_COLUMNS["installed"], "Not scanned")
                self._set_item(table, row, BASE_TABLE_COLUMNS["available"], spec.available_display)
                self._set_item(table, row, BASE_TABLE_COLUMNS["downloaded"], self._component_downloaded_display(spec))
                self._set_item(table, row, BASE_TABLE_COLUMNS["size"], self._component_size_display(spec))
                self._set_status_cell(table, row, spec.key, BASE_TABLE_COLUMNS["status"])
                self._set_action_buttons_widget(table, row, spec, screen_index)
            if queue_entry is not None:
                self._set_status_widget(spec.key, queue_entry.status, queue_entry.percent)
            else:
                self._set_status_widget(spec.key, "Pending", 0)
        self._selection_sync = False
        table.setUpdatesEnabled(True)
        update_downloader_table_height(table)

    def _refresh_games_table(self) -> None:
        refresh_games_table(self)

    def _installed_games_for_current_target(self) -> set[tuple[str, str]]:
        return installed_games_for_current_target(self)

    def _sorted_filtered_games(self, installed_games: set[tuple[str, str]]):
        return sorted_filtered_games(self, installed_games)

    def _games_sort_key(self, entry, installed_games: set[tuple[str, str]]) -> Any:
        return games_sort_key(self, entry, installed_games)

    def _refresh_games_catalog(self) -> None:
        refresh_games_catalog(self)

    def _sync_games_collection_filter(self) -> None:
        sync_games_collection_filter(self)

    def _refresh_collections_catalog(self) -> None:
        refresh_collections_catalog(self)

    def _refresh_collections_table(self) -> None:
        refresh_collections_table(self)

    def _refresh_logs_screen(self) -> None:
        refresh_logs_screen(self)

    def _refresh_themes_screen(self) -> None:
        refresh_themes_screen(self)

    @Slot(int, int, object)
    def _handle_theme_entry_ready(self, completed: int, total: int, entry: object) -> None:
        on_theme_entry_ready(self, completed, total, entry)

    @Slot(object, str)
    def _handle_theme_catalog_finished(self, entries: object, target_key: str) -> None:
        on_theme_catalog_finished(self, entries, target_key)

    def _refresh_downloader_screen(self) -> None:
        if self._catalog_refresh_handle.running:
            return
        needs_network = (
            self._force_required_catalog_refresh
            or self._force_system_pack_catalog_refresh
            or self._force_bitlcd_catalog_refresh
            or self._force_optional_catalog_refresh
            or not self.required_component_catalog.is_loaded()
            or not self.system_pack_catalog.is_loaded()
            or not self.bitlcd_catalog.is_loaded()
            or not self.optional_component_catalog.is_loaded()
        )
        if needs_network:
            self._start_catalog_refresh()
        else:
            self._post_catalog_refresh()

    def _start_catalog_refresh(self) -> None:
        if self._catalog_refresh_handle.running:
            return

        jobs: list[tuple[str, object, bool]] = [
            ("required", self.required_component_catalog, self._force_required_catalog_refresh),
            ("system_pack", self.system_pack_catalog, self._force_system_pack_catalog_refresh),
            ("bitlcd", self.bitlcd_catalog, self._force_bitlcd_catalog_refresh),
            ("optional", self.optional_component_catalog, self._force_optional_catalog_refresh),
        ]
        self._force_required_catalog_refresh = False
        self._force_system_pack_catalog_refresh = False
        self._force_bitlcd_catalog_refresh = False
        self._force_optional_catalog_refresh = False
        self._catalog_refresh_completed = 0
        self._catalog_refresh_total = len(jobs)
        self._catalog_refresh_failed_keys = set()

        button = getattr(self, "downloads_refresh_button", None)
        if isinstance(button, QPushButton):
            button.setEnabled(False)

        worker = CatalogRefreshWorker(jobs)
        worker.specs_ready.connect(self._handle_catalog_specs)
        worker.refresh_failed.connect(self._handle_catalog_refresh_failed)
        worker.finished.connect(self._handle_catalog_refresh_finished)
        self._catalog_refresh_handle.start(
            worker,
            finish_signals=(worker.finished,),
            on_cleared=self._on_background_task_cleared,
        )
        self._update_loading_indicator()

    def _update_loading_indicator(self) -> None:
        progress = getattr(self, "startup_loading_progress", None)
        if progress is None:
            return
        catalog_running = self._catalog_refresh_handle.running
        remote_sizes_running = self._remote_sizes_handle.running
        installed_status_running = self._installed_status_handle.running
        if catalog_running:
            self._set_progress(progress, "Refreshing catalog… %v of %m", self._catalog_refresh_completed, self._catalog_refresh_total)
            return
        if installed_status_running:
            self._set_progress(progress, "Scanning installed components… %v of %m", self._installed_status_completed, self._installed_status_total)
            return
        if remote_sizes_running:
            self._set_progress(progress, "Fetching component sizes… %v of %m", self._remote_sizes_completed, self._remote_sizes_total)
            return
        if self._themes.rendering:
            progress.setRange(0, 1)
            progress.setValue(1)
            progress.setFormat("Rendering Theme… Please Wait")
            progress.show()
            return
        theme_catalog_running = self._themes.catalog_handle.running
        if theme_catalog_running:
            self._set_progress(progress, "Scanning themes… %v of %m", self._themes.catalog_completed, self._themes.catalog_total)
            return
        if self._screen_loading_label is not None:
            progress.setRange(0, 1)
            progress.setValue(1)
            progress.setFormat(f"Loading {self._screen_loading_label}… Please Wait")
            progress.show()
            return
        if self._startup_refresh_queue:
            progress.setRange(0, 1)
            progress.setValue(1)
            progress.setFormat("Loading… Please Wait")
            progress.show()
            return
        progress.hide()

    def _set_progress(self, progress: QProgressBar, fmt: str, completed: int, total: int) -> None:
        if total <= 0:
            progress.setRange(0, 0)
            progress.setFormat(fmt.split(" %v")[0].rstrip(" …") + "…")
        else:
            progress.setRange(0, total)
            progress.setValue(min(completed, total))
            progress.setFormat(fmt)
        progress.show()

    @Slot(str, object)
    def _handle_catalog_specs(self, key: str, specs: object) -> None:
        self._catalog_refresh_completed += 1
        self._update_loading_indicator()
        if not isinstance(specs, tuple):
            return
        if key == "required":
            if specs != self._required_specs:
                self._set_dynamic_specs(
                    screen_index=BASE_COMPONENTS_SCREEN,
                    specs=specs,
                    installer=self.base_installer,
                    source_labels=("Base Component",),
                )
        elif key == "system_pack":
            if specs != self._game_pack_specs:
                self._set_dynamic_specs(
                    screen_index=GAME_PACKS_SCREEN,
                    specs=specs,
                    installer=self.game_packs_installer,
                    source_labels=("System Pack", "Game Pack"),
                )
        elif key == "bitlcd":
            if specs != self._bitlcd_specs:
                self._set_dynamic_specs(
                    screen_index=BITLCD_MARQUEES_SCREEN,
                    specs=specs,
                    installer=self.bitlcd_installer,
                    source_labels=("BitLCD Marquee",),
                )
        elif key == "optional":
            if specs != self._optional_specs:
                self._set_dynamic_specs(
                    screen_index=OPTIONAL_COMPONENTS_SCREEN,
                    specs=specs,
                    installer=self.optional_components_installer,
                    source_labels=("Optional Component",),
                )

    @Slot(str)
    def _handle_catalog_refresh_failed(self, key: str) -> None:
        self._catalog_refresh_failed_keys.add(key)

    def _handle_catalog_refresh_finished(self) -> None:
        self._cached_downloads_installed_statuses = {}
        self._downloads_action_widgets = {}
        self._start_installed_status_refresh()
        self._post_catalog_refresh()
        button = getattr(self, "downloads_refresh_button", None)
        if isinstance(button, QPushButton):
            button.setEnabled(True)
        if self._catalog_refresh_failed_keys:
            LOGGER.warning(
                "Catalog refresh could not reach archive.org for: %s.",
                ", ".join(sorted(self._catalog_refresh_failed_keys)),
            )
            self._push_status_message(
                "Couldn't reach archive.org to refresh catalogs — showing last known data.",
                minimum_ms=5000,
            )
            self._catalog_refresh_user_initiated = False
        elif self._catalog_refresh_user_initiated:
            self._push_status_message("Downloads refreshed.")
            self._catalog_refresh_user_initiated = False
        self._update_loading_indicator()

    def _on_background_task_cleared(self) -> None:
        """Shared WorkerHandle on_cleared callback for loading-indicator tasks."""
        self._update_loading_indicator()
        self._finalize_close_if_ready()

    def _post_catalog_refresh(self) -> None:
        self._downloads.prune_operations()
        self._refresh_cached_download_versions_for_downloads()
        self._populate_downloads_filter_options()
        self._refresh_downloads_table()
        self._downloads.schedule()
        self._start_remote_sizes_refresh()

    def _start_remote_sizes_refresh(self) -> bool:
        if self._remote_sizes_handle.running:
            self._remote_sizes_restart_pending = True
            return False
        pending: list[ComponentSpec] = []
        for spec in self._all_download_specs():
            if spec.key in self._remote_size_overrides:
                continue
            if spec in self._game_pack_specs:
                continue
            pending.append(spec)
        if not pending:
            return False

        credentials = self._archive_credentials()
        self._remote_sizes_completed = 0
        self._remote_sizes_total = len(pending)
        worker = RemoteSizesWorker(self.archive_metadata, pending, credentials)
        worker.size_ready.connect(self._handle_remote_size_ready)
        worker.finished.connect(self._handle_remote_sizes_finished)
        self._remote_sizes_handle.start(
            worker,
            finish_signals=(worker.finished,),
            on_cleared=self._on_remote_sizes_cleared,
        )
        self._update_loading_indicator()
        return True

    @Slot(str, str, object)
    def _handle_remote_size_ready(self, spec_key: str, size_display: str, size_bytes: object) -> None:
        bytes_value = size_bytes if isinstance(size_bytes, int) else None
        self._remote_size_overrides[spec_key] = (size_display, bytes_value)
        self._remote_sizes_completed += 1
        self._update_loading_indicator()

    def _handle_remote_sizes_finished(self) -> None:
        self._refresh_downloads_table()
        self._update_loading_indicator()

    def _on_remote_sizes_cleared(self) -> None:
        self._update_loading_indicator()
        if self._remote_sizes_restart_pending:
            self._remote_sizes_restart_pending = False
            self._start_remote_sizes_refresh()
        self._finalize_close_if_ready()

    def _start_installed_status_refresh(self) -> bool:
        if self._installed_status_handle.running:
            self._installed_status_restart_pending = True
            return False
        target = self._target_dir()
        bitlcd_target = self._bitlcd_target_dir()
        jobs: list[tuple[str, object, object]] = [
            ("required", self.base_installer, target),
            ("game_packs", self.game_packs_installer, target),
            ("optional", self.optional_components_installer, target),
            ("bitlcd", self.bitlcd_installer, bitlcd_target),
        ]
        self._installed_status_pending_keys = {key for key, _, _ in jobs}
        self._installed_status_completed = 0
        self._installed_status_total = len(jobs)
        worker = InstalledStatusWorker(jobs)
        worker.statuses_ready.connect(self._handle_installed_statuses_ready)
        worker.finished.connect(self._handle_installed_statuses_finished)
        self._installed_status_handle.start(
            worker,
            finish_signals=(worker.finished,),
            on_cleared=self._on_installed_status_cleared,
        )
        self._update_loading_indicator()
        return True

    @Slot(str, object)
    def _handle_installed_statuses_ready(self, installer_key: str, statuses: object) -> None:
        if isinstance(statuses, dict):
            for spec_key, status in statuses.items():
                if isinstance(spec_key, str):
                    self._cached_downloads_installed_statuses[spec_key] = status
        self._installed_status_pending_keys.discard(installer_key)
        self._installed_status_completed += 1
        self._update_loading_indicator()
        if hasattr(self, "downloads_table"):
            self._refresh_downloads_table()

    def _handle_installed_statuses_finished(self) -> None:
        self._installed_status_pending_keys.clear()
        self._update_loading_indicator()

    def _on_installed_status_cleared(self) -> None:
        self._update_loading_indicator()
        if self._installed_status_restart_pending:
            self._installed_status_restart_pending = False
            self._start_installed_status_refresh()
        self._finalize_close_if_ready()

    def _handle_downloads_refresh_requested(self) -> None:
        if self._catalog_refresh_handle.running:
            return
        self._force_required_catalog_refresh = True
        self._force_system_pack_catalog_refresh = True
        self._force_bitlcd_catalog_refresh = True
        self._force_optional_catalog_refresh = True
        self._catalog_refresh_user_initiated = True
        self._append_downloads_log_line("Refreshing downloads...")
        self._push_status_message("Refreshing catalog…")
        self._refresh_downloader_screen()

    def _all_download_specs(self) -> tuple[ComponentSpec, ...]:
        return (*self._required_specs, *self._game_pack_specs, *self._bitlcd_specs, *self._optional_specs)

    def _refresh_cached_download_versions_for_downloads(self) -> None:
        downloads_dir = self._downloads_dir()
        files = list_cached_archive_files(downloads_dir)
        for spec in self._all_download_specs():
            self._cached_download_versions[spec.key] = cached_download_version(downloads_dir, spec, files=files)

    def _downloads_component_type_display(self, spec: ComponentSpec) -> str:
        if spec in self._required_specs:
            return "Base Component"
        if spec in self._game_pack_specs:
            return "System Pack"
        if spec in self._bitlcd_specs:
            return "BitLCD Marquee"
        if spec.component_type == "Theme":
            return "Theme"
        if spec.component_type == "Videos":
            return "Video Pack"
        return "Optional Component"

    def _downloads_target_dir_for_spec(self, spec: ComponentSpec) -> Path | None:
        if spec in self._bitlcd_specs:
            return self._bitlcd_target_dir()
        return self._target_dir()

    def _downloads_installer_for_spec(self, spec: ComponentSpec) -> Installer:
        if spec in self._required_specs:
            return self.base_installer
        if spec in self._game_pack_specs:
            return self.game_packs_installer
        if spec in self._bitlcd_specs:
            return self.bitlcd_installer
        return self.optional_components_installer

    def _downloads_installed_statuses(self) -> dict[str, ComponentStatus]:
        statuses: dict[str, ComponentStatus] = {}
        target = self._target_dir()
        bitlcd_target = self._bitlcd_target_dir()
        if target is not None:
            statuses.update({status.spec.key: status for status in self.base_installer.scan_target(target)})
            statuses.update({status.spec.key: status for status in self.game_packs_installer.scan_target(target)})
            statuses.update({status.spec.key: status for status in self.optional_components_installer.scan_target(target)})
        if bitlcd_target is not None:
            statuses.update({status.spec.key: status for status in self.bitlcd_installer.scan_target(bitlcd_target)})
        return statuses

    def _downloads_baseline_status(self, spec: ComponentSpec, installed_status: ComponentStatus | None) -> str:
        downloaded_version = self._component_downloaded_version(spec)
        if installed_status is not None and installed_status.status == "Installed":
            return "Up-to-Date"
        if downloaded_version == spec.available_version:
            return "Ready for Install"
        if installed_status is not None and installed_status.status == "Update Available":
            return "Update Available"
        if installed_status is None and self._installed_status_pending_for_spec(spec):
            return "Checking…"
        return "Not Installed"

    def _installed_status_pending_for_spec(self, spec: ComponentSpec) -> bool:
        if not self._installed_status_pending_keys:
            return False
        if spec in self._required_specs:
            return "required" in self._installed_status_pending_keys
        if spec in self._game_pack_specs:
            return "game_packs" in self._installed_status_pending_keys
        if spec in self._bitlcd_specs:
            return "bitlcd" in self._installed_status_pending_keys
        return "optional" in self._installed_status_pending_keys

    def _downloads_row_view(self, spec: ComponentSpec, installed_status: ComponentStatus | None) -> DownloadsRowView:
        operation = self._downloads.operations.get(spec.key)
        status = operation.status if operation is not None else self._downloads_baseline_status(spec, installed_status)
        if operation is None:
            percent = 100.0 if status == "Up-to-Date" else 0.0
            self._downloads_status_state[spec.key] = (status, percent)
        else:
            self._downloads_status_state.setdefault(spec.key, (status, 0.0))
        return DownloadsRowView(
            spec=spec,
            component_type=self._downloads_component_type_display(spec),
            available_version=spec.available_display,
            downloaded_version=self._component_downloaded_version(spec),
            installed_version=installed_status.installed_version if installed_status is not None else None,
            status=status,
        )

    def _downloads_all_status_values(self) -> tuple[str, ...]:
        return (
            "Up-to-Date",
            "Update Available",
            "Ready for Install",
            "Not Installed",
            "Downloading",
            "Pending Download",
            "Pending Install",
            "Installing",
        )

    def _populate_downloads_filter_options(self) -> None:
        if not hasattr(self, "downloads_type_filter"):
            return
        self._downloads_filtering = True
        try:
            current_type = self.downloads_type_filter.currentText()
            current_status = self.downloads_status_filter.currentText()
            type_values = ["Any Component Type"] + sorted(
                {self._downloads_component_type_display(spec) for spec in self._all_download_specs()}
            )
            self.downloads_type_filter.clear()
            self.downloads_type_filter.addItems(type_values)
            type_index = max(0, self.downloads_type_filter.findText(current_type))
            self.downloads_type_filter.setCurrentIndex(type_index)

            self.downloads_status_filter.clear()
            self.downloads_status_filter.addItem("Any Status")
            self.downloads_status_filter.addItems(list(self._downloads_all_status_values()))
            status_index = max(0, self.downloads_status_filter.findText(current_status))
            self.downloads_status_filter.setCurrentIndex(status_index)
        finally:
            self._downloads_filtering = False

    def _handle_downloads_filter_changed(self) -> None:
        if self._downloads_filtering:
            return
        if self.sender() is self.downloads_name_filter:
            self._downloads_filter_debounce_timer.start()
        else:
            self._refresh_downloads_table()

    def _downloads_filtered_rows(self) -> list[DownloadsRowView]:
        statuses_by_key = self._cached_downloads_installed_statuses
        type_filter = self.downloads_type_filter.currentText().strip()
        status_filter = self.downloads_status_filter.currentText().strip()
        name_filter = self.downloads_name_filter.text().strip().lower()
        rows: list[DownloadsRowView] = []
        for spec in self._all_download_specs():
            row = self._downloads_row_view(spec, statuses_by_key.get(spec.key))
            if type_filter and type_filter != "Any Component Type" and row.component_type != type_filter:
                continue
            if status_filter and status_filter != "Any Status" and not self._downloads_status_matches_filter(row.status, status_filter):
                continue
            if name_filter and name_filter not in row.spec.display_name.lower():
                continue
            rows.append(row)
        return rows

    @staticmethod
    def _downloads_status_matches_filter(status: str, status_filter: str) -> bool:
        if status_filter == "Pending Download":
            return status in {"Pending Download", "Pending Download (Paused)"}
        if status_filter == "Downloading":
            return status in {"Downloading", "Download Paused"}
        if status_filter == "Installing":
            return status in {"Installing", "Install Paused"}
        return status == status_filter

    def _refresh_downloads_table(self) -> None:
        if not hasattr(self, "downloads_table"):
            return
        self._downloads_table_refresh_pending = False
        rows = self._downloads_filtered_rows()
        self._downloads_visible_keys = [row.spec.key for row in rows]
        self._downloads_status_widgets = {}
        self.downloads_table.setUpdatesEnabled(False)
        self.downloads_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self._set_item(self.downloads_table, row_index, 0, row.spec.display_name)
            self._set_item(self.downloads_table, row_index, 1, row.component_type)
            self._set_item(self.downloads_table, row_index, 2, row.available_version)
            self._set_item(self.downloads_table, row_index, 3, row.downloaded_version or "Not downloaded")
            self._set_item(self.downloads_table, row_index, 4, row.installed_version or "Not installed")
            self._set_item(self.downloads_table, row_index, 5, self._component_size_display(row.spec))
            self._set_downloads_status_cell(row_index, row.spec.key, row.status)
            self._set_downloads_action_buttons_widget(row_index, row)
        self.downloads_table.setUpdatesEnabled(True)
        self._update_downloads_batch_buttons()

    def _schedule_downloads_table_refresh(self) -> None:
        if self._downloads_table_refresh_pending:
            return
        self._downloads_table_refresh_pending = True
        QTimer.singleShot(0, self._refresh_downloads_table)

    def _set_downloads_status_cell(self, row_index: int, component_key: str, fallback_status: str) -> None:
        status, percent = self._downloads_status_state.get(
            component_key,
            (fallback_status, 100.0 if fallback_status == "Up-to-Date" else 0.0),
        )
        widget = ComponentStatusCell()
        widget.set_status(self._display_downloads_status(status), percent)
        self._downloads_status_widgets[component_key] = widget
        self.downloads_table.setCellWidget(row_index, 6, widget)

    def _set_downloads_status_widget(self, component_key: str, status: str, percent: float) -> None:
        self._downloads_status_state[component_key] = (status, percent)
        widget = self._downloads_status_widgets.get(component_key)
        if widget is not None and isValid(widget):
            widget.set_status(self._display_downloads_status(status), percent)

    @staticmethod
    def _display_downloads_status(status: str) -> str:
        if status == "Download Paused":
            return "Downloading (Paused)"
        if status == "Install Paused":
            return "Installing (Paused)"
        return status

    def _set_downloads_action_buttons_widget(self, row_index: int, row: DownloadsRowView) -> None:
        operation = self._downloads.operations.get(row.spec.key)
        download_enabled = operation is None
        install_enabled = operation is None and self._downloads_can_install(row)
        pause_resume_enabled = operation is not None
        cancel_enabled = operation is not None
        pause_resume_label = (
            "Resume"
            if operation is not None and operation.status in {"Pending Download (Paused)", "Download Paused", "Install Paused"}
            else "Pause"
        )

        cached = self._downloads_action_widgets.get(row.spec.key)
        if (
            cached is not None
            and isValid(cached[0])
            and self.downloads_table.cellWidget(row_index, 7) is cached[0]
        ):
            # Widget is already at exactly this cell — update button states in place.
            # Moving a cell widget via setCellWidget triggers deleteLater on the displaced
            # widget; checking the cell position first avoids that entirely.
            container, download_button, install_button, pause_resume_button, cancel_button = cached
            _update_downloads_icon_button(download_button, "Download", "download", download_enabled)
            _update_downloads_icon_button(install_button, "Install", "install", install_enabled)
            _update_downloads_icon_button(pause_resume_button, pause_resume_label, pause_resume_label.lower(), pause_resume_enabled)
            _update_downloads_icon_button(cancel_button, "Cancel", "cancel", cancel_enabled)
            return

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        download_button = self._build_downloads_icon_button("Download", "download", download_enabled)
        install_button = self._build_downloads_icon_button("Install", "install", install_enabled)
        pause_resume_button = self._build_downloads_icon_button(pause_resume_label, pause_resume_label.lower(), pause_resume_enabled)
        cancel_button = self._build_downloads_icon_button("Cancel", "cancel", cancel_enabled)
        for button in (download_button, install_button, pause_resume_button, cancel_button):
            layout.addWidget(button)
        download_button.clicked.connect(lambda _=False, spec=row.spec: self._request_download_for_spec(spec))
        install_button.clicked.connect(lambda _=False, spec=row.spec: self._request_install_for_spec(spec))
        pause_resume_button.clicked.connect(lambda _=False, spec=row.spec: self._downloads.toggle_row_pause(spec.key))
        cancel_button.clicked.connect(lambda _=False, spec=row.spec: self._downloads.cancel_row(spec.key))
        self._downloads_action_widgets[row.spec.key] = (container, download_button, install_button, pause_resume_button, cancel_button)
        self.downloads_table.setCellWidget(row_index, 7, container)

    def _build_downloads_icon_button(self, tooltip: str, icon_name: str, enabled: bool) -> QPushButton:
        button = QPushButton()
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(36, 36)
        button.setIconSize(QSize(18, 18))
        button.setIcon(_downloads_action_icon(icon_name))
        button.setEnabled(enabled)
        button.setStyleSheet(_DOWNLOADS_ICON_BUTTON_STYLESHEET)
        return button

    def _downloads_can_install(self, row: DownloadsRowView) -> bool:
        downloaded_version = row.downloaded_version
        if downloaded_version is None:
            return False
        if downloaded_version == row.spec.available_version:
            return True
        return row.status == "Ready for Install"

    def _update_downloads_batch_buttons(self) -> None:
        _update_downloads_icon_button(
            self.downloads_updates_button,
            "Download Updates",
            "download",
            bool(self._downloads_update_candidates()),
        )
        _update_downloads_icon_button(
            self.downloads_all_button,
            "Download All",
            "download-all",
            bool(self._downloads_combined_download_candidates()),
        )
        _update_downloads_icon_button(
            self.downloads_install_ready_button,
            "Install Ready",
            "install",
            bool(self._downloads_install_candidates()),
        )
        visible_operations = [self._downloads.operations.get(key) for key in self._downloads_visible_keys]
        self.downloads_pause_all_button.setEnabled(
            any(op is not None and op.status in {"Pending Download", "Pending Install", "Downloading", "Installing"} for op in visible_operations)
        )
        self.downloads_resume_all_button.setEnabled(
            any(op is not None and op.status in {"Pending Download (Paused)", "Download Paused", "Install Paused"} for op in visible_operations)
        )
        self.downloads_cancel_all_button.setEnabled(any(op is not None for op in visible_operations))

    def _downloads_update_candidates(self) -> list[DownloadsRowView]:
        return [
            row
            for row in self._downloads_filtered_rows()
            if row.status == "Update Available"
            and row.downloaded_version != row.spec.available_version
            and self._downloads.operations.get(row.spec.key) is None
        ]

    def _downloads_all_candidates(self) -> list[DownloadsRowView]:
        return [
            row
            for row in self._downloads_filtered_rows()
            if row.downloaded_version is None
            and row.installed_version is None
            and self._downloads.operations.get(row.spec.key) is None
        ]

    def _downloads_install_candidates(self) -> list[DownloadsRowView]:
        return [
            row
            for row in self._downloads_filtered_rows()
            if row.status == "Ready for Install"
            and self._downloads.operations.get(row.spec.key) is None
        ]

    def _downloads_combined_download_candidates(self) -> list[DownloadsRowView]:
        candidates: list[DownloadsRowView] = []
        seen_keys: set[str] = set()
        for row in [*self._downloads_update_candidates(), *self._downloads_all_candidates()]:
            if row.spec.key in seen_keys:
                continue
            seen_keys.add(row.spec.key)
            candidates.append(row)
        return candidates

    def _handle_downloads_batch_download_updates(self) -> None:
        candidates = self._downloads_update_candidates()
        if not candidates:
            message = "No component updates need downloading."
            self._append_downloads_log_line(message)
            self._push_status_message(message, minimum_ms=3000)
            return
        for row in candidates:
            self._downloads.queue_download(row.spec)
        message = f"Queued {len(candidates)} component update download(s)."
        self._append_downloads_log_line(message)
        self._push_status_message(message, minimum_ms=3000)

    def _handle_downloads_batch_download_all(self) -> None:
        candidates = self._downloads_combined_download_candidates()
        if not candidates:
            message = "No components need downloading."
            self._append_downloads_log_line(message)
            self._push_status_message(message, minimum_ms=3000)
            return
        for row in candidates:
            self._downloads.queue_download(row.spec)
        message = f"Queued {len(candidates)} component download(s)."
        self._append_downloads_log_line(message)
        self._push_status_message(message, minimum_ms=3000)

    def _handle_downloads_batch_install_ready(self) -> None:
        candidates = self._downloads_install_candidates()
        if not candidates:
            message = "No components are ready to install."
            self._append_downloads_log_line(message)
            self._push_status_message(message, minimum_ms=3000)
            return
        for row in candidates:
            self._downloads.queue_install(row.spec)
        message = f"Queued {len(candidates)} component install(s)."
        self._append_downloads_log_line(message)
        self._push_status_message(message, minimum_ms=3000)

    def _handle_downloads_batch_pause_all(self) -> None:
        for component_key in list(self._downloads_visible_keys):
            operation = self._downloads.operations.get(component_key)
            if operation is None:
                continue
            if operation.status in {"Pending Download", "Downloading"}:
                self._downloads.pause_operation(component_key, "download")
            elif operation.status in {"Pending Install", "Installing"}:
                self._downloads.pause_operation(component_key, "install")
        self._schedule_downloads_table_refresh()

    def _handle_downloads_batch_resume_all(self) -> None:
        for component_key in list(self._downloads_visible_keys):
            self._downloads.resume_operation(component_key)
        self._schedule_downloads_table_refresh()
        self._downloads.schedule()

    def _handle_downloads_batch_cancel_all(self) -> None:
        for component_key in list(self._downloads_visible_keys):
            self._downloads.cancel_row(component_key, refresh=False)
        self._refresh_downloader_screen()

    def _request_download_for_spec(self, spec: ComponentSpec, *, prompt_for_cached_latest: bool = True) -> None:
        if self._downloads.operations.get(spec.key) is not None:
            return
        if prompt_for_cached_latest and self._component_downloaded_version(spec) == spec.available_version:
            self._prompt_download_overwrite(spec)
            return
        self._downloads.queue_download(spec)

    def _request_install_for_spec(self, spec: ComponentSpec) -> None:
        if self._downloads.operations.get(spec.key) is not None:
            return
        downloaded_version = self._component_downloaded_version(spec)
        if downloaded_version is None:
            live_version = cached_download_version(self._downloads_dir(), spec)
            if live_version is not None:
                self._cached_download_versions[spec.key] = live_version
                downloaded_version = live_version
        if downloaded_version is None:
            QMessageBox.information(self, "Download required", f"Download {spec.display_name} before installing it.")
            return
        if downloaded_version != spec.available_version:
            QMessageBox.information(
                self,
                "Update required",
                f"Download the latest {spec.display_name} archive before installing it.",
            )
            return
        target_dir = self._downloads_target_dir_for_spec(spec)
        if target_dir is None:
            if spec in self._bitlcd_specs:
                message = "Choose the BitLCD folder in Settings before installing BitLCD Marquee components."
            else:
                message = "Choose the target folder in Settings before installing components."
            QMessageBox.information(self, "Target required", message)
            return
        installed_status = self._cached_downloads_installed_statuses.get(spec.key)
        if installed_status is not None and installed_status.status == "Installed":
            self._prompt_reinstall_component(spec)
            return
        self._downloads.queue_install(spec)

    def _prompt_download_overwrite(self, spec: ComponentSpec) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Overwrite download")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(f"{spec.display_name} {spec.available_version} is already cached.")
        dialog.setInformativeText("Overwrite the local archive and download it again?")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setModal(False)
        dialog.finished.connect(
            lambda result, message_box=dialog, selected_spec=spec: self._handle_download_overwrite_prompt_finished(
                message_box,
                selected_spec,
                result,
            )
        )
        self._downloads_prompt_dialogs.append(dialog)
        dialog.open()

    def _handle_download_overwrite_prompt_finished(
        self,
        dialog: QMessageBox,
        spec: ComponentSpec,
        result: int,
    ) -> None:
        if dialog in self._downloads_prompt_dialogs:
            self._downloads_prompt_dialogs.remove(dialog)
        dialog.deleteLater()
        if result != int(QMessageBox.StandardButton.Yes):
            return
        cached_archive = self._downloads_installer_for_spec(spec).cached_archive_path(spec)
        if cached_archive is not None:
            cached_archive.unlink(missing_ok=True)
        partial_archive = self._downloads_dir() / f"{spec.cache_name}.part"
        partial_archive.unlink(missing_ok=True)
        self._cached_download_versions.pop(spec.key, None)
        self._downloads.queue_download(spec)

    def _prompt_reinstall_component(self, spec: ComponentSpec) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Reinstall component")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(f"{spec.display_name} {spec.available_version} is already installed.")
        dialog.setInformativeText("Reinstall and overwrite the current local version?")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setModal(False)
        dialog.finished.connect(
            lambda result, message_box=dialog, selected_spec=spec: self._handle_reinstall_prompt_finished(
                message_box,
                selected_spec,
                result,
            )
        )
        self._downloads_prompt_dialogs.append(dialog)
        dialog.open()

    def _handle_reinstall_prompt_finished(
        self,
        dialog: QMessageBox,
        spec: ComponentSpec,
        result: int,
    ) -> None:
        if dialog in self._downloads_prompt_dialogs:
            self._downloads_prompt_dialogs.remove(dialog)
        dialog.deleteLater()
        if result != int(QMessageBox.StandardButton.Yes):
            return
        self._downloads.queue_install(spec)

    def _append_downloads_log_line(self, message: str) -> None:
        if hasattr(self, "downloads_log_output"):
            self.downloads_log_output.appendPlainText(message)

    def _select_log(self, log_key: str) -> None:
        select_log(self, log_key)

    def _show_log_contents(self, log_key: str) -> None:
        show_log_contents(self, log_key)

    def _load_full_log(self) -> None:
        load_full_log(self)

    @Slot(str, str, bool)
    def _handle_log_load_finished(self, log_key: str, content: str, truncated: bool) -> None:
        on_log_load_finished(self, log_key, content, truncated)

    @Slot(str)
    def _handle_log_load_failed(self, log_key: str) -> None:
        on_log_load_failed(self, log_key)

    def _log_file_paths(self) -> dict[str, Path]:
        return log_file_paths(self)

    def _update_log_wrap_mode(self) -> None:
        update_log_wrap_mode(self)

    def _handle_log_wrap_toggled(self, _state: int) -> None:
        handle_log_wrap_toggled(self, _state)

    def _handle_log_reverse_toggled(self, _state: int) -> None:
        handle_log_reverse_toggled(self, _state)

    def _change_log_colors(self) -> None:
        change_log_colors(self)

    def _filtered_log_content(self, content: str) -> str:
        return filtered_log_content(self, content)

    def _log_level_for_line(self, line: str) -> str:
        return log_level_for_line(line)

    def _sorted_filtered_collections(self) -> list[CollectionCatalogEntry]:
        return sorted_filtered_collections(self)

    def _collections_sort_key(self, entry: CollectionCatalogEntry) -> Any:
        return collections_sort_key(self, entry)

    def _set_collection_name_cell(
        self,
        row: int,
        entry: CollectionCatalogEntry,
        navigation_entries: list[CollectionCatalogEntry],
        navigation_index: int,
    ) -> None:
        set_collection_name_cell(self, row, entry, navigation_entries, navigation_index)

    def _set_collection_parent_cell(self, row: int, entry: CollectionCatalogEntry) -> None:
        set_collection_parent_cell(self, row, entry)

    def _set_collection_game_count_cell(self, row: int, entry: CollectionCatalogEntry) -> None:
        set_collection_game_count_cell(self, row, entry)

    def _open_collection_details_by_name(self, collection_name: str) -> None:
        open_collection_details_by_name(self, collection_name)

    def _open_collection_details_dialog(
        self,
        entry: CollectionCatalogEntry,
        navigation_entries: list[CollectionCatalogEntry] | None = None,
        navigation_index: int | None = None,
    ) -> None:
        # Replace the COLLECTION_DETAILS_SCREEN slot with a fresh details
        # widget, dispose the previous one if any, then navigate.
        previous = self.stack.widget(COLLECTION_DETAILS_SCREEN)
        new_screen = CollectionDetailsScreen(
            entry, self._target_dir(), navigation_entries, navigation_index, self
        )
        self.stack.removeWidget(previous)
        self.stack.insertWidget(COLLECTION_DETAILS_SCREEN, new_screen)
        if isinstance(previous, CollectionDetailsScreen):
            previous.dispose()
        if previous is not None:
            previous.deleteLater()
        self._change_screen(COLLECTION_DETAILS_SCREEN)

    def _show_games_for_collection(self, collection_name: str) -> None:
        show_games_for_collection(self, collection_name)

    def _handle_collections_header_clicked(self, section: int) -> None:
        handle_collections_header_clicked(self, section)

    def _reset_collections_page_and_refresh(self, *_args: Any) -> None:
        reset_collections_page_and_refresh(self)

    def _set_collections_page(self, page: int) -> None:
        set_collections_page(self, page)

    def _go_to_last_collections_page(self) -> None:
        go_to_last_collections_page(self)

    def _change_collections_page_size(self, *_args: Any) -> None:
        change_collections_page_size(self)

    def _update_collections_pagination(self, total_items: int, total_pages: int) -> None:
        update_collections_pagination(self, total_items, total_pages)

    def _set_games_name_cell(
        self,
        row: int,
        entry: GameManifestEntry,
        status: str,
        navigation_entries: list[GameManifestEntry],
        navigation_index: int,
        installed_games: set[tuple[str, str]],
    ) -> None:
        set_games_name_cell(self, row, entry, status, navigation_entries, navigation_index, installed_games)

    def _open_game_details_dialog(
        self,
        entry: GameManifestEntry,
        installed: bool,
        navigation_entries: list[GameManifestEntry],
        navigation_index: int,
        installed_keys: set[tuple[str, str]],
    ) -> None:
        # Replace the GAME_DETAILS_SCREEN slot with a fresh details widget,
        # dispose the previous one if any, then navigate via _change_screen.
        previous = self.stack.widget(GAME_DETAILS_SCREEN)
        new_screen = GameDetailsScreen(
            entry,
            installed,
            self._target_dir(),
            self._bitlcd_target_dir(),
            navigation_entries,
            navigation_index,
            installed_keys,
            self,
        )
        self.stack.removeWidget(previous)
        self.stack.insertWidget(GAME_DETAILS_SCREEN, new_screen)
        if isinstance(previous, GameDetailsScreen):
            previous.dispose()
        if previous is not None:
            previous.deleteLater()
        self._change_screen(GAME_DETAILS_SCREEN)

    def _handle_games_header_clicked(self, section: int) -> None:
        handle_games_header_clicked(self, section)

    def _reset_games_page_and_refresh(self, *_args: Any) -> None:
        reset_games_page_and_refresh(self)

    def _set_games_page(self, page: int) -> None:
        set_games_page(self, page)

    def _go_to_last_games_page(self) -> None:
        go_to_last_games_page(self)

    def _change_games_page_size(self, *_args: Any) -> None:
        change_games_page_size(self)

    def _update_games_pagination(self, total_items: int, total_pages: int) -> None:
        update_games_pagination(self, total_items, total_pages)

    def _set_item(self, table: QTableWidget, row: int, column: int, text: str, alignment: Qt.AlignmentFlag | None = None) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if alignment is not None:
            item.setTextAlignment(int(alignment))
        table.setItem(row, column, item)

    def _initialize_status_cells(self, components: tuple[ComponentSpec, ...]) -> None:
        for spec in components:
            self._status_state.setdefault(spec.key, ("Pending", 0))

    def _set_status_cell(self, table: QTableWidget, row: int, component_key: str, column: int) -> None:
        status, percent = self._status_state.get(component_key, ("Pending", 0))
        widget = ComponentStatusCell()
        widget.set_status(status, percent)
        self._status_widgets[component_key] = widget
        table.setCellWidget(row, column, widget)

    def _handle_table_header_clicked(self, screen_index: int, section: int) -> None:
        if section not in self._sortable_columns(screen_index):
            return
        current_column, current_order = self._sort_states[screen_index]
        if current_column == section:
            next_order = (
                Qt.SortOrder.DescendingOrder
                if current_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
            self._sort_states[screen_index] = (section, next_order)
        else:
            self._sort_states[screen_index] = (section, Qt.SortOrder.AscendingOrder)

        if screen_index == QUEUE_SCREEN:
            self._sort_queue_entries()
            self._refresh_queue_table()
            self._save_settings()
            return
        self._refresh_screen_table(screen_index)

    def _sortable_columns(self, screen_index: int) -> set[int]:
        if screen_index == QUEUE_SCREEN:
            return {
                QUEUE_TABLE_COLUMNS["component"],
                QUEUE_TABLE_COLUMNS["source"],
                QUEUE_TABLE_COLUMNS["available"],
                QUEUE_TABLE_COLUMNS["size"],
                QUEUE_TABLE_COLUMNS["status"],
            }
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return {
                OPTIONAL_TABLE_COLUMNS["component"],
                OPTIONAL_TABLE_COLUMNS["installed"],
                OPTIONAL_TABLE_COLUMNS["available"],
                OPTIONAL_TABLE_COLUMNS["downloaded"],
                OPTIONAL_TABLE_COLUMNS["size"],
                OPTIONAL_TABLE_COLUMNS["status"],
            }
        return {
            BASE_TABLE_COLUMNS["component"],
            BASE_TABLE_COLUMNS["installed"],
            BASE_TABLE_COLUMNS["available"],
            BASE_TABLE_COLUMNS["downloaded"],
            BASE_TABLE_COLUMNS["size"],
            BASE_TABLE_COLUMNS["status"],
        }

    def _apply_sort_indicator(self, screen_index: int) -> None:
        table = self.queue_table if screen_index == QUEUE_SCREEN else self._table_for_screen(screen_index)
        column, order = self._sort_states[screen_index]
        table.horizontalHeader().setSortIndicatorShown(column >= 0)
        if column >= 0:
            table.horizontalHeader().setSortIndicator(column, order)

    def _sorted_component_specs(self, screen_index: int, components: list[ComponentSpec]) -> list[ComponentSpec]:
        column, order = self._sort_states[screen_index]
        size_column = OPTIONAL_TABLE_COLUMNS["size"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["size"]
        if column == size_column:
            return self._sort_by_size(
                components,
                key_fn=self._component_size_bytes,
                descending=order == Qt.SortOrder.DescendingOrder,
            )
        reverse = order == Qt.SortOrder.DescendingOrder
        return sorted(components, key=lambda spec: self._component_spec_sort_key(screen_index, column, spec), reverse=reverse)

    def _sorted_component_statuses(self, screen_index: int, statuses: list[Any]) -> list[Any]:
        column, order = self._sort_states[screen_index]
        size_column = OPTIONAL_TABLE_COLUMNS["size"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["size"]
        if column == size_column:
            return self._sort_by_size(
                statuses,
                key_fn=lambda status: self._component_size_bytes(status.spec),
                descending=order == Qt.SortOrder.DescendingOrder,
            )
        reverse = order == Qt.SortOrder.DescendingOrder
        return sorted(statuses, key=lambda status: self._component_status_sort_key(screen_index, column, status), reverse=reverse)

    def _component_spec_sort_key(self, screen_index: int, column: int, spec: ComponentSpec) -> Any:
        component_column = OPTIONAL_TABLE_COLUMNS["component"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["component"]
        installed_column = OPTIONAL_TABLE_COLUMNS["installed"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["installed"]
        available_column = OPTIONAL_TABLE_COLUMNS["available"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["available"]
        downloaded_column = OPTIONAL_TABLE_COLUMNS["downloaded"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["downloaded"]
        size_column = OPTIONAL_TABLE_COLUMNS["size"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["size"]
        status_column = OPTIONAL_TABLE_COLUMNS["status"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["status"]
        if column == component_column:
            return spec.display_name.casefold()
        if column == installed_column:
            return self._version_sort_key(None)
        if column == available_column:
            return self._version_sort_key(spec.available_version)
        if column == downloaded_column:
            return self._version_sort_key(self._component_downloaded_version(spec))
        if column == size_column:
            return self._size_sort_key(self._component_size_bytes(spec), self._component_size_display(spec))
        if column == status_column:
            return self._status_sort_key("Pending", 0)
        return spec.display_name.casefold()

    def _component_status_sort_key(self, screen_index: int, column: int, status: Any) -> Any:
        component_column = OPTIONAL_TABLE_COLUMNS["component"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["component"]
        installed_column = OPTIONAL_TABLE_COLUMNS["installed"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["installed"]
        available_column = OPTIONAL_TABLE_COLUMNS["available"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["available"]
        downloaded_column = OPTIONAL_TABLE_COLUMNS["downloaded"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["downloaded"]
        size_column = OPTIONAL_TABLE_COLUMNS["size"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["size"]
        status_column = OPTIONAL_TABLE_COLUMNS["status"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["status"]
        if column == component_column:
            return status.spec.display_name.casefold()
        if column == installed_column:
            return self._version_sort_key(status.installed_version)
        if column == available_column:
            return self._version_sort_key(status.available_version)
        if column == downloaded_column:
            return self._version_sort_key(self._component_downloaded_version(status.spec))
        if column == size_column:
            return self._size_sort_key(
                self._component_size_bytes(status.spec),
                self._component_size_display(status.spec),
            )
        if column == status_column:
            _, percent = self._status_state.get(status.spec.key, (status.status, 0))
            return self._status_sort_key(status.status, percent)
        return status.spec.display_name.casefold()

    def _sort_queue_entries(self) -> None:
        sort_queue_entries(self)

    def _queue_entry_sort_key(self, column: int, entry: QueueEntry) -> Any:
        return queue_entry_sort_key(self, column, entry)

    def _version_sort_key(self, value: str | None) -> tuple[int, tuple[int, int, int], str]:
        if not value:
            return (1, (0, 0, 0), "")
        normalized = value.strip().lower()
        cleaned = normalized[1:] if normalized.startswith("v") else normalized
        main_part, beta_separator, beta_part = cleaned.partition("b")
        numbers: list[int] = []
        for token in main_part.split("."):
            if token.isdigit():
                numbers.append(int(token))
            else:
                return (0, (0, 0, 0), normalized)
        while len(numbers) < 2:
            numbers.append(0)
        beta_value = int(beta_part) if beta_separator and beta_part.isdigit() else 999999
        return (0, (numbers[0], numbers[1], beta_value), normalized)

    def _size_sort_key(self, size_bytes: int | None, label: str) -> tuple[int, int, str]:
        if size_bytes is None:
            return (1, 0, label.casefold())
        return (0, size_bytes, label.casefold())

    def _sort_by_size(self, values: list[Any], key_fn, descending: bool) -> list[Any]:
        known = [value for value in values if key_fn(value) is not None]
        unknown = [value for value in values if key_fn(value) is None]
        known.sort(key=lambda value: key_fn(value), reverse=descending)
        return [*known, *unknown]

    def _status_sort_key(self, status: str, percent: float) -> tuple[int, float, str]:
        order = {
            "Pending": 0,
            "Queued": 1,
            "Missing": 2,
            "Update Available": 3,
            "Downloading": 4,
            "Downloaded": 5,
            "Preparing": 6,
            "Backing Up": 7,
            "Installing": 8,
            "Installed": 9,
            "Skipped": 10,
            "Failed": 11,
        }
        return (order.get(status, 99), percent, status.casefold())

    def _set_checkbox_widget(self, table: QTableWidget, row: int, component_key: str, screen_index: int) -> None:
        checkbox = QCheckBox()
        checkbox.setObjectName("rowSelector")
        disabled_keys = self._disabled_component_keys.get(screen_index, set())
        disabled = component_key in disabled_keys
        checkbox.toggled.connect(
            lambda checked, key=component_key, screen=screen_index: self._handle_component_checkbox_toggled(
                screen,
                key,
                checked,
            )
        )

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(checkbox)
        layout.addStretch(1)
        checkbox.setChecked(not disabled and component_key in self._selected_component_keys.get(screen_index, set()))
        checkbox.setEnabled(not disabled)
        table.setCellWidget(row, 0, container)

    def _set_action_buttons_widget(self, table: QTableWidget, row: int, spec: ComponentSpec, screen_index: int) -> None:
        action_column = OPTIONAL_TABLE_COLUMNS["actions"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["actions"]
        container = QWidget()
        container.setProperty("componentKey", spec.key)
        container.setProperty("screenIndex", screen_index)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(6)
        download_button = QPushButton("Download")
        download_button.setObjectName("downloaderDownloadButton")
        download_button.setMinimumWidth(96)
        install_button = QPushButton("Install")
        install_button.setObjectName("downloaderInstallButton")
        install_button.setMinimumWidth(76)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("downloaderCancelButton")
        cancel_button.setMinimumWidth(76)
        layout.addWidget(download_button)
        layout.addWidget(install_button)
        layout.addWidget(cancel_button)
        table.setCellWidget(row, action_column, container)
        self._configure_action_buttons_widget(container, spec, screen_index)

    def _configure_action_buttons_widget(self, container: QWidget, spec: ComponentSpec, screen_index: int) -> None:
        download_button = container.findChild(QPushButton, "downloaderDownloadButton")
        install_button = container.findChild(QPushButton, "downloaderInstallButton")
        cancel_button = container.findChild(QPushButton, "downloaderCancelButton")
        if download_button is None or install_button is None or cancel_button is None:
            return
        try:
            download_button.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            install_button.clicked.disconnect()
        except RuntimeError:
            pass
        try:
            cancel_button.clicked.disconnect()
        except RuntimeError:
            pass

        queue_entry = next((entry for entry in self._queue_entries if entry.spec.key == spec.key), None)
        queue_status = queue_entry.status if queue_entry is not None else self._status_state.get(spec.key, ("", 0))[0]
        is_active_paused = queue_status == "Paused" or (
            self._controller is not None and self._controller.is_component_paused(spec.key)
        )
        is_downloading = queue_status in {"Downloading", "Preparing", "Backing Up", "Installing"} and queue_entry is not None
        is_queued = queue_entry is not None

        if is_active_paused:
            download_button.setText("Resume")
            download_button.setEnabled(True)
            download_button.clicked.connect(lambda _checked=False, _component_key=spec.key: self._resume_component(_component_key))
        elif is_downloading:
            download_button.setText("Pause")
            download_button.setEnabled(True)
            download_button.clicked.connect(lambda _checked=False, _component_key=spec.key: self._pause_component(_component_key))
        else:
            download_button.setText("Download")
            download_button.setEnabled(not is_queued)
            download_button.clicked.connect(
                lambda _checked=False, _screen_index=screen_index, _component_key=spec.key: self._download_component_for_screen(
                    _screen_index,
                    _component_key,
                )
            )

        install_button.setVisible(self._component_downloaded_version(spec) is not None)
        install_button.setEnabled(self._component_downloaded_version(spec) is not None and not is_queued)
        install_button.clicked.connect(
            lambda _checked=False, _spec_name=spec.display_name: self._install_downloaded_component_stub(_spec_name)
        )

        cancel_button.setVisible(is_queued)
        cancel_button.setEnabled(is_queued)
        cancel_button.clicked.connect(lambda _checked=False, _component_key=spec.key: self._remove_queue_entry(_component_key))

    def _refresh_downloader_action_buttons(self) -> None:
        for screen_index in (
            BASE_COMPONENTS_SCREEN,
            GAME_PACKS_SCREEN,
            BITLCD_MARQUEES_SCREEN,
            OPTIONAL_COMPONENTS_SCREEN,
        ):
            table = self._table_for_screen(screen_index)
            action_column = OPTIONAL_TABLE_COLUMNS["actions"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["actions"]
            for row in range(table.rowCount()):
                container = table.cellWidget(row, action_column)
                if not isinstance(container, QWidget):
                    continue
                component_key = str(container.property("componentKey") or "")
                spec = self._all_components_by_key.get(component_key)
                if spec is None:
                    continue
                self._configure_action_buttons_widget(container, spec, screen_index)

    def _screen_for_table(self, table: QTableWidget) -> int:
        if table is self.bitlcd_table:
            return BITLCD_MARQUEES_SCREEN
        if table is self.optional_components_table:
            return OPTIONAL_COMPONENTS_SCREEN
        if table is self.game_packs_table:
            return GAME_PACKS_SCREEN
        return BASE_COMPONENTS_SCREEN

    def _handle_component_checkbox_toggled(self, screen_index: int, component_key: str, selected: bool) -> None:
        if self._selection_sync:
            return
        selected_keys = self._selected_component_keys.setdefault(screen_index, set())
        if selected:
            selected_keys.add(component_key)
        else:
            selected_keys.discard(component_key)
        self._sync_header_checkbox(screen_index)

    def _toggle_all_component_rows(self, screen_index: int, checked: bool) -> None:
        selected_keys = self._selected_component_keys.setdefault(screen_index, set())
        disabled_keys = self._disabled_component_keys.get(screen_index, set())
        if checked:
            selectable_keys = {spec.key for spec in self._components_for_screen(screen_index) if spec.key not in disabled_keys}
            selected_keys.update(selectable_keys)
        else:
            selected_keys.clear()
        self._refresh_screen_table(screen_index)
        self._sync_header_checkbox(screen_index)

    def _sync_header_checkbox(self, screen_index: int) -> None:
        return

    def _refresh_queue_table(self) -> None:
        refresh_queue_table(self)
        self._refresh_downloader_action_buttons()

    def _queue_entry_for_key(self, component_key: str) -> QueueEntry | None:
        return next((entry for entry in self._queue_entries if entry.spec.key == component_key), None)

    def _transferable_queue_entries(self) -> list[QueueEntry]:
        return [entry for entry in self._queue_entries if entry.status not in {"Installed", "Paused"}]

    def _update_queue_buttons(self) -> None:
        update_queue_buttons(self)

    def _set_queue_actions_widget(self, row: int, entry: QueueEntry) -> None:
        set_queue_actions_widget(self, row, entry)

    def _set_queue_controls_enabled(self, enabled: bool) -> None:
        set_queue_controls_enabled(self, enabled)

    def _move_queue_entry(self, component_key: str, offset: int) -> None:
        move_queue_entry(self, component_key, offset)

    def _remove_queue_entry(self, component_key: str) -> None:
        remove_queue_entry(self, component_key)

    def _clear_queue(self) -> None:
        clear_queue(self)

    def _update_queue_status(self, component_key: str, status: str, percent: float) -> None:
        update_queue_status(self, component_key, status, percent)
        self._refresh_downloader_action_buttons()

    def _set_status_widget(self, component_key: str, status: str, percent: float) -> None:
        self._status_state[component_key] = (status, percent)
        widget = self._status_widgets.get(component_key)
        if widget is not None and isValid(widget):
            widget.set_status(self._display_component_status(component_key, status), percent)

    def _display_component_status(self, component_key: str, status: str) -> str:
        display_status = {
            "Installed": "Up-to-Date",
            "Missing": "Not Installed",
        }.get(status, status)
        if (
            self._controller is not None
            and self._controller.is_component_paused(component_key)
            and component_key in self._active_components
        ):
            return f"{display_status} (Paused)"
        return display_status

    def _refresh_active_status_widgets(self) -> None:
        for component_key, (status, percent) in list(self._status_state.items()):
            widget = self._status_widgets.get(component_key)
            if widget is not None and isValid(widget):
                widget.set_status(self._display_component_status(component_key, status), percent)
        for entry in self._queue_entries:
            widget = self._queue_status_widgets.get(entry.spec.key)
            if widget is not None and isValid(widget):
                widget.set_status(self._display_component_status(entry.spec.key, entry.status), entry.percent)

    def _rebuild_component_registry(self) -> None:
        self._all_components_by_key = {
            spec.key: spec
            for spec in (*self._required_specs, *self._game_pack_specs, *self._bitlcd_specs, *self._optional_specs)
        }
        self._default_source_label_by_key = (
            {spec.key: "Base Component" for spec in self._required_specs}
            | {spec.key: "System Pack" for spec in self._game_pack_specs}
            | {spec.key: "BitLCD Marquee" for spec in self._bitlcd_specs}
            | {spec.key: "Optional Component" for spec in self._optional_specs}
        )

    def _set_dynamic_specs(
        self,
        *,
        screen_index: int,
        specs: tuple[ComponentSpec, ...],
        installer: Installer,
        source_labels: tuple[str, ...],
    ) -> None:
        current_specs = self._components_for_screen(screen_index)
        old_keys = {spec.key for spec in current_specs}
        new_keys = {spec.key for spec in specs}
        if screen_index == BASE_COMPONENTS_SCREEN:
            self._required_specs = specs
        elif screen_index == GAME_PACKS_SCREEN:
            self._game_pack_specs = specs
        elif screen_index == BITLCD_MARQUEES_SCREEN:
            self._bitlcd_specs = specs
        elif screen_index == OPTIONAL_COMPONENTS_SCREEN:
            self._optional_specs = specs
        installer.components = specs
        self._initialize_status_cells(specs)
        self._selected_component_keys.setdefault(screen_index, set()).intersection_update(new_keys)
        self._disabled_component_keys.setdefault(screen_index, set()).intersection_update(new_keys)
        for key in old_keys | new_keys:
            self._remote_size_overrides.pop(key, None)
            self._cached_download_versions.pop(key, None)
        self._rebuild_component_registry()
        for entry in self._queue_entries:
            if entry.source_label not in source_labels:
                continue
            latest_spec = self._all_components_by_key.get(entry.spec.key)
            if latest_spec is not None:
                entry.spec = latest_spec

    def _refresh_required_component_catalog(self, force_refresh: bool = False) -> None:
        specs = self.required_component_catalog.specs(force_refresh=force_refresh)
        if specs != self._required_specs:
            self._set_dynamic_specs(
                screen_index=BASE_COMPONENTS_SCREEN,
                specs=specs,
                installer=self.base_installer,
                source_labels=("Base Component",),
            )

    def _refresh_system_pack_catalog(self, force_refresh: bool = False) -> None:
        specs = self.system_pack_catalog.specs(force_refresh=force_refresh)
        if specs != self._game_pack_specs:
            self._set_dynamic_specs(
                screen_index=GAME_PACKS_SCREEN,
                specs=specs,
                installer=self.game_packs_installer,
                source_labels=("System Pack", "Game Pack"),
            )

    def _refresh_bitlcd_catalog(self, force_refresh: bool = False) -> None:
        specs = self.bitlcd_catalog.specs(force_refresh=force_refresh)
        if specs != self._bitlcd_specs:
            self._set_dynamic_specs(
                screen_index=BITLCD_MARQUEES_SCREEN,
                specs=specs,
                installer=self.bitlcd_installer,
                source_labels=("BitLCD Marquee",),
            )

    def _refresh_optional_component_catalog(self, force_refresh: bool = False) -> None:
        specs = self.optional_component_catalog.specs(force_refresh=force_refresh)
        if specs != self._optional_specs:
            self._set_dynamic_specs(
                screen_index=OPTIONAL_COMPONENTS_SCREEN,
                specs=specs,
                installer=self.optional_components_installer,
                source_labels=("Optional Component",),
            )

    def _components_for_screen(self, screen_index: int) -> tuple[ComponentSpec, ...]:
        if screen_index == BASE_COMPONENTS_SCREEN:
            return self._required_specs
        if screen_index == GAME_PACKS_SCREEN:
            return self._game_pack_specs
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self._bitlcd_specs
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return self._optional_specs
        return ()

    def _installer_for_screen(self, screen_index: int) -> Installer:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_installer
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return self.optional_components_installer
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_installer
        return self.base_installer

    def _table_for_screen(self, screen_index: int) -> QTableWidget:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_table
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return self.optional_components_table
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_table
        return self.table

    def _install_button_for_screen(self, screen_index: int) -> QPushButton:
        return self.downloader_refresh_button

    def _refresh_button_for_screen(self, screen_index: int) -> QPushButton:
        return self.downloader_refresh_button

    def _log_output_for_screen(self, screen_index: int) -> QPlainTextEdit:
        return self.queue_log_output

    def _screen_label(self, screen_index: int) -> str:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return "BitLCD marquees"
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return "Optional components"
        if screen_index == GAME_PACKS_SCREEN:
            return "System packs"
        if screen_index == DOWNLOADER_SCREEN:
            return "Downloader"
        if screen_index == QUEUE_SCREEN:
            return "Downloader"
        return "Required components"

    def _start_install_for_screen(self, screen_index: int) -> None:
        target = self._target_dir_for_screen(screen_index)
        if target is None:
            message = (
                "Choose a BitLCD target folder in Settings before installing."
                if screen_index == BITLCD_MARQUEES_SCREEN
                else "Choose a target folder in Settings before installing."
            )
            QMessageBox.warning(self, "Missing target", message)
            self._change_screen(SETTINGS_SCREEN)
            return

        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password in Settings before downloading.",
            )
            self._change_screen(SETTINGS_SCREEN)
            return

        selected_keys = set(self._selected_component_keys.get(screen_index, set()))
        if not selected_keys:
            QMessageBox.information(
                self,
                "Nothing selected",
                "Select one or more missing or outdated rows to add them to the queue.",
            )
            return
        queued = self._enqueue_selected_for_screen(screen_index, target)
        if queued == 0:
            return
        self._change_screen(DOWNLOADER_SCREEN)
        if self._controller is None:
            self._start_queue_install()

    def _download_component_for_screen(self, screen_index: int, component_key: str) -> None:
        target = self._target_dir_for_screen(screen_index)
        if target is None:
            message = (
                "Choose a BitLCD target folder in Settings before downloading."
                if screen_index == BITLCD_MARQUEES_SCREEN
                else "Choose a target folder in Settings before downloading."
            )
            QMessageBox.warning(self, "Missing target", message)
            self._change_screen(SETTINGS_SCREEN)
            return

        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password in Settings before downloading.",
            )
            self._change_screen(SETTINGS_SCREEN)
            return

        spec = self._all_components_by_key.get(component_key)
        if spec is None:
            return
        downloaded_version = self._component_downloaded_version(spec)
        if downloaded_version is not None and self._version_sort_key(downloaded_version) >= self._version_sort_key(spec.available_version):
            overwrite = QMessageBox.question(
                self,
                "Overwrite downloaded archive",
                f"{spec.display_name} {downloaded_version} is already in the downloads folder. Download it again and overwrite the existing archive?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
            self._remove_cached_download_for_spec(spec, screen_index)

        installer = self._installer_for_screen(screen_index)
        statuses = installer.scan_target(target)
        matching_status = next((status for status in statuses if status.spec.key == component_key), None)
        if matching_status is None:
            return
        download_only = matching_status.status == "Installed" or not self.auto_install_after_download_checkbox.isChecked()

        queued = self._enqueue_component_for_screen(screen_index, component_key, target, matching_status, download_only)
        if queued == 0:
            return
        self._change_screen(DOWNLOADER_SCREEN)
        if self._controller is None:
            self._start_queue_auto(preferred_component_key=component_key)

    def _install_downloaded_component_stub(self, component_name: str) -> None:
        QMessageBox.information(
            self,
            "Install not implemented",
            f"Installing downloaded archives directly is not implemented yet for {component_name}.",
        )

    def _enqueue_component_for_screen(
        self,
        screen_index: int,
        component_key: str,
        target: Path,
        matching_status: ComponentStatus | None = None,
        download_only: bool = False,
    ) -> int:
        installer = self._installer_for_screen(screen_index)
        statuses = [matching_status] if matching_status is not None else installer.scan_target(target)
        if screen_index == GAME_PACKS_SCREEN:
            source_label = "System Pack"
        elif screen_index == BITLCD_MARQUEES_SCREEN:
            source_label = "BitLCD Marquee"
        elif screen_index == OPTIONAL_COMPONENTS_SCREEN:
            source_label = "Optional Component"
        else:
            source_label = "Base Component"
        queued_keys = {entry.spec.key for entry in self._queue_entries}
        for status in statuses:
            if status.spec.key != component_key or status.spec.key in queued_keys:
                continue
            self._queue_entries.append(
                QueueEntry(
                    spec=status.spec,
                    source_label=source_label,
                    target_path=str(target),
                    allow_installed=status.status == "Installed",
                    download_only=download_only,
                )
            )
            self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
            self._set_status_widget(status.spec.key, "Queued", 0.0)
            self._refresh_queue_table()
            self._save_settings()
            self._push_status_message(f"Queued {source_label.lower()} download.")
            return 1
        return 0

    def _remove_cached_download_for_spec(self, spec: ComponentSpec, screen_index: int) -> None:
        installer = self._installer_for_screen(screen_index)
        installer.cache_dir = self._downloads_dir()
        cached_archive = installer.cached_archive_path(spec)
        if cached_archive is not None:
            try:
                cached_archive.unlink(missing_ok=True)
            except OSError:
                pass
        partial_archive = (self._downloads_dir() / spec.cache_name).with_suffix(Path(spec.cache_name).suffix + ".part")
        try:
            partial_archive.unlink(missing_ok=True)
        except OSError:
            pass
        self._cached_download_versions.pop(spec.key, None)

    def _enqueue_selected_for_screen(self, screen_index: int, target: Path) -> int:
        installer = self._installer_for_screen(screen_index)
        statuses = installer.scan_target(target)
        selected_keys = self._selected_component_keys.get(screen_index, set())
        disabled_keys = self._disabled_component_keys.get(screen_index, set())
        added = 0
        if screen_index == GAME_PACKS_SCREEN:
            source_label = "System Pack"
        elif screen_index == BITLCD_MARQUEES_SCREEN:
            source_label = "BitLCD Marquee"
        elif screen_index == OPTIONAL_COMPONENTS_SCREEN:
            source_label = "Optional Component"
        else:
            source_label = "Base Component"
        queued_keys = {entry.spec.key for entry in self._queue_entries}
        for status in statuses:
            if status.spec.key not in selected_keys or status.spec.key in disabled_keys or status.status == "Installed" or status.spec.key in queued_keys:
                continue
            self._queue_entries.append(
                QueueEntry(spec=status.spec, source_label=source_label, target_path=str(target))
            )
            self._set_status_widget(status.spec.key, "Queued", 0.0)
            queued_keys.add(status.spec.key)
            added += 1
        if added:
            self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
            self._refresh_queue_table()
            self._save_settings()
            self._push_status_message(f"Queued {added} {source_label.lower()} item(s).")
        return added

    def _start_queue_install(self) -> None:
        self._start_queue_transfer(download_only=False)

    def _start_queue_download_only(self) -> None:
        self._start_queue_transfer(download_only=True)

    def _start_queue_auto(self, preferred_component_key: str | None = None) -> None:
        pending_entries = self._transferable_queue_entries()
        if not pending_entries:
            self._start_queue_install()
            return
        batch_entries = self._next_queue_batch_entries(pending_entries, preferred_component_key=preferred_component_key)
        self._start_queue_transfer(batch_entries=batch_entries)

    def _start_queue_transfer(self, *, batch_entries: list[QueueEntry] | None = None) -> None:
        pending_entries = self._transferable_queue_entries()
        if not pending_entries:
            QMessageBox.information(self, "Queue empty", "Add one or more components to the queue first.")
            self._save_settings()
            return
        batch_entries = batch_entries or self._next_queue_batch_entries(pending_entries)
        if not batch_entries:
            QMessageBox.information(self, "Queue empty", "Add one or more components to the queue first.")
            self._save_settings()
            return
        download_only = all(entry.download_only for entry in batch_entries)
        if not batch_entries[0].target_path.strip():
            QMessageBox.warning(self, "Missing target", "Choose a target folder in Settings before installing.")
            self._change_screen(SETTINGS_SCREEN)
            return
        target = Path(batch_entries[0].target_path).expanduser()
        queue_specs = tuple(entry.spec for entry in batch_entries)
        force_component_keys = {entry.spec.key for entry in batch_entries if entry.allow_installed}
        installer = Installer(
            queue_specs,
            max_parallel_downloads=self.parallel_downloads_spin.value(),
            downloader=self._shared_downloader,
        )
        installer.cache_dir = self._downloads_dir()
        cache_files = list_cached_archive_files(installer.cache_dir)
        cached_specs = [
            spec for spec in queue_specs if installer.cached_archive_path(spec, files=cache_files) is not None
        ]
        credentials = self._archive_credentials()
        if credentials is None and len(cached_specs) != len(queue_specs):
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password in Settings before downloading.",
            )
            self._change_screen(SETTINGS_SCREEN)
            return

        self._save_settings()
        log_output = self._log_output_for_screen(QUEUE_SCREEN)
        self._controller = OperationController()
        self._active_operation_screen = DOWNLOADER_SCREEN
        self._active_components.clear()
        self._set_action_buttons_enabled(False)
        self._set_queue_controls_enabled(False)
        self.queue_pause_button.setText("Pause")
        self._push_status_message("Preparing downloads..." if download_only else "Preparing install...")
        log_output.appendPlainText(f"Target: {target}")
        log_output.appendPlainText(f"Queue batch: {len(batch_entries)} item(s)")
        if cached_specs:
            log_output.appendPlainText(f"Using cached archive(s) for {len(cached_specs)} queued item(s).")

        worker = InstallWorker(
            installer,
            target,
            credentials,
            self._controller,
            download_only=download_only,
            force_component_keys=force_component_keys,
        )
        worker.log.connect(log_output.appendPlainText)
        worker.component_status.connect(self._update_component_status)
        worker.progress.connect(self._update_progress)
        worker.cancelled.connect(self._install_cancelled)
        worker.error.connect(self._install_failed)
        worker.finished.connect(self._install_finished)
        self._install_handle.start(
            worker,
            finish_signals=(worker.finished, worker.cancelled, worker.error),
            on_cleared=self._finalize_close_if_ready,
        )

    @staticmethod
    def _next_queue_batch_entries(
        pending_entries: list[QueueEntry],
        preferred_component_key: str | None = None,
    ) -> list[QueueEntry]:
        if not pending_entries:
            return []
        if preferred_component_key is not None:
            preferred_entry = next((entry for entry in pending_entries if entry.spec.key == preferred_component_key), None)
            if preferred_entry is not None:
                return [preferred_entry]
        target_path = pending_entries[0].target_path
        download_only = pending_entries[0].download_only
        return [entry for entry in pending_entries if entry.target_path == target_path and entry.download_only == download_only]

    def _toggle_pause(self) -> None:
        active_keys = set(self._active_components)
        paused_entries = [entry for entry in self._queue_entries if entry.status == "Paused"]
        if active_keys and self._controller is not None:
            self._controller.pause_components(active_keys)
            for entry in self._queue_entries:
                if entry.spec.key in active_keys:
                    entry.status = "Paused"
                    self._set_status_widget(entry.spec.key, "Paused", entry.percent)
            self._push_status_message("Pausing active transfers...")
            self._refresh_active_status_widgets()
            self._refresh_queue_table()
            self._save_settings()
            return
        if paused_entries:
            if self._controller is not None:
                self._controller.resume_all()
            for entry in paused_entries:
                entry.status = "Queued"
                entry.percent = 0.0
                self._set_status_widget(entry.spec.key, "Queued", 0.0)
            self._push_status_message("Resuming paused transfers...")
            self._refresh_queue_table()
            self._save_settings()
            if self._controller is None:
                self._start_queue_auto()
            return
        if self._queue_entries:
            self._start_queue_auto()

    def _pause_component(self, component_key: str) -> None:
        if self._controller is None:
            return
        self._controller.pause_component(component_key)
        for entry in self._queue_entries:
            if entry.spec.key == component_key:
                entry.status = "Paused"
                self._set_status_widget(component_key, "Paused", entry.percent)
                break
        self._push_status_message("Pausing transfer...")
        self._refresh_active_status_widgets()
        self._refresh_queue_table()
        self._save_settings()

    def _resume_component(self, component_key: str) -> None:
        if self._controller is not None:
            self._controller.resume_component(component_key)
        for entry in self._queue_entries:
            if entry.spec.key == component_key:
                entry.status = "Queued"
                entry.percent = 0.0
                self._set_status_widget(component_key, "Queued", 0.0)
                break
        self._push_status_message("Resuming transfer...")
        self._refresh_queue_table()
        self._save_settings()
        if self._controller is None:
            self._start_queue_auto(preferred_component_key=component_key)

    def _cancel_install(self) -> None:
        if self._controller is None:
            return
        self._push_status_message("Cancelling...")
        self._controller.cancel()

    def _update_component_status(self, component_key: str, status: str) -> None:
        if status in {"Downloading", "Preparing", "Backing Up", "Installing"}:
            self._active_components.add(component_key)
        else:
            self._active_components.discard(component_key)
        _, current_percent = self._status_state.get(component_key, (status, 0))
        self._set_status_widget(component_key, status, current_percent)
        queue_widget = self._queue_status_widgets.get(component_key)
        self._update_queue_status(component_key, status, queue_widget.percent() if queue_widget is not None else 0)
        spec = self._all_components_by_key.get(component_key)
        if spec is not None:
            self._push_status_message(f"{spec.display_name}: {status}")

    def _update_progress(self, progress: InstallProgress) -> None:
        if progress.phase == "queued":
            return
        status_text = {
            "download": "Downloading",
            "download_complete": "Downloaded",
            "prepare": "Preparing",
            "backup": "Backing Up",
            "extract": "Installing",
            "installed": "Installed",
        }.get(progress.phase, "Working")
        self._set_status_widget(progress.component_key, status_text, progress.component_percent)
        self._update_queue_status(progress.component_key, status_text, progress.component_percent)

    def _install_finished(self, report: object) -> None:
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        installed_components = getattr(report, "installed_components", [])
        downloaded_components = getattr(report, "downloaded_components", [])
        continue_queue = (
            not (downloaded_components and not installed_components)
            and
            self._active_operation_screen == DOWNLOADER_SCREEN
            and bool(self._transferable_queue_entries())
        )
        self._finish_install_ui()
        self._push_status_message("Downloads complete" if downloaded_components and not installed_components else "Install complete")
        cleanup_result = self._enforce_download_cache_policy()
        self._refresh_all_tables()
        self._refresh_queue_table()

        backup_dir = getattr(report, "backup_dir", None)
        if backup_dir:
            log_output.appendPlainText(f"Backup directory: {backup_dir}")
        if cleanup_result.deleted_files:
            log_output.appendPlainText(
                f"Downloads cleanup removed {cleanup_result.deleted_files} file(s) from {self._downloads_dir()}."
            )

        if continue_queue and not self._closing:
            self._save_settings()
            self._start_queue_auto()
            return

        self._save_settings()
        self._finalize_close_if_ready()

    def _install_cancelled(self, message: str) -> None:
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        self._finish_install_ui()
        self._push_status_message("Install cancelled")
        log_output.appendPlainText(message)
        self._refresh_queue_table()
        self._save_settings()
        self._finalize_close_if_ready()

    def _install_failed(self, message: str) -> None:
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        self._finish_install_ui()
        self._push_status_message("Install failed")
        log_output.appendPlainText(f"ERROR: {message}")
        self._refresh_queue_table()
        if not self._closing:
            QMessageBox.critical(self, "Install failed", message)
        self._save_settings()
        self._finalize_close_if_ready()

    def _finish_install_ui(self) -> None:
        self._active_components.clear()
        self._set_action_buttons_enabled(True)
        self._controller = None
        self._active_operation_screen = None
        self._set_queue_controls_enabled(True)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self.validate_button.setEnabled(enabled)
        self.clear_downloads_button.setEnabled(enabled)

    def _set_transfer_controls_enabled(self, enabled: bool) -> None:
        return

    def _update_progress_controls_visibility(self) -> None:
        return

    def _push_status_message(self, message: str, minimum_ms: int = 1000) -> None:
        message = message.strip()
        if not message:
            return
        if message == self._current_status_message:
            return
        if self._status_message_queue and self._status_message_queue[-1][0] == message:
            return
        self._status_message_queue.append((message, minimum_ms))
        if self._current_status_message is None and not self._status_message_timer.isActive():
            self._show_next_status_message()

    def _show_next_status_message(self) -> None:
        if not self._status_message_queue:
            self._current_status_message = None
            return
        message, minimum_ms = self._status_message_queue.popleft()
        self._current_status_message = message
        self.statusBar().showMessage(message)
        self._status_message_timer.start(max(1000, minimum_ms))

    def _validate_credentials_success(self, user: str) -> None:
        self._set_action_buttons_enabled(True)
        self._set_queue_controls_enabled(True)
        self._refresh_all_tables()
        self._push_status_message(f"Archive.org credentials validated for {user}")
        if not self._closing:
            QMessageBox.information(self, "Validation successful", f"Archive.org login succeeded for {user}.")
        self._finalize_close_if_ready()

    def _validate_credentials_error(self, message: str) -> None:
        self._set_action_buttons_enabled(True)
        self._set_queue_controls_enabled(True)
        self._refresh_all_tables()
        self._push_status_message("Archive.org credential validation failed")
        if not self._closing:
            QMessageBox.critical(self, "Validation failed", message)
        self._finalize_close_if_ready()

    def _start_release_check(self) -> None:
        if self._release_check_handle.running:
            return

        worker = ReleaseCheckWorker(APP_VERSION)
        worker.finished.connect(self._release_check_finished)
        worker.error.connect(self._release_check_failed)
        self._release_check_handle.start(
            worker,
            finish_signals=(worker.finished, worker.error),
            on_cleared=self._finalize_close_if_ready,
        )

    def _release_check_finished(self, _latest_tag: str, is_newer: bool) -> None:
        if is_newer:
            self.sidebar_version_note.setText(
                f'A newer version is <a href="{RELEASES_PAGE_URL}">available</a>'
            )
        else:
            self.sidebar_version_note.setText("You are on the current version")
        self.sidebar_version_note.show()
        self._finalize_close_if_ready()

    def _release_check_failed(self, _message: str) -> None:
        self.sidebar_version_note.hide()
        self._finalize_close_if_ready()

    @property
    def _base_game_entries(self) -> tuple[GameManifestEntry, ...]:
        return load_game_manifest()

    @property
    def _game_entries(self) -> tuple[GameManifestEntry, ...]:
        if self._game_entries_override is not None:
            return self._game_entries_override
        return load_game_manifest()

    @_game_entries.setter
    def _game_entries(self, value: tuple[GameManifestEntry, ...]) -> None:
        self._game_entries_override = value

    @property
    def _collection_options(self) -> tuple[str, ...]:
        if self._collection_options_override is not None:
            return self._collection_options_override
        return available_collections()

    @_collection_options.setter
    def _collection_options(self, value: tuple[str, ...]) -> None:
        self._collection_options_override = value

    def _target_dir(self) -> Path | None:
        raw = self.target_edit.text().strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    def _autostart_state(self):
        return detect_autostart_state(self._target_dir())

    def _bitlcd_target_dir(self) -> Path | None:
        raw = self.bitlcd_target_edit.text().strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    def _refresh_tweaks_screen(self) -> None:
        if TWEAKS_SCREEN in self._pending_screen_builders:
            return
        refresh_tweaks_screen(self)

    def _handle_autostart_primary_action(self) -> None:
        handle_autostart_primary_action(self)

    def _handle_install_autostart_fix(self) -> None:
        handle_install_autostart_fix(self)

    def _handle_legends_micro_fix_toggled(self, state: int) -> None:
        handle_legends_micro_fix_toggled(self, state)

    def _handle_default_theme_changed(self, index: int) -> None:
        handle_default_theme_changed(self, index)

    def _handle_remember_menu_toggled(self, state: int) -> None:
        handle_remember_menu_toggled(self, state)

    def _handle_write_launcher_log_toggled(self, state: int) -> None:
        handle_write_launcher_log_toggled(self, state)

    def _handle_video_enable_toggled(self, state: int) -> None:
        handle_video_enable_toggled(self, state)

    def _handle_video_loop_changed(self) -> None:
        handle_video_loop_changed(self)

    def _handle_auto_scan_collections_toggled(self, state: int) -> None:
        handle_auto_scan_collections_toggled(self, state)

    def _handle_attract_mode_time_changed(self) -> None:
        handle_attract_mode_time_changed(self)

    def _handle_attract_mode_next_time_changed(self) -> None:
        handle_attract_mode_next_time_changed(self)

    def _handle_default_video_value_changed(self, value: int) -> None:
        handle_default_video_value_changed(self, value)

    def _downloads_dir(self) -> Path:
        raw = self.downloads_path_edit.text().strip()
        if not raw:
            return default_downloads_dir()
        return Path(raw).expanduser()

    def _target_dir_for_screen(self, screen_index: int) -> Path | None:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self._bitlcd_target_dir()
        return self._target_dir()

    def _archive_credentials(self) -> ArchiveOrgCredentials | None:
        email = self.archive_email_edit.text().strip()
        password = self.archive_password_edit.text()
        if not email or not password:
            return None
        return ArchiveOrgCredentials(email=email, password=password)

    def _refresh_remote_sizes_for_screen(self, screen_index: int) -> None:
        if screen_index not in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            return
        if screen_index == GAME_PACKS_SCREEN:
            return
        if self._remote_sizes_handle.running:
            return
        self._start_remote_sizes_refresh()

    def _component_size_display(self, spec: ComponentSpec) -> str:
        override = self._remote_size_overrides.get(spec.key)
        if override is None:
            return spec.size_display
        label, _ = override
        return label

    def _component_downloaded_version(self, spec: ComponentSpec) -> str | None:
        return self._cached_download_versions.get(spec.key)

    def _component_downloaded_display(self, spec: ComponentSpec) -> str:
        return self._component_downloaded_version(spec) or "Not downloaded"

    def _refresh_cached_download_versions_for_screen(self, screen_index: int) -> None:
        if screen_index not in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            return
        downloads_dir = self._downloads_dir()
        files = list_cached_archive_files(downloads_dir)
        for spec in self._components_for_screen(screen_index):
            self._cached_download_versions[spec.key] = cached_download_version(downloads_dir, spec, files=files)

    def _component_type_display(self, spec: ComponentSpec) -> str:
        return spec.component_type or ""

    def _update_component_summary_labels(self) -> None:
        entries = (
            ("base_summary_label", "base_summary_warning_icon", "Review required components and install or update them."),
            ("game_packs_summary_label", "game_packs_summary_warning_icon", "Browse and update the optional system packs archive."),
            ("bitlcd_summary_label", "bitlcd_summary_warning_icon", "Browse and update BitLCD marquee packs to the BitLCD target folder."),
            ("optional_components_summary_label", "optional_components_summary_warning_icon", "Browse and update optional components that install into the OnesaUCE drive."),
        )
        credentials_missing = self._archive_credentials() is None
        warning_message = "Add Archive.org credentials in settings to enable downloads"
        for label_attr, icon_attr, default_message in entries:
            label = getattr(self, label_attr, None)
            icon_label = getattr(self, icon_attr, None)
            if label is None or icon_label is None:
                continue
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(warning_message if credentials_missing else default_message)
            icon_label.setVisible(credentials_missing)

    def _component_size_bytes(self, spec: ComponentSpec) -> int | None:
        override = self._remote_size_overrides.get(spec.key)
        if override is None:
            return spec.size_bytes
        _, size_bytes = override
        return size_bytes

    def _update_primary_action(self, screen_index: int, statuses: list) -> None:
        return

    def _serialized_queue_entries(self) -> list[dict[str, object]]:
        serialized: list[dict[str, object]] = []
        for entry in self._queue_entries:
            if entry.status == "Installed":
                continue
            serialized.append(
                {
                    "component_key": entry.spec.key,
                    "source_label": entry.source_label,
                    "target_path": entry.target_path,
                    "allow_installed": entry.allow_installed,
                    "download_only": entry.download_only,
                    "status": entry.status,
                }
            )
        return serialized

    def _load_saved_queue_entries(self, settings: AppSettings) -> None:
        loaded_entries: list[QueueEntry] = []
        seen_keys: set[str] = set()
        for raw_entry in settings.queue_entries:
            component_key = raw_entry.get("component_key", "")
            spec = self._all_components_by_key.get(component_key)
            if spec is None or component_key in seen_keys:
                continue
            seen_keys.add(component_key)
            loaded_entries.append(
                QueueEntry(
                    spec=spec,
                    source_label=raw_entry.get("source_label") or self._default_source_label_by_key.get(component_key, ""),
                    target_path=raw_entry.get("target_path", ""),
                    allow_installed=bool(raw_entry.get("allow_installed", False)),
                    download_only=bool(raw_entry.get("download_only", False)),
                    status=str(raw_entry.get("status", "Queued") or "Queued"),
                    percent=0.0,
                )
            )
        self._queue_entries = self._prune_installed_queue_entries(loaded_entries)
        self._refresh_queue_table()
        if self._queue_entries:
            self._push_status_message(f"Loaded {len(self._queue_entries)} queued item(s).")

    def _prune_installed_queue_entries(self, entries: list[QueueEntry]) -> list[QueueEntry]:
        if not entries:
            return []
        remaining: list[QueueEntry] = []
        status_cache: dict[tuple[str, str], dict[str, str]] = {}
        for entry in entries:
            if entry.allow_installed:
                remaining.append(entry)
                continue
            target_path = entry.target_path.strip()
            if not target_path:
                remaining.append(entry)
                continue
            cache_key = (entry.source_label, target_path)
            if cache_key not in status_cache:
                installer = self._installer_for_queue_entry(entry)
                statuses = installer.scan_target(Path(target_path).expanduser())
                status_cache[cache_key] = {status.spec.key: status.status for status in statuses}
            if status_cache[cache_key].get(entry.spec.key) == "Installed":
                continue
            remaining.append(entry)
        return remaining

    def _installer_for_queue_entry(self, entry: QueueEntry) -> Installer:
        if entry.source_label == "BitLCD Marquee":
            return self.bitlcd_installer
        if entry.source_label in {"Optional Component"}:
            return self.optional_components_installer
        if entry.source_label in {"System Pack", "Game Pack"}:
            return self.game_packs_installer
        return self.base_installer

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._scan_timer.stop()
        self._startup_refresh_timer.stop()
        self._themes.preview_cycle_timer.stop()
        self._themes.preview_scroll_timer.stop()
        self._themes.video_repaint_timer.stop()
        dispose_all_theme_preview_video_sessions(self)
        self._save_settings()

        if self._controller is not None:
            self._controller.cancel()
        self._downloads.cancel_active_work()

        if self._background_work_running():
            self._close_after_workers = True
            self._push_status_message("Stopping background work...")
            event.ignore()
            return

        event.accept()

    def _background_work_running(self) -> bool:
        """True while any background thread the window owns is still running."""
        handles = (
            self._install_handle,
            self._validate_handle,
            self._release_check_handle,
            self._catalog_refresh_handle,
            self._remote_sizes_handle,
            self._installed_status_handle,
            self._themes.catalog_handle,
            self._log_load_handle,
        )
        if any(handle.running for handle in handles):
            return True
        return self._downloads.has_active_work()

    def _finalize_close_if_ready(self) -> None:
        if not self._close_after_workers:
            return
        if self._background_work_running():
            return
        self._close_after_workers = False
        self.close()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_logo_pixmap()



def _filesystem_type_for_path(target: Path) -> str | None:
    if not hasattr(ctypes, "windll"):
        return None
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    anchor = resolved.anchor or target.anchor
    if not anchor:
        return None

    volume_root = str(Path(anchor))
    filesystem_name = ctypes.create_unicode_buffer(256)
    result = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(volume_root),
        None,
        0,
        None,
        None,
        None,
        filesystem_name,
        len(filesystem_name),
    )
    if result == 0:
        return None
    return filesystem_name.value or None




def _cherry_icon_pixmap(size: int = 14) -> QPixmap:
    pixmap = QPixmap(str(_assets_dir() / "Cherry.webp"))
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _strawberry_icon_pixmap(size: int = 14) -> QPixmap:
    pixmap = QPixmap(str(_assets_dir() / "Strawberry.webp"))
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _orange_icon_pixmap(size: int = 14) -> QPixmap:
    pixmap = QPixmap(str(_assets_dir() / "Orange.webp"))
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


_DOWNLOADS_ICON_BUTTON_STYLESHEET = """
QPushButton {
    border: 1px solid #5a5a5a;
    border-radius: 6px;
    background-color: transparent;
    padding: 0px;
}
QPushButton:hover:enabled {
    background-color: #2f2f2f;
    border-color: #e6d15a;
}
QPushButton:disabled {
    border-color: #4a4a4a;
    background-color: transparent;
}
"""


def _update_downloads_icon_button(button: QPushButton, tooltip: str, icon_name: str, enabled: bool) -> None:
    button.setEnabled(enabled)
    button.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setIcon(_downloads_action_icon(icon_name))


_DOWNLOADS_ACTION_ICON_CACHE: dict[str, QIcon] = {}


def _downloads_action_icon(name: str) -> QIcon:
    cached = _DOWNLOADS_ACTION_ICON_CACHE.get(name)
    if cached is not None:
        return cached
    icon = QIcon()
    enabled_path, disabled_path = _downloads_action_icon_paths(name)
    icon.addFile(str(enabled_path), mode=QIcon.Mode.Normal)
    icon.addFile(str(enabled_path), mode=QIcon.Mode.Active)
    icon.addFile(str(disabled_path), mode=QIcon.Mode.Disabled)
    _DOWNLOADS_ACTION_ICON_CACHE[name] = icon
    return icon


def _downloads_action_icon_paths(name: str) -> tuple[Path, Path]:
    assets_dir = _assets_dir()
    mapping = {
        "download": ("download_icon_white.svg", "download_icon_grey.svg"),
        "download-all": ("download-all-icon.svg", "download-all-icon-grey.svg"),
        "install": ("install_icon_white.svg", "install_icon_grey.svg"),
        "cancel": ("cancel_icon_white.svg", "cancel_icon_grey.svg"),
        "pause": ("pause-white.svg", "pause-grey.svg"),
        "resume": ("play-button-white.svg", "play-button-grey.svg"),
        "refresh": ("refresh_icon_white.svg", "refresh_icon_grey.svg"),
    }
    enabled_name, disabled_name = mapping[name]
    return assets_dir / enabled_name, assets_dir / disabled_name

