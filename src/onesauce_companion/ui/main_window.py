from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QIcon, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QHeaderView,
    QCheckBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.manifest import BITLCD_MARQUEES, GAME_PACKS, REQUIRED_COMPONENTS
from onesauce_companion.models import ComponentSpec, InstallProgress, QueueEntry
from onesauce_companion.services.archive_metadata import ArchiveMetadataService
from onesauce_companion.services.archive_org import ArchiveOrgCredentials
from onesauce_companion.services.control import OperationController
from onesauce_companion.services.download_cache import (
    clear_downloads_dir,
    default_downloads_dir,
    enforce_download_cache_policy,
)
from onesauce_companion.services.games import (
    GameManifestEntry,
    available_game_packs,
    is_excluded_game,
    load_game_manifest,
    scan_excluded_games,
    scan_installed_games,
)
from onesauce_companion.services.installer import Installer
from onesauce_companion.services.settings import AppSettings, SettingsStore
from onesauce_companion.ui.workers import InstallWorker, ValidateCredentialsWorker
from shiboken6 import isValid

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_QT_MULTIMEDIA = True
except ImportError:  # pragma: no cover - optional runtime dependency in some environments
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None
    HAS_QT_MULTIMEDIA = False


APP_VERSION = "v0.1"
SETTINGS_SCREEN = 0
BASE_COMPONENTS_SCREEN = 1
GAME_PACKS_SCREEN = 2
BITLCD_MARQUEES_SCREEN = 3
QUEUE_SCREEN = 4
GAMES_SCREEN = 5

BASE_TABLE_COLUMNS = {
    "select": 0,
    "component": 1,
    "installed": 2,
    "available": 3,
    "size": 4,
    "status": 5,
}

QUEUE_TABLE_COLUMNS = {
    "actions": 0,
    "component": 1,
    "source": 2,
    "available": 3,
    "size": 4,
    "status": 5,
}

GAMES_TABLE_COLUMNS = {
    "game_name": 0,
    "game_pack": 1,
    "status": 2,
    "actions": 3,
}

GAME_PRIMARY_ART_FOLDERS = ("artwork_3d", "artwork_front", "artwork_front_s")
GAME_DETAIL_MEDIA_FOLDERS = ("screenshot", "screentitle", "video")


class ScaledImageLabel(QLabel):
    def __init__(self, max_height: int, minimum_width: int = 220) -> None:
        super().__init__()
        self._pixmap = QPixmap()
        self._max_height = max_height
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(max_height)
        self.setMaximumHeight(max_height)
        self.setMinimumWidth(minimum_width)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_image(self, image_path: Path | None, placeholder: str) -> None:
        if image_path is None or not image_path.exists():
            self._pixmap = QPixmap()
            self.setText(placeholder)
            self.setPixmap(QPixmap())
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._pixmap = QPixmap()
            self.setText(placeholder)
            self.setPixmap(QPixmap())
            return
        self._pixmap = pixmap
        self.setText("")
        self._apply_scaled_pixmap()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        scaled = self._pixmap.scaled(
            max(1, self.width()),
            self._max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


class GameDetailsDialog(QDialog):
    def __init__(
        self,
        entry: GameManifestEntry,
        installed: bool,
        target_dir: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.installed = installed
        self.target_dir = target_dir
        self._media_player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
        self._video_widget: QVideoWidget | QLabel | None = None
        self._video_button_default_text = "Play Video"

        self.setWindowTitle(entry.game_name)
        if isinstance(parent, QWidget):
            self.resize(parent.size())
        else:
            self.resize(1280, 960)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        self.artwork_3d_label = ScaledImageLabel(180, minimum_width=220)
        self.front_art_label = ScaledImageLabel(180, minimum_width=220)
        self.back_art_label = ScaledImageLabel(180, minimum_width=220)
        self.logo_label = ScaledImageLabel(180, minimum_width=220)
        top_row.addWidget(self._build_media_group("Artwork 3D", self.artwork_3d_label), stretch=1)
        top_row.addWidget(self._build_media_group("Artwork Front", self.front_art_label), stretch=1)
        top_row.addWidget(self._build_media_group("Artwork Back", self.back_art_label), stretch=1)
        top_row.addWidget(self._build_media_group("Logo", self.logo_label), stretch=1)
        root.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        details_group = QGroupBox("Game Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(8)
        details_layout.addWidget(QLabel(f"Game Name: {entry.game_name}"))
        details_layout.addWidget(QLabel(f"Game Pack: {entry.game_pack}"))
        details_layout.addWidget(QLabel(f"Status: {'Installed' if installed else 'Not Installed'}"))
        self.media_collection_label = QLabel("Media Collection: Not resolved")
        details_layout.addWidget(self.media_collection_label)
        self.story_text = QTextEdit()
        self.story_text.setReadOnly(True)
        self.story_text.setMinimumHeight(420)
        details_layout.addWidget(self.story_text, stretch=1)
        left_layout.addWidget(details_group, stretch=1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.screenshot_label = ScaledImageLabel(180, minimum_width=220)
        self.screentitle_label = ScaledImageLabel(180, minimum_width=220)
        right_layout.addWidget(self._build_media_group("Screenshot", self.screenshot_label))
        right_layout.addWidget(self._build_media_group("Screen Title", self.screentitle_label))
        right_layout.addWidget(self._build_video_group(), stretch=1)
        right_layout.addStretch(1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([int(self.width() * 0.75), int(self.width() * 0.25)])
        root.addWidget(splitter, stretch=1)

        self._populate()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._media_player is not None:
            self._media_player.stop()
        super().closeEvent(event)

    def _build_media_group(self, title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(widget)
        return group

    def _build_video_group(self) -> QGroupBox:
        group = QGroupBox("Video")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        if HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QVideoWidget is not None and QAudioOutput is not None:
            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumHeight(220)
            self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.video_button = QPushButton(self._video_button_default_text)
            self.video_button.clicked.connect(self._toggle_video_playback)
            self.video_button.setEnabled(False)
            layout.addWidget(self._video_widget, stretch=1)
            layout.addWidget(self.video_button, alignment=Qt.AlignmentFlag.AlignRight)
        else:
            placeholder = QLabel("Video playback is not available in this build.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setMinimumHeight(220)
            self._video_widget = placeholder
            self.video_button = None
            layout.addWidget(placeholder)
        return group

    def _populate(self) -> None:
        rom_name = Path(self.entry.rom_path).name
        base_names = _game_name_candidates(rom_name)
        media_root = _resolve_game_media_root(self.target_dir, self.entry, base_names)
        if media_root is not None:
            self.media_collection_label.setText(f"Media Collection: {media_root.parent.name}")
        else:
            self.media_collection_label.setText("Media Collection: Not found")

        media_base = media_root if media_root is not None else Path()
        self.artwork_3d_label.set_image(
            _find_matching_media_file(media_base / "artwork_3d", base_names),
            "No 3D artwork found.",
        )
        self.front_art_label.set_image(
            _find_matching_media_file(media_base / "artwork_front", base_names)
            or _find_matching_media_file(media_base / "artwork_front_s", base_names),
            "No front artwork found.",
        )
        self.back_art_label.set_image(
            _find_matching_media_file(media_base / "artwork_back", base_names),
            "No back artwork found.",
        )

        logo_path = _find_matching_media_file(media_base / "logo", base_names)
        self.logo_label.set_image(logo_path, "No logo found.")

        self.screenshot_label.set_image(
            _find_matching_media_file(media_base / "screenshot", base_names),
            "No screenshot found.",
        )
        self.screentitle_label.set_image(
            _find_matching_media_file(media_base / "screentitle", base_names),
            "No screen title found.",
        )

        story_path = _find_matching_media_file(media_base / "story", base_names)
        self.story_text.setPlainText(_read_story_text(story_path))

        video_path = _find_matching_media_file(media_base / "video", base_names)
        self._load_video(video_path)

    def _load_video(self, video_path: Path | None) -> None:
        if self.video_button is None:
            if isinstance(self._video_widget, QLabel):
                if video_path is None:
                    self._video_widget.setText("No video found.")
                else:
                    self._video_widget.setText(f"Video available:\n{video_path.name}")
            return

        if video_path is None or not video_path.exists():
            if isinstance(self._video_widget, QLabel):
                self._video_widget.setText("No video found.")
            self.video_button.setEnabled(False)
            self.video_button.setText(self._video_button_default_text)
            return

        self._audio_output = QAudioOutput(self)
        self._media_player = QMediaPlayer(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self._video_widget)
        self._media_player.setSource(QUrl.fromLocalFile(str(video_path)))
        self._media_player.playbackStateChanged.connect(self._sync_video_button)
        self.video_button.setEnabled(True)
        self._video_button_default_text = f"Play Video ({video_path.name})"
        self.video_button.setText(self._video_button_default_text)

    def _toggle_video_playback(self) -> None:
        if self._media_player is None:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
        else:
            self._media_player.play()
        self._sync_video_button()

    def _sync_video_button(self, *_args) -> None:
        if self.video_button is None or self._media_player is None:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.video_button.setText("Pause Video")
        else:
            self.video_button.setText(self._video_button_default_text)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.base_installer = Installer(REQUIRED_COMPONENTS)
        self.game_packs_installer = Installer(GAME_PACKS)
        self.bitlcd_installer = Installer(BITLCD_MARQUEES)
        self.archive_metadata = ArchiveMetadataService()
        self.settings_store = SettingsStore()
        self._worker_thread: QThread | None = None
        self._worker: InstallWorker | None = None
        self._validate_thread: QThread | None = None
        self._validate_worker: ValidateCredentialsWorker | None = None
        self._controller: OperationController | None = None
        self._loading_settings = False
        self._closing = False
        self._close_after_workers = False
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(350)
        self._scan_timer.timeout.connect(self._refresh_all_tables)
        self._status_widgets: dict[str, ComponentStatusCell] = {}
        self._status_state: dict[str, tuple[str, float]] = {}
        self._remote_size_overrides: dict[str, tuple[str, int | None]] = {}
        self._active_components: set[str] = set()
        self._all_components_by_key = {spec.key: spec for spec in (*REQUIRED_COMPONENTS, *GAME_PACKS, *BITLCD_MARQUEES)}
        self._default_source_label_by_key = {
            spec.key: "Base Component" for spec in REQUIRED_COMPONENTS
        } | {
            spec.key: "Game Pack" for spec in GAME_PACKS
        } | {
            spec.key: "BitLCD Marquee" for spec in BITLCD_MARQUEES
        }
        self._selected_component_keys: dict[int, set[str]] = {
            BASE_COMPONENTS_SCREEN: set(),
            GAME_PACKS_SCREEN: set(),
            BITLCD_MARQUEES_SCREEN: set(),
        }
        self._selection_sync = False
        self._logo_pixmap = QPixmap()
        self._active_operation_screen: int | None = None
        self._queue_entries: list[QueueEntry] = []
        self._queue_status_widgets: dict[str, ComponentStatusCell] = {}
        self._game_entries = load_game_manifest()
        self._game_pack_options = available_game_packs()
        self._games_installed_target: str | None = None
        self._installed_games_cache: set[tuple[str, str]] = set()
        self._games_excluded_target: str | None = None
        self._excluded_games_cache: set[tuple[str, str]] = set()
        self._games_current_page = 1
        self._games_page_size = 100
        self._games_sort_column = GAMES_TABLE_COLUMNS["game_name"]
        self._games_sort_order = Qt.SortOrder.AscendingOrder
        self._sort_states: dict[int, tuple[int, Qt.SortOrder]] = {
            BASE_COMPONENTS_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            GAME_PACKS_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            BITLCD_MARQUEES_SCREEN: (BASE_TABLE_COLUMNS["component"], Qt.SortOrder.AscendingOrder),
            QUEUE_SCREEN: (-1, Qt.SortOrder.AscendingOrder),
        }

        self.setWindowTitle("OnesaUCE Companion")
        self.resize(1280, 1020)
        self.setMinimumSize(1000, 960)
        self._build_ui()
        self._apply_style()
        self._load_settings()
        self._connect_setting_signals()
        self._refresh_all_tables()
        self._show_initial_screen()
        QTimer.singleShot(0, self._resume_saved_queue_if_possible)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        sidebar = QWidget()
        sidebar.setObjectName("sidebarCard")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 16)
        sidebar_layout.setSpacing(12)

        self.settings_nav_button = QPushButton("Settings")
        self.settings_nav_button.setObjectName("navButton")
        self.settings_nav_button.setCheckable(True)
        self.settings_nav_button.clicked.connect(lambda: self._change_screen(SETTINGS_SCREEN))

        self.base_components_nav_button = QPushButton("Base Components")
        self.base_components_nav_button.setObjectName("navButton")
        self.base_components_nav_button.setCheckable(True)
        self.base_components_nav_button.clicked.connect(lambda: self._change_screen(BASE_COMPONENTS_SCREEN))

        self.game_packs_nav_button = QPushButton("Game Packs")
        self.game_packs_nav_button.setObjectName("navButton")
        self.game_packs_nav_button.setCheckable(True)
        self.game_packs_nav_button.clicked.connect(lambda: self._change_screen(GAME_PACKS_SCREEN))

        self.bitlcd_nav_button = QPushButton("BitLCD Marquees")
        self.bitlcd_nav_button.setObjectName("navButton")
        self.bitlcd_nav_button.setCheckable(True)
        self.bitlcd_nav_button.clicked.connect(lambda: self._change_screen(BITLCD_MARQUEES_SCREEN))

        self.queue_nav_button = QPushButton("Queue")
        self.queue_nav_button.setObjectName("navButton")
        self.queue_nav_button.setCheckable(True)
        self.queue_nav_button.clicked.connect(lambda: self._change_screen(QUEUE_SCREEN))

        self.games_nav_button = QPushButton("Games")
        self.games_nav_button.setObjectName("navButton")
        self.games_nav_button.setCheckable(True)
        self.games_nav_button.clicked.connect(lambda: self._change_screen(GAMES_SCREEN))

        sidebar_layout.addWidget(
            self._build_nav_group(
                self.settings_nav_button,
                self.queue_nav_button,
            )
        )
        sidebar_layout.addWidget(
            self._build_nav_group(
                self.base_components_nav_button,
                self.game_packs_nav_button,
                self.bitlcd_nav_button,
            )
        )
        sidebar_layout.addWidget(self._build_nav_group(self.games_nav_button))
        sidebar_layout.addStretch(1)
        self.sidebar_version_label = QLabel(APP_VERSION)
        self.sidebar_version_label.setObjectName("sidebarVersion")
        self.sidebar_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(self.sidebar_version_label)
        main_layout.addWidget(sidebar)

        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        title = QLabel()
        title.setObjectName("titleLogo")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        logo_path = _assets_dir() / "onesauce_logo.png"
        self._logo_pixmap = QPixmap(str(logo_path))
        if not self._logo_pixmap.isNull():
            self._title_logo = title
        else:
            title.setText("OnesaUCE")
            self._title_logo = None
        content_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(content_container, stretch=1)

        self.stack.addWidget(self._build_settings_screen())
        self.stack.addWidget(self._build_base_components_screen())
        self.stack.addWidget(self._build_game_packs_screen())
        self.stack.addWidget(self._build_bitlcd_marquees_screen())
        self.stack.addWidget(self._build_queue_screen())
        self.stack.addWidget(self._build_games_screen())

        self.progress_container = QWidget()
        progress_layout = QHBoxLayout(self.progress_container)
        progress_layout.setContentsMargins(0, 10, 0, 0)
        progress_layout.setSpacing(12)

        self.progress_label = QLabel("Idle")
        self.pause_button = QPushButton("Pause")
        self.pause_button.setMinimumWidth(120)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.clicked.connect(self._cancel_install)

        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch(1)
        progress_layout.addWidget(self.pause_button)
        progress_layout.addWidget(self.cancel_button)
        self.progress_container.setVisible(False)
        content_layout.addWidget(self.progress_container)

        self._set_transfer_controls_enabled(False)
        self._update_progress_controls_visibility()

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("Ready")

        file_menu = self.menuBar().addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        QTimer.singleShot(0, self._update_logo_pixmap)

    def _build_nav_group(self, *buttons: QPushButton) -> QWidget:
        container = QWidget()
        container.setObjectName("navGroup")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        for button in buttons:
            layout.addWidget(button)
        return container

    def _build_settings_screen(self) -> QWidget:
        container = QScrollArea()
        container.setWidgetResizable(True)
        container.setFrameShape(QFrame.Shape.NoFrame)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        screen = QWidget()
        container.setWidget(screen)
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(18)

        target_group = QGroupBox("Install Target")
        target_layout = QGridLayout(target_group)
        target_layout.setHorizontalSpacing(12)
        target_layout.setVerticalSpacing(10)
        target_layout.setColumnStretch(1, 1)

        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText(r"E:\ or another NTFS drive root")
        browse_button = QPushButton("Browse")
        browse_button.setMinimumWidth(160)
        browse_button.clicked.connect(self._browse_for_target)
        self.bitlcd_target_edit = QLineEdit()
        self.bitlcd_target_edit.setPlaceholderText(r"Choose a BitLCD image folder")
        bitlcd_browse_button = QPushButton("Browse")
        bitlcd_browse_button.setMinimumWidth(160)
        bitlcd_browse_button.clicked.connect(self._browse_for_bitlcd_target)
        self.validate_button = QPushButton("Validate")
        self.validate_button.setMinimumWidth(150)
        self.validate_button.clicked.connect(self._start_validate_credentials)
        self.save_settings_button = QPushButton("Save Settings")
        self.save_settings_button.setMinimumWidth(180)
        self.save_settings_button.clicked.connect(self._save_settings_and_notify)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_row.addWidget(self.save_settings_button)

        target_layout.addWidget(QLabel("Target folder"), 0, 0)
        target_layout.addWidget(self.target_edit, 0, 1)
        target_layout.addWidget(browse_button, 0, 2)
        target_layout.addWidget(QLabel("BitLCD folder"), 1, 0)
        target_layout.addWidget(self.bitlcd_target_edit, 1, 1)
        target_layout.addWidget(bitlcd_browse_button, 1, 2)
        self.root_warning = self._build_target_warning(
            "OnesaUCE will not run unless it is installed to the root of the drive."
        )
        self.ntfs_warning = self._build_target_warning(
            "OnesaUCE will not run unless the drive has been formatted NTFS."
        )
        target_layout.addWidget(self.root_warning, 2, 0, 1, 3)
        target_layout.addWidget(self.ntfs_warning, 3, 0, 1, 3)
        layout.addWidget(target_group)

        auth_group = QGroupBox("Archive.org Credentials")
        auth_layout = QGridLayout(auth_group)
        auth_layout.setHorizontalSpacing(12)
        auth_layout.setVerticalSpacing(10)
        auth_layout.setColumnStretch(1, 1)

        auth_note = QLabel("These downloads currently require Archive.org authentication.")
        auth_note.setWordWrap(True)
        signup_link = QLabel(
            '<a href="https://archive.org/account/signup">Sign up for an Internet Archive account</a>'
        )
        signup_link.setObjectName("signupLink")
        signup_link.setOpenExternalLinks(True)
        self.archive_email_edit = QLineEdit()
        self.archive_email_edit.setPlaceholderText("Archive.org email")
        self.archive_email_edit.setMinimumHeight(44)
        self.archive_password_edit = QLineEdit()
        self.archive_password_edit.setPlaceholderText("Archive.org password")
        self.archive_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.archive_password_edit.setMinimumHeight(44)
        self.parallel_downloads_spin = QSpinBox()
        self.parallel_downloads_spin.setMinimum(1)
        self.parallel_downloads_spin.setMaximum(8)
        self.parallel_downloads_spin.setValue(2)
        self.parallel_downloads_spin.setMinimumHeight(36)
        parallel_note = QLabel("Higher values allow more simultaneous downloads while another component installs.")
        parallel_note.setWordWrap(True)
        parallel_note.setObjectName("parallelNote")
        auth_actions_row = QHBoxLayout()
        auth_actions_row.addStretch(1)
        auth_actions_row.addWidget(self.validate_button)

        auth_layout.addWidget(auth_note, 0, 0, 1, 2)
        auth_layout.addWidget(signup_link, 1, 0, 1, 2)
        auth_layout.addWidget(QLabel("Email"), 2, 0)
        auth_layout.addWidget(self.archive_email_edit, 2, 1)
        auth_layout.addWidget(QLabel("Password"), 3, 0)
        auth_layout.addWidget(self.archive_password_edit, 3, 1)
        auth_layout.addWidget(QLabel("Parallel downloads"), 4, 0)
        auth_layout.addWidget(self.parallel_downloads_spin, 4, 1)
        auth_layout.addWidget(parallel_note, 5, 0, 1, 2)
        auth_layout.addLayout(auth_actions_row, 6, 0, 1, 2)
        layout.addWidget(auth_group)

        downloads_group = QGroupBox("Downloads")
        downloads_layout = QGridLayout(downloads_group)
        downloads_layout.setHorizontalSpacing(12)
        downloads_layout.setVerticalSpacing(10)
        downloads_layout.setColumnStretch(1, 1)

        self.downloads_path_edit = QLineEdit()
        self.downloads_path_edit.setPlaceholderText(str(default_downloads_dir()))
        downloads_browse_button = QPushButton("Browse")
        downloads_browse_button.setMinimumWidth(160)
        downloads_browse_button.clicked.connect(self._browse_for_downloads_path)
        self.downloads_retention_combo = QComboBox()
        self.downloads_retention_combo.addItem("Delete immediately after install", "delete")
        self.downloads_retention_combo.addItem("Keep latest version of each component", "latest")
        self.downloads_retention_combo.addItem("Keep zips up to a number of days", "days")
        self.downloads_retention_combo.addItem("Keep zips up to a max amount of space (GB)", "space")
        self.downloads_retention_days_spin = QSpinBox()
        self.downloads_retention_days_spin.setMinimum(1)
        self.downloads_retention_days_spin.setMaximum(3650)
        self.downloads_retention_days_spin.setValue(30)
        self.downloads_retention_days_spin.setFixedWidth(120)
        self.downloads_retention_max_gb_spin = QDoubleSpinBox()
        self.downloads_retention_max_gb_spin.setMinimum(0.1)
        self.downloads_retention_max_gb_spin.setMaximum(10000.0)
        self.downloads_retention_max_gb_spin.setDecimals(1)
        self.downloads_retention_max_gb_spin.setSingleStep(0.5)
        self.downloads_retention_max_gb_spin.setValue(5.0)
        self.downloads_retention_max_gb_spin.setSuffix(" GB")
        self.downloads_retention_max_gb_spin.setFixedWidth(120)
        self.clear_downloads_button = QPushButton("Clear Downloads Now")
        self.clear_downloads_button.setMinimumWidth(200)
        self.clear_downloads_button.clicked.connect(self._clear_downloads_now)
        downloads_note = QLabel("Downloaded archives are cached here before extraction and can be reused across installs.")
        downloads_note.setWordWrap(True)
        downloads_note.setObjectName("parallelNote")
        downloads_actions_row = QHBoxLayout()
        downloads_actions_row.addStretch(1)
        downloads_actions_row.addWidget(self.clear_downloads_button)
        self.downloads_retention_days_label = QLabel("Days to keep")
        self.downloads_retention_max_gb_label = QLabel("Max space")

        downloads_layout.addWidget(QLabel("Downloads folder"), 0, 0)
        downloads_layout.addWidget(self.downloads_path_edit, 0, 1)
        downloads_layout.addWidget(downloads_browse_button, 0, 2)
        downloads_layout.addWidget(QLabel("Retention"), 1, 0)
        downloads_layout.addWidget(self.downloads_retention_combo, 1, 1, 1, 2)
        downloads_layout.addWidget(self.downloads_retention_days_label, 2, 0)
        downloads_layout.addWidget(self.downloads_retention_days_spin, 2, 1)
        downloads_layout.addWidget(self.downloads_retention_max_gb_label, 3, 0)
        downloads_layout.addWidget(self.downloads_retention_max_gb_spin, 3, 1)
        downloads_layout.addWidget(downloads_note, 4, 0, 1, 3)
        downloads_layout.addLayout(downloads_actions_row, 5, 0, 1, 3)
        layout.addWidget(downloads_group)
        layout.addLayout(save_row)
        layout.addStretch(1)
        return container

    def _build_base_components_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
        self.base_summary_label = QLabel("Review required components and install or update them.")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMinimumWidth(140)
        self.refresh_button.clicked.connect(self._refresh_all_tables)
        self.install_button = QPushButton("Update")
        self.install_button.setMinimumWidth(220)
        self.install_button.clicked.connect(lambda: self._start_install_for_screen(BASE_COMPONENTS_SCREEN))
        actions_row.addWidget(self.base_summary_label)
        actions_row.addStretch(1)
        actions_row.addWidget(self.refresh_button)
        actions_row.addWidget(self.install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("Required Components")
        status_layout = QVBoxLayout(status_group)

        self.table = QTableWidget(len(REQUIRED_COMPONENTS), 6)
        self.table.setObjectName("ComponentsTable")
        self.base_header = CheckBoxHeader()
        self.base_header.toggled.connect(lambda checked: self._toggle_all_component_rows(BASE_COMPONENTS_SCREEN, checked))
        self.table.setHorizontalHeader(self.base_header)
        self.table.setHorizontalHeaderLabels(["", "Component", "Installed", "Available", "Size", "Status"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sectionClicked.connect(
            lambda section: self._handle_table_header_clicked(BASE_COMPONENTS_SCREEN, section)
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 360)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._initialize_status_cells(REQUIRED_COMPONENTS)
        status_layout.addWidget(self.table)
        layout.addWidget(status_group, stretch=2)

        layout.addSpacing(14)

        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(2000)
        self.log_output.setFont(QFont("Consolas", 10))
        log_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        log_group.setFixedHeight(190)
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_group, stretch=1)
        return screen

    def _build_game_packs_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
        self.game_packs_summary_label = QLabel("Browse and update the optional system game packs archive.")
        self.game_packs_refresh_button = QPushButton("Refresh")
        self.game_packs_refresh_button.setMinimumWidth(140)
        self.game_packs_refresh_button.clicked.connect(self._refresh_all_tables)
        self.game_packs_install_button = QPushButton("Update")
        self.game_packs_install_button.setMinimumWidth(220)
        self.game_packs_install_button.clicked.connect(lambda: self._start_install_for_screen(GAME_PACKS_SCREEN))
        actions_row.addWidget(self.game_packs_summary_label)
        actions_row.addStretch(1)
        actions_row.addWidget(self.game_packs_refresh_button)
        actions_row.addWidget(self.game_packs_install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("Game Packs")
        status_layout = QVBoxLayout(status_group)

        self.game_packs_table = QTableWidget(len(GAME_PACKS), 6)
        self.game_packs_table.setObjectName("ComponentsTable")
        self.game_packs_header = CheckBoxHeader()
        self.game_packs_header.toggled.connect(lambda checked: self._toggle_all_component_rows(GAME_PACKS_SCREEN, checked))
        self.game_packs_table.setHorizontalHeader(self.game_packs_header)
        self.game_packs_table.setHorizontalHeaderLabels(["", "Pack", "Installed", "Available", "Size", "Status"])
        self.game_packs_table.horizontalHeader().setStretchLastSection(False)
        self.game_packs_table.horizontalHeader().setSectionsClickable(True)
        self.game_packs_table.horizontalHeader().setSortIndicatorShown(True)
        self.game_packs_table.horizontalHeader().sectionClicked.connect(
            lambda section: self._handle_table_header_clicked(GAME_PACKS_SCREEN, section)
        )
        self.game_packs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.game_packs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.game_packs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.game_packs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.game_packs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.game_packs_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.game_packs_table.setColumnWidth(0, 42)
        self.game_packs_table.setColumnWidth(4, 110)
        self.game_packs_table.setColumnWidth(5, 360)
        self.game_packs_table.verticalHeader().setVisible(False)
        self.game_packs_table.verticalHeader().setDefaultSectionSize(64)
        self.game_packs_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.game_packs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.game_packs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.game_packs_table.setAlternatingRowColors(True)
        self.game_packs_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._initialize_status_cells(GAME_PACKS)
        status_layout.addWidget(self.game_packs_table)
        layout.addWidget(status_group, stretch=2)

        layout.addSpacing(14)

        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.game_packs_log_output = QPlainTextEdit()
        self.game_packs_log_output.setReadOnly(True)
        self.game_packs_log_output.setMaximumBlockCount(2000)
        self.game_packs_log_output.setFont(QFont("Consolas", 10))
        log_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        log_group.setFixedHeight(190)
        log_layout.addWidget(self.game_packs_log_output)
        layout.addWidget(log_group, stretch=1)
        return screen

    def _build_bitlcd_marquees_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
        self.bitlcd_summary_label = QLabel("Browse and update BitLCD marquee packs to the BitLCD target folder.")
        self.bitlcd_refresh_button = QPushButton("Refresh")
        self.bitlcd_refresh_button.setMinimumWidth(140)
        self.bitlcd_refresh_button.clicked.connect(self._refresh_all_tables)
        self.bitlcd_install_button = QPushButton("Update")
        self.bitlcd_install_button.setMinimumWidth(220)
        self.bitlcd_install_button.clicked.connect(lambda: self._start_install_for_screen(BITLCD_MARQUEES_SCREEN))
        actions_row.addWidget(self.bitlcd_summary_label)
        actions_row.addStretch(1)
        actions_row.addWidget(self.bitlcd_refresh_button)
        actions_row.addWidget(self.bitlcd_install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("BitLCD Marquees")
        status_layout = QVBoxLayout(status_group)

        self.bitlcd_table = QTableWidget(len(BITLCD_MARQUEES), 6)
        self.bitlcd_table.setObjectName("ComponentsTable")
        self.bitlcd_header = CheckBoxHeader()
        self.bitlcd_header.toggled.connect(lambda checked: self._toggle_all_component_rows(BITLCD_MARQUEES_SCREEN, checked))
        self.bitlcd_table.setHorizontalHeader(self.bitlcd_header)
        self.bitlcd_table.setHorizontalHeaderLabels(["", "Marquee", "Installed", "Available", "Size", "Status"])
        self.bitlcd_table.horizontalHeader().setStretchLastSection(False)
        self.bitlcd_table.horizontalHeader().setSectionsClickable(True)
        self.bitlcd_table.horizontalHeader().setSortIndicatorShown(True)
        self.bitlcd_table.horizontalHeader().sectionClicked.connect(
            lambda section: self._handle_table_header_clicked(BITLCD_MARQUEES_SCREEN, section)
        )
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.bitlcd_table.setColumnWidth(0, 42)
        self.bitlcd_table.setColumnWidth(4, 110)
        self.bitlcd_table.setColumnWidth(5, 360)
        self.bitlcd_table.verticalHeader().setVisible(False)
        self.bitlcd_table.verticalHeader().setDefaultSectionSize(64)
        self.bitlcd_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.bitlcd_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bitlcd_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bitlcd_table.setAlternatingRowColors(True)
        self.bitlcd_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._initialize_status_cells(BITLCD_MARQUEES)
        status_layout.addWidget(self.bitlcd_table)
        layout.addWidget(status_group, stretch=2)

        layout.addSpacing(14)

        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.bitlcd_log_output = QPlainTextEdit()
        self.bitlcd_log_output.setReadOnly(True)
        self.bitlcd_log_output.setMaximumBlockCount(2000)
        self.bitlcd_log_output.setFont(QFont("Consolas", 10))
        log_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        log_group.setFixedHeight(190)
        log_layout.addWidget(self.bitlcd_log_output)
        layout.addWidget(log_group, stretch=1)
        return screen

    def _build_queue_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
        self.queue_summary_label = QLabel("Queued component updates start automatically and can be reordered below.")
        self.queue_pause_button = QPushButton("Pause")
        self.queue_pause_button.setMinimumWidth(140)
        self.queue_pause_button.clicked.connect(self._toggle_pause)
        self.queue_clear_button = QPushButton("Clear")
        self.queue_clear_button.setMinimumWidth(120)
        self.queue_clear_button.clicked.connect(self._clear_queue)
        actions_row.addWidget(self.queue_summary_label)
        actions_row.addStretch(1)
        actions_row.addWidget(self.queue_pause_button)
        actions_row.addWidget(self.queue_clear_button)
        layout.addLayout(actions_row)

        queue_group = QGroupBox("Queue")
        queue_layout = QVBoxLayout(queue_group)
        self.queue_table = QTableWidget(0, 6)
        self.queue_table.setObjectName("QueueTable")
        self.queue_table.setHorizontalHeaderLabels(["", "Component", "Source", "Available", "Size", "Status"])
        self.queue_table.horizontalHeader().setStretchLastSection(False)
        self.queue_table.horizontalHeader().setSectionsClickable(True)
        self.queue_table.horizontalHeader().setSortIndicatorShown(True)
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
        self.queue_table.setColumnWidth(5, 360)
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

    def _build_games_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(12)
        self.games_name_filter = QLineEdit()
        self.games_name_filter.setPlaceholderText("Filter by game name")
        self.games_name_filter.textChanged.connect(self._reset_games_page_and_refresh)
        self.games_pack_filter = QComboBox()
        self.games_pack_filter.addItem("All Game Packs", "")
        for pack_name in self._game_pack_options:
            self.games_pack_filter.addItem(pack_name, pack_name)
        self.games_pack_filter.currentIndexChanged.connect(self._reset_games_page_and_refresh)
        self.games_status_filter = QComboBox()
        self.games_status_filter.addItem("All Statuses", "")
        self.games_status_filter.addItem("Installed", "Installed")
        self.games_status_filter.addItem("Not Installed", "Not Installed")
        self.games_status_filter.currentIndexChanged.connect(self._reset_games_page_and_refresh)

        filters_row.addWidget(QLabel("Game Name"))
        filters_row.addWidget(self.games_name_filter, stretch=2)
        filters_row.addWidget(QLabel("Game Pack"))
        filters_row.addWidget(self.games_pack_filter, stretch=1)
        filters_row.addWidget(QLabel("Status"))
        filters_row.addWidget(self.games_status_filter, stretch=1)
        layout.addLayout(filters_row)

        games_group = QGroupBox("Games")
        games_layout = QVBoxLayout(games_group)
        self.games_table = QTableWidget(0, 4)
        self.games_table.setObjectName("GamesTable")
        self.games_table.setHorizontalHeaderLabels(["Game Name", "Game Pack", "Status", ""])
        self.games_table.horizontalHeader().setStretchLastSection(False)
        self.games_table.horizontalHeader().setSectionsClickable(True)
        self.games_table.horizontalHeader().setSortIndicatorShown(True)
        self.games_table.horizontalHeader().sectionClicked.connect(self._handle_games_header_clicked)
        self.games_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.games_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.games_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.games_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.games_table.setColumnWidth(3, 54)
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

    def _apply_style(self) -> None:
        assets_dir = _assets_dir()
        spin_up_icon = (assets_dir / "chevron_up_white.svg").as_posix()
        spin_down_icon = (assets_dir / "chevron_down_white.svg").as_posix()
        checkbox_check_icon = (assets_dir / "check_white.svg").as_posix()
        queue_remove_icon = (assets_dir / "queue_remove_red.svg").as_posix()
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: #1e1e1e;
            }}
            QWidget {{
                background: #2b2b2b;
                color: #ffffff;
                font-family: "Segoe UI";
                font-size: 11pt;
            }}
            QGroupBox {{
                border: 1px solid #555555;
                border-radius: 10px;
                margin-top: 14px;
                padding: 16px 14px 14px 14px;
                background: #222222;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px 0 6px;
                color: #aaaaaa;
                font-weight: 600;
            }}
            QWidget#sidebarCard {{
                background: #222222;
                border: 1px solid #555555;
                border-radius: 12px;
            }}
            QWidget#navGroup {{
                background: #1f1f1f;
                border: 1px solid #4f4f4f;
                border-radius: 12px;
            }}
            QLabel {{
                background: transparent;
                color: #ffffff;
            }}
            QLineEdit, QPlainTextEdit, QTextEdit {{
                background: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
            }}
            QComboBox {{
                background: #242424;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 8px 34px 8px 10px;
                min-height: 24px;
            }}
            QComboBox:hover {{
                border-color: #666666;
            }}
            QComboBox:focus {{
                border-color: #2ea3ff;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url("{spin_down_icon}");
                width: 10px;
                height: 10px;
            }}
            QComboBox QAbstractItemView {{
                background: #242424;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #0084ff;
                selection-color: #ffffff;
            }}
            QSpinBox {{
                background: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 6px 40px 6px 10px;
                min-height: 24px;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
                border-color: #2ea3ff;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                subcontrol-origin: border;
                width: 28px;
                background: #222222;
                border-left: 1px solid #555555;
            }}
            QSpinBox::up-button {{
                subcontrol-position: top right;
                border-top-right-radius: 8px;
                border-bottom: 1px solid #555555;
            }}
            QSpinBox::down-button {{
                subcontrol-position: bottom right;
                border-bottom-right-radius: 8px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: #3a3a3a;
            }}
            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
                background: #0066cc;
            }}
            QSpinBox::up-arrow, QSpinBox::down-arrow {{
                width: 10px;
                height: 10px;
            }}
            QSpinBox::up-arrow {{
                image: url("{spin_up_icon}");
            }}
            QSpinBox::down-arrow {{
                image: url("{spin_down_icon}");
            }}
            QTableWidget#ComponentsTable, QTableWidget#QueueTable, QTableWidget#GamesTable {{
                gridline-color: #555555;
                alternate-background-color: #242424;
                border: 1px solid #555555;
                border-radius: 4px;
                background: #2b2b2b;
            }}
            QTableWidget#ComponentsTable::item, QTableWidget#QueueTable::item, QTableWidget#GamesTable::item {{
                padding: 4px;
                selection-background-color: #2b2b2b;
                selection-color: #ffffff;
            }}
            QCheckBox#rowSelector {{
                background: transparent;
                spacing: 0px;
            }}
            QCheckBox#rowSelector::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid #555555;
                border-radius: 3px;
                background: #2b2b2b;
            }}
            QCheckBox#rowSelector::indicator:hover {{
                border-color: #2ea3ff;
            }}
            QCheckBox#rowSelector::indicator:checked {{
                border-color: #2ea3ff;
                background: #2ea3ff;
                image: url("{checkbox_check_icon}");
            }}
            QCheckBox#headerSelector {{
                background: transparent;
                spacing: 0px;
            }}
            QCheckBox#headerSelector::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid #d8e6f2;
                border-radius: 3px;
                background: #737b84;
            }}
            QCheckBox#headerSelector::indicator:hover {{
                border-color: #ffffff;
                background: #7f8892;
            }}
            QCheckBox#headerSelector::indicator:checked {{
                border-color: #2ea3ff;
                background: #2ea3ff;
                image: url("{checkbox_check_icon}");
            }}
            QTableCornerButton::section {{
                background: #2b2b2b;
                border: 1px solid #555555;
            }}
            QPushButton {{
                background: #2ea3ff;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #1495ff;
            }}
            QPushButton:pressed {{
                background: #0066cc;
            }}
            QPushButton:disabled {{
                background: #4a4a4a;
                color: #8f8f8f;
            }}
            QPushButton#navButton {{
                background: transparent;
                color: #aaaaaa;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 14px 14px;
                text-align: left;
                font-weight: 700;
                font-size: 11.5pt;
            }}
            QPushButton#navButton:hover {{
                background: #3a3a3a;
                color: #ffffff;
                border-color: #555555;
            }}
            QPushButton#navButton:checked {{
                background: #0084ff;
                color: white;
                border-color: #0084ff;
            }}
            QLabel#sidebarVersion {{
                color: #8f8f8f;
                font-size: 10pt;
                font-weight: 600;
                padding-top: 4px;
            }}
            QLabel#gamesPlaceholder {{
                color: #7f8790;
                font-size: 14pt;
                font-weight: 700;
            }}
            QPushButton#gameLink {{
                background: transparent;
                color: #69b8ff;
                border: none;
                border-radius: 0px;
                padding: 0;
                text-align: left;
                font-weight: 600;
            }}
            QPushButton#gameLink:hover {{
                background: transparent;
                color: #8bc9ff;
                text-decoration: underline;
            }}
            QPushButton#gameLink:pressed {{
                background: transparent;
                color: #2ea3ff;
            }}
            QToolButton[queueAction="true"] {{
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
                min-width: 22px;
                min-height: 22px;
            }}
            QToolButton[queueAction="true"]:hover {{
                background: #3a3a3a;
            }}
            QToolButton[queueAction="true"]:pressed {{
                background: #0066cc;
            }}
            QToolButton[queueAction="true"]:disabled {{
                background: transparent;
            }}
            QHeaderView::section {{
                background: #242424;
                color: #ffffff;
                border: none;
                border-right: 1px solid #555555;
                padding: 10px 28px 10px 10px;
                font-weight: 700;
            }}
            QHeaderView::up-arrow {{
                image: url("{spin_up_icon}");
                width: 10px;
                height: 10px;
            }}
            QHeaderView::down-arrow {{
                image: url("{spin_down_icon}");
                width: 10px;
                height: 10px;
            }}
            QProgressBar {{
                border: 1px solid #555555;
                border-radius: 8px;
                background: #3a3a3a;
                text-align: center;
                min-height: 24px;
                color: #ffffff;
                font-weight: 700;
            }}
            QProgressBar::chunk {{
                border-radius: 7px;
                background: #2ea3ff;
            }}
            QLabel#titleLogo {{
                padding: 0 0 8px 0;
                background: transparent;
            }}
            QLabel#signupLink {{
                color: #00c4f4;
                padding-top: 2px;
            }}
            QLabel#parallelNote {{
                color: #aaaaaa;
                padding-top: 2px;
            }}
            QWidget#warningBanner {{
                background: #3a2f12;
                border: 1px solid #b38a1f;
                border-radius: 8px;
            }}
            QLabel#warningMessage {{
                color: #ffd66b;
                padding: 2px 0;
            }}
            QStatusBar {{
                background: #222222;
                color: #aaaaaa;
                border-top: 1px solid #555555;
            }}
            QMenuBar {{
                background: #222222;
                color: #ffffff;
                border-bottom: 1px solid #555555;
            }}
            QMenuBar::item:selected {{
                background: #3a3a3a;
            }}
            QMenu {{
                background: #222222;
                color: #ffffff;
                border: 1px solid #555555;
            }}
            QMenu::item:selected {{
                background: #0084ff;
            }}
            QScrollBar:vertical {{
                background: #2b2b2b;
                width: 12px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #555555;
                min-height: 24px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #666666;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background: #2b2b2b;
                height: 12px;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: #555555;
                min-width: 24px;
                border-radius: 6px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #666666;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            """
        )

    def _connect_setting_signals(self) -> None:
        self.target_edit.textChanged.connect(self._save_settings)
        self.target_edit.textChanged.connect(self._schedule_scan)
        self.target_edit.textChanged.connect(self._refresh_target_validation)
        self.bitlcd_target_edit.textChanged.connect(self._save_settings)
        self.bitlcd_target_edit.textChanged.connect(self._schedule_scan)
        self.downloads_path_edit.textChanged.connect(self._save_settings)
        self.downloads_retention_combo.currentIndexChanged.connect(self._sync_download_retention_controls)
        self.downloads_retention_combo.currentIndexChanged.connect(self._save_settings)
        self.downloads_retention_days_spin.valueChanged.connect(self._save_settings)
        self.downloads_retention_max_gb_spin.valueChanged.connect(self._save_settings)
        self.archive_email_edit.textChanged.connect(self._save_settings)
        self.archive_password_edit.textChanged.connect(self._save_settings)
        self.parallel_downloads_spin.valueChanged.connect(self._save_settings)

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
            self.archive_email_edit.setText(settings.archive_email)
            self.archive_password_edit.setText(settings.archive_password)
            self.parallel_downloads_spin.setValue(settings.parallel_downloads)
            self._apply_download_settings_to_installers(settings)
            self.resize(settings.window_width, settings.window_height)
            self._load_saved_queue_entries(settings)
        finally:
            self._loading_settings = False
        self._refresh_target_validation()
        self._sync_download_retention_controls()
        self._enforce_download_cache_policy()

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
            archive_email=self.archive_email_edit.text().strip(),
            archive_password=self.archive_password_edit.text(),
            parallel_downloads=self.parallel_downloads_spin.value(),
            window_width=self.width(),
            window_height=self.height(),
            queue_entries=self._serialized_queue_entries(),
        )
        self.settings_store.save(settings)
        self._apply_download_settings_to_installers(settings)

    def _save_settings_and_notify(self) -> None:
        self._save_settings()
        result = self._enforce_download_cache_policy()
        self._refresh_all_tables()
        cleanup_note = ""
        if result.deleted_files:
            cleanup_note = f"\nDownloads cleaned: {result.deleted_files} file(s) removed."
        QMessageBox.information(self, "Settings saved", f"Settings were saved.{cleanup_note}")

    def _start_validate_credentials(self) -> None:
        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password before validating.",
            )
            return

        self._save_settings()
        self._set_action_buttons_enabled(False)
        self._set_queue_controls_enabled(False)
        self.statusBar().showMessage("Validating Archive.org credentials...")

        self._validate_thread = QThread(self)
        self._validate_worker = ValidateCredentialsWorker(credentials)
        self._validate_worker.moveToThread(self._validate_thread)

        self._validate_thread.started.connect(self._validate_worker.run)
        self._validate_worker.finished.connect(self._validate_credentials_success)
        self._validate_worker.error.connect(self._validate_credentials_error)
        self._validate_worker.finished.connect(self._validate_thread.quit)
        self._validate_worker.error.connect(self._validate_thread.quit)
        self._validate_thread.finished.connect(self._validate_thread.deleteLater)
        self._validate_thread.finished.connect(self._clear_validate_refs)
        self._validate_thread.start()

    def _show_initial_screen(self) -> None:
        settings = self.settings_store.load()
        has_settings = bool(
            settings.install_target.strip()
            or settings.bitlcd_target.strip()
            or settings.archive_email.strip()
            or settings.archive_password
        )
        self._change_screen(BASE_COMPONENTS_SCREEN if has_settings else SETTINGS_SCREEN)

    def _resume_saved_queue_if_possible(self) -> None:
        if self._controller is not None or not self._queue_entries:
            self._update_queue_buttons()
            return
        pending_entries = [entry for entry in self._queue_entries if entry.status != "Installed"]
        if not pending_entries:
            self._update_queue_buttons()
            return
        if self._archive_credentials() is None:
            self.statusBar().showMessage("Saved queue loaded. Enter Archive.org credentials to resume.")
            self._update_queue_buttons()
            return
        if not pending_entries[0].target_path.strip():
            self.statusBar().showMessage("Saved queue loaded. Choose a target folder to resume.")
            self._update_queue_buttons()
            return
        self._change_screen(QUEUE_SCREEN)
        self.queue_log_output.appendPlainText(f"Resuming saved queue with {len(pending_entries)} item(s).")
        self._start_queue_install()

    def _change_screen(self, index: int) -> None:
        if index < 0:
            return
        self.stack.setCurrentIndex(index)
        self.settings_nav_button.setChecked(index == SETTINGS_SCREEN)
        self.base_components_nav_button.setChecked(index == BASE_COMPONENTS_SCREEN)
        self.game_packs_nav_button.setChecked(index == GAME_PACKS_SCREEN)
        self.bitlcd_nav_button.setChecked(index == BITLCD_MARQUEES_SCREEN)
        self.queue_nav_button.setChecked(index == QUEUE_SCREEN)
        self.games_nav_button.setChecked(index == GAMES_SCREEN)
        self._update_progress_controls_visibility()
        if index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN}:
            self._refresh_screen_table(index)
        elif index == QUEUE_SCREEN:
            self._refresh_queue_table()
        elif index == GAMES_SCREEN:
            self._refresh_games_table()

    def _browse_for_target(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose OnesaUCE target folder")
        if directory:
            self.target_edit.setText(directory)
            self._refresh_all_tables()

    def _browse_for_bitlcd_target(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose BitLCD target folder")
        if directory:
            self.bitlcd_target_edit.setText(directory)

    def _browse_for_downloads_path(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose downloads cache folder")
        if directory:
            self.downloads_path_edit.setText(directory)

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
        self.base_installer.cache_dir = downloads_dir
        self.game_packs_installer.cache_dir = downloads_dir
        self.bitlcd_installer.cache_dir = downloads_dir
        self.base_installer.max_parallel_downloads = settings.parallel_downloads
        self.game_packs_installer.max_parallel_downloads = settings.parallel_downloads
        self.bitlcd_installer.max_parallel_downloads = settings.parallel_downloads

    def _clear_downloads_now(self) -> None:
        result = clear_downloads_dir(self._downloads_dir())
        self.statusBar().showMessage(f"Cleared {result.deleted_files} download file(s).")
        QMessageBox.information(
            self,
            "Downloads cleared",
            f"Removed {result.deleted_files} file(s) from the downloads cache.",
        )

    def _enforce_download_cache_policy(self):
        settings = self.settings_store.load()
        return enforce_download_cache_policy(
            self._downloads_dir(),
            settings.downloads_retention_mode,
            self._all_components_by_key.values(),
            days=settings.downloads_retention_days,
            max_gb=settings.downloads_retention_max_gb,
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
            return

        self.root_warning.setVisible(not self._is_root_target(target))
        self.ntfs_warning.setVisible(not self._is_ntfs_target(target))

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

    def _update_logo_pixmap(self) -> None:
        if self._title_logo is None or self._logo_pixmap.isNull():
            return
        self._title_logo.setPixmap(self._logo_pixmap)
        self._title_logo.setFixedSize(self._logo_pixmap.size())

    def _schedule_scan(self) -> None:
        if self._loading_settings:
            return
        self._scan_timer.start()

    def _refresh_all_tables(self) -> None:
        self._games_installed_target = None
        self._games_excluded_target = None
        self._refresh_screen_table(BASE_COMPONENTS_SCREEN)
        self._refresh_screen_table(GAME_PACKS_SCREEN)
        self._refresh_screen_table(BITLCD_MARQUEES_SCREEN)
        self._refresh_games_table()

    def _refresh_screen_table(self, screen_index: int) -> None:
        table = self._table_for_screen(screen_index)
        components = self._components_for_screen(screen_index)
        installer = self._installer_for_screen(screen_index)
        target = self._target_dir_for_screen(screen_index)
        self._refresh_remote_sizes_for_screen(screen_index)
        if target is None:
            self._populate_missing_table(table, self._sorted_component_specs(screen_index, list(components)))
            self._update_primary_action(screen_index, [])
            self._sync_header_checkbox(screen_index)
            self._apply_sort_indicator(screen_index)
            if self.stack.currentIndex() == screen_index:
                if screen_index == BITLCD_MARQUEES_SCREEN:
                    self.statusBar().showMessage("Select a BitLCD target folder to scan.")
                else:
                    self.statusBar().showMessage("Select a target folder to scan.")
            return

        self._selection_sync = True
        statuses = self._sorted_component_statuses(screen_index, installer.scan_target(target))
        table.setUpdatesEnabled(False)
        table.setRowCount(len(statuses))
        for row, status in enumerate(statuses):
            self._set_checkbox_widget(table, row, status.spec.key, screen_index)
            self._set_item(table, row, BASE_TABLE_COLUMNS["component"], status.spec.display_name)
            self._set_item(table, row, BASE_TABLE_COLUMNS["installed"], status.installed_version or "Not installed")
            self._set_item(table, row, BASE_TABLE_COLUMNS["available"], status.spec.available_display)
            self._set_item(table, row, BASE_TABLE_COLUMNS["size"], self._component_size_display(status.spec))
            self._set_status_cell(table, row, status.spec.key, BASE_TABLE_COLUMNS["status"])
            if status.spec.key not in self._active_components:
                self._set_status_widget(status.spec.key, status.status, 100 if status.status == "Installed" else 0)
        self._selection_sync = False
        table.setUpdatesEnabled(True)
        self._update_primary_action(screen_index, statuses)
        self._sync_header_checkbox(screen_index)
        self._apply_sort_indicator(screen_index)
        if self.stack.currentIndex() == screen_index:
            self.statusBar().showMessage(f"Scanned {target}")

    def _populate_missing_table(self, table: QTableWidget, components: list[ComponentSpec]) -> None:
        screen_index = self._screen_for_table(table)
        self._selection_sync = True
        table.setUpdatesEnabled(False)
        table.setRowCount(len(components))
        for row, spec in enumerate(components):
            self._set_checkbox_widget(table, row, spec.key, screen_index)
            self._set_item(table, row, BASE_TABLE_COLUMNS["component"], spec.display_name)
            self._set_item(table, row, BASE_TABLE_COLUMNS["installed"], "Not scanned")
            self._set_item(table, row, BASE_TABLE_COLUMNS["available"], spec.available_display)
            self._set_item(table, row, BASE_TABLE_COLUMNS["size"], self._component_size_display(spec))
            self._set_status_cell(table, row, spec.key, BASE_TABLE_COLUMNS["status"])
            self._set_status_widget(spec.key, "Pending", 0)
        self._selection_sync = False
        table.setUpdatesEnabled(True)

    def _refresh_games_table(self) -> None:
        installed_games = self._installed_games_for_current_target()
        excluded_games = self._excluded_games_for_current_target()
        filtered_entries = self._sorted_filtered_games(installed_games, excluded_games)
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
            status = "Installed" if entry.key in installed_games else "Not Installed"
            self._set_games_name_cell(row, entry, status)
            self._set_item(self.games_table, row, GAMES_TABLE_COLUMNS["game_pack"], entry.game_pack)
            self._set_item(self.games_table, row, GAMES_TABLE_COLUMNS["status"], status)
            self._set_games_placeholder_cell(row)
        self.games_table.setUpdatesEnabled(True)
        self.games_table.horizontalHeader().setSortIndicator(self._games_sort_column, self._games_sort_order)
        self.games_table.horizontalHeader().setSortIndicatorShown(True)
        self._update_games_pagination(total_items, total_pages)
        if self.stack.currentIndex() == GAMES_SCREEN:
            target = self._target_dir()
            if target is None:
                self.statusBar().showMessage("Select a target folder to scan installed games.")
            else:
                self.statusBar().showMessage(f"Loaded {total_items} games for {target}")

    def _installed_games_for_current_target(self) -> set[tuple[str, str]]:
        target = self._target_dir()
        target_key = str(target) if target is not None else ""
        if self._games_installed_target == target_key:
            return self._installed_games_cache
        self._games_installed_target = target_key
        self._installed_games_cache = scan_installed_games(target)
        return self._installed_games_cache

    def _excluded_games_for_current_target(self) -> set[tuple[str, str]]:
        target = self._target_dir()
        target_key = str(target) if target is not None else ""
        if self._games_excluded_target == target_key:
            return self._excluded_games_cache
        self._games_excluded_target = target_key
        self._excluded_games_cache = scan_excluded_games(target)
        return self._excluded_games_cache

    def _sorted_filtered_games(
        self,
        installed_games: set[tuple[str, str]],
        excluded_games: set[tuple[str, str]],
    ):
        name_filter = self.games_name_filter.text().strip().casefold()
        pack_filter = str(self.games_pack_filter.currentData() or "")
        status_filter = str(self.games_status_filter.currentData() or "")

        filtered_entries = []
        for entry in self._game_entries:
            if is_excluded_game(entry, excluded_games):
                continue
            status = "Installed" if entry.key in installed_games else "Not Installed"
            if name_filter and name_filter not in entry.game_name.casefold():
                continue
            if pack_filter and entry.game_pack != pack_filter:
                continue
            if status_filter and status != status_filter:
                continue
            filtered_entries.append(entry)

        reverse = self._games_sort_order == Qt.SortOrder.DescendingOrder
        return sorted(filtered_entries, key=lambda entry: self._games_sort_key(entry, installed_games), reverse=reverse)

    def _games_sort_key(self, entry, installed_games: set[tuple[str, str]]) -> Any:
        if self._games_sort_column == GAMES_TABLE_COLUMNS["game_name"]:
            return (entry.game_name.casefold(), entry.game_pack.casefold(), entry.rom_path.casefold())
        if self._games_sort_column == GAMES_TABLE_COLUMNS["game_pack"]:
            return (entry.game_pack.casefold(), entry.game_name.casefold(), entry.rom_path.casefold())
        if self._games_sort_column == GAMES_TABLE_COLUMNS["status"]:
            installed = entry.key in installed_games
            return (0 if installed else 1, entry.game_name.casefold(), entry.game_pack.casefold())
        return (entry.game_name.casefold(), entry.game_pack.casefold(), entry.rom_path.casefold())

    def _set_games_placeholder_cell(self, row: int) -> None:
        placeholder = QLabel("â‰¡")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setObjectName("gamesPlaceholder")
        self.games_table.setCellWidget(row, GAMES_TABLE_COLUMNS["actions"], placeholder)

    def _set_games_name_cell(self, row: int, entry: GameManifestEntry, status: str) -> None:
        button = QPushButton(entry.game_name)
        button.setObjectName("gameLink")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(
            lambda _checked=False, game_entry=entry, installed=(status == "Installed"): self._open_game_details_dialog(
                game_entry,
                installed,
            )
        )
        self.games_table.setCellWidget(row, GAMES_TABLE_COLUMNS["game_name"], button)

    def _open_game_details_dialog(self, entry: GameManifestEntry, installed: bool) -> None:
        dialog = GameDetailsDialog(entry, installed, self._target_dir(), self)
        dialog.exec()

    def _handle_games_header_clicked(self, section: int) -> None:
        if section == GAMES_TABLE_COLUMNS["actions"]:
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

    def _reset_games_page_and_refresh(self, *_args) -> None:
        self._games_current_page = 1
        self._refresh_games_table()

    def _set_games_page(self, page: int) -> None:
        self._games_current_page = max(1, page)
        self._refresh_games_table()

    def _go_to_last_games_page(self) -> None:
        installed_games = self._installed_games_for_current_target()
        excluded_games = self._excluded_games_for_current_target()
        total_items = len(self._sorted_filtered_games(installed_games, excluded_games))
        total_pages = max(1, (total_items + self._games_page_size - 1) // self._games_page_size)
        self._games_current_page = total_pages
        self._refresh_games_table()

    def _change_games_page_size(self, *_args) -> None:
        self._games_page_size = int(self.games_page_size_combo.currentData() or 100)
        self._games_current_page = 1
        self._refresh_games_table()

    def _update_games_pagination(self, total_items: int, total_pages: int) -> None:
        self.games_results_label.setText(f"{total_items:,} games")
        self.games_page_label.setText(f"Page {self._games_current_page} of {total_pages}")
        self.games_first_button.setEnabled(self._games_current_page > 1)
        self.games_previous_button.setEnabled(self._games_current_page > 1)
        self.games_next_button.setEnabled(self._games_current_page < total_pages)
        self.games_last_button.setEnabled(self._games_current_page < total_pages)

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
        return {
            BASE_TABLE_COLUMNS["component"],
            BASE_TABLE_COLUMNS["installed"],
            BASE_TABLE_COLUMNS["available"],
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
        if column == BASE_TABLE_COLUMNS["size"]:
            return self._sort_by_size(
                components,
                key_fn=self._component_size_bytes,
                descending=order == Qt.SortOrder.DescendingOrder,
            )
        reverse = order == Qt.SortOrder.DescendingOrder
        return sorted(components, key=lambda spec: self._component_spec_sort_key(column, spec), reverse=reverse)

    def _sorted_component_statuses(self, screen_index: int, statuses: list[Any]) -> list[Any]:
        column, order = self._sort_states[screen_index]
        if column == BASE_TABLE_COLUMNS["size"]:
            return self._sort_by_size(
                statuses,
                key_fn=lambda status: self._component_size_bytes(status.spec),
                descending=order == Qt.SortOrder.DescendingOrder,
            )
        reverse = order == Qt.SortOrder.DescendingOrder
        return sorted(statuses, key=lambda status: self._component_status_sort_key(column, status), reverse=reverse)

    def _component_spec_sort_key(self, column: int, spec: ComponentSpec) -> Any:
        if column == BASE_TABLE_COLUMNS["component"]:
            return spec.display_name.casefold()
        if column == BASE_TABLE_COLUMNS["installed"]:
            return self._version_sort_key(None)
        if column == BASE_TABLE_COLUMNS["available"]:
            return self._version_sort_key(spec.available_version)
        if column == BASE_TABLE_COLUMNS["size"]:
            return self._size_sort_key(self._component_size_bytes(spec), self._component_size_display(spec))
        if column == BASE_TABLE_COLUMNS["status"]:
            return self._status_sort_key("Pending", 0)
        return spec.display_name.casefold()

    def _component_status_sort_key(self, column: int, status: Any) -> Any:
        if column == BASE_TABLE_COLUMNS["component"]:
            return status.spec.display_name.casefold()
        if column == BASE_TABLE_COLUMNS["installed"]:
            return self._version_sort_key(status.installed_version)
        if column == BASE_TABLE_COLUMNS["available"]:
            return self._version_sort_key(status.available_version)
        if column == BASE_TABLE_COLUMNS["size"]:
            return self._size_sort_key(
                self._component_size_bytes(status.spec),
                self._component_size_display(status.spec),
            )
        if column == BASE_TABLE_COLUMNS["status"]:
            _, percent = self._status_state.get(status.spec.key, (status.status, 0))
            return self._status_sort_key(status.status, percent)
        return status.spec.display_name.casefold()

    def _sort_queue_entries(self) -> None:
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
        self._queue_entries.sort(key=lambda entry: self._queue_entry_sort_key(column, entry), reverse=reverse)

    def _queue_entry_sort_key(self, column: int, entry: QueueEntry) -> Any:
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
        checkbox.setChecked(component_key in self._selected_component_keys.get(screen_index, set()))
        table.setCellWidget(row, 0, container)

    def _screen_for_table(self, table: QTableWidget) -> int:
        if table is self.bitlcd_table:
            return BITLCD_MARQUEES_SCREEN
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
        if checked:
            selected_keys.update(spec.key for spec in self._components_for_screen(screen_index))
        else:
            selected_keys.clear()
        self._refresh_screen_table(screen_index)
        self._sync_header_checkbox(screen_index)

    def _sync_header_checkbox(self, screen_index: int) -> None:
        components = self._components_for_screen(screen_index)
        selected = self._selected_component_keys.get(screen_index, set())
        checked = bool(components) and all(spec.key in selected for spec in components)
        if screen_index == BITLCD_MARQUEES_SCREEN:
            self.bitlcd_header.set_checked(checked)
            return
        if screen_index == GAME_PACKS_SCREEN:
            self.game_packs_header.set_checked(checked)
            return
        self.base_header.set_checked(checked)

    def _refresh_queue_table(self) -> None:
        self.queue_table.setUpdatesEnabled(False)
        self.queue_table.setRowCount(len(self._queue_entries))
        self._queue_status_widgets.clear()
        for row, entry in enumerate(self._queue_entries):
            self._set_queue_actions_widget(row, entry)
            self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["component"], entry.spec.display_name)
            self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["source"], entry.source_label)
            self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["available"], entry.spec.available_display)
            self._set_item(self.queue_table, row, QUEUE_TABLE_COLUMNS["size"], self._component_size_display(entry.spec))
            widget = ComponentStatusCell()
            widget.set_status(entry.status, entry.percent)
            self._queue_status_widgets[entry.spec.key] = widget
            self.queue_table.setCellWidget(row, QUEUE_TABLE_COLUMNS["status"], widget)
        self.queue_table.setUpdatesEnabled(True)
        self._apply_sort_indicator(QUEUE_SCREEN)
        self._update_queue_buttons()

    def _update_queue_buttons(self) -> None:
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

    def _set_queue_actions_widget(self, row: int, entry: QueueEntry) -> None:
        assets_dir = _assets_dir()
        up_icon = QIcon(str(assets_dir / "chevron_up_white.svg"))
        down_icon = QIcon(str(assets_dir / "chevron_down_white.svg"))
        remove_icon = QIcon(str(assets_dir / "queue_remove_red.svg"))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        up_button = QToolButton()
        up_button.setProperty("queueAction", True)
        up_button.setIcon(up_icon)
        up_button.setIconSize(QSize(14, 14))
        up_button.setEnabled(self._controller is None and row > 0)
        up_button.clicked.connect(lambda _=False, key=entry.spec.key: self._move_queue_entry(key, -1))

        down_button = QToolButton()
        down_button.setProperty("queueAction", True)
        down_button.setIcon(down_icon)
        down_button.setIconSize(QSize(14, 14))
        down_button.setEnabled(self._controller is None and row < len(self._queue_entries) - 1)
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

    def _set_queue_controls_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.queue_clear_button.setEnabled(False)
            self.queue_pause_button.setEnabled(bool(self._queue_entries))
            self._refresh_queue_table()
            return
        self._update_queue_buttons()
        self._refresh_queue_table()

    def _move_queue_entry(self, component_key: str, offset: int) -> None:
        row = next((index for index, entry in enumerate(self._queue_entries) if entry.spec.key == component_key), -1)
        if row < 0:
            return
        new_row = row + offset
        if new_row < 0 or new_row >= len(self._queue_entries):
            return
        self._queue_entries[row], self._queue_entries[new_row] = self._queue_entries[new_row], self._queue_entries[row]
        self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
        self._refresh_queue_table()
        self._save_settings()

    def _remove_queue_entry(self, component_key: str) -> None:
        if self._controller is not None:
            self._controller.skip_component(component_key)
        self._queue_entries = [entry for entry in self._queue_entries if entry.spec.key != component_key]
        self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
        self._refresh_queue_table()
        self._save_settings()

    def _clear_queue(self) -> None:
        self._queue_entries.clear()
        self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
        self._refresh_queue_table()
        self._save_settings()

    def _update_queue_status(self, component_key: str, status: str, percent: float) -> None:
        widget = self._queue_status_widgets.get(component_key)
        if widget is not None:
            widget.set_status(status, percent)
        for entry in self._queue_entries:
            if entry.spec.key == component_key:
                entry.status = status
                entry.percent = percent
                break

    def _set_status_widget(self, component_key: str, status: str, percent: float) -> None:
        self._status_state[component_key] = (status, percent)
        widget = self._status_widgets.get(component_key)
        if widget is not None and isValid(widget):
            widget.set_status(status, percent)

    def _components_for_screen(self, screen_index: int) -> tuple[ComponentSpec, ...]:
        if screen_index == BASE_COMPONENTS_SCREEN:
            return REQUIRED_COMPONENTS
        if screen_index == GAME_PACKS_SCREEN:
            return GAME_PACKS
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return BITLCD_MARQUEES
        return ()

    def _installer_for_screen(self, screen_index: int) -> Installer:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_installer
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_installer
        return self.base_installer

    def _table_for_screen(self, screen_index: int) -> QTableWidget:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_table
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_table
        return self.table

    def _install_button_for_screen(self, screen_index: int) -> QPushButton:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_install_button
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_install_button
        return self.install_button

    def _refresh_button_for_screen(self, screen_index: int) -> QPushButton:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_refresh_button
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_refresh_button
        return self.refresh_button

    def _log_output_for_screen(self, screen_index: int) -> QPlainTextEdit:
        if screen_index == QUEUE_SCREEN:
            return self.queue_log_output
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_log_output
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_log_output
        return self.log_output

    def _screen_label(self, screen_index: int) -> str:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return "BitLCD marquees"
        if screen_index == GAME_PACKS_SCREEN:
            return "Game packs"
        if screen_index == QUEUE_SCREEN:
            return "Queue"
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
        self._change_screen(QUEUE_SCREEN)
        if self._controller is None:
            self._start_queue_install()

    def _enqueue_selected_for_screen(self, screen_index: int, target: Path) -> int:
        installer = self._installer_for_screen(screen_index)
        statuses = installer.scan_target(target)
        selected_keys = self._selected_component_keys.get(screen_index, set())
        added = 0
        if screen_index == GAME_PACKS_SCREEN:
            source_label = "Game Pack"
        elif screen_index == BITLCD_MARQUEES_SCREEN:
            source_label = "BitLCD Marquee"
        else:
            source_label = "Base Component"
        queued_keys = {entry.spec.key for entry in self._queue_entries}
        for status in statuses:
            if status.spec.key not in selected_keys or status.status == "Installed" or status.spec.key in queued_keys:
                continue
            self._queue_entries.append(
                QueueEntry(spec=status.spec, source_label=source_label, target_path=str(target))
            )
            queued_keys.add(status.spec.key)
            added += 1
        if added:
            self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
            self._refresh_queue_table()
            self._save_settings()
            self.statusBar().showMessage(f"Queued {added} {source_label.lower()} item(s).")
        return added

    def _start_queue_install(self) -> None:
        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password in Settings before downloading.",
            )
            self._change_screen(SETTINGS_SCREEN)
            return

        self._queue_entries = self._prune_installed_queue_entries(self._queue_entries)
        self._refresh_queue_table()
        pending_entries = [entry for entry in self._queue_entries if entry.status != "Installed"]
        if not pending_entries:
            QMessageBox.information(self, "Queue empty", "Add one or more components to the queue first.")
            self._save_settings()
            return
        if not pending_entries[0].target_path.strip():
            QMessageBox.warning(self, "Missing target", "Choose a target folder in Settings before installing.")
            self._change_screen(SETTINGS_SCREEN)
            return
        batch_entries = self._next_queue_batch_entries(pending_entries)
        target = Path(batch_entries[0].target_path).expanduser()
        queue_specs = tuple(entry.spec for entry in batch_entries)

        self._save_settings()
        installer = Installer(queue_specs, max_parallel_downloads=self.parallel_downloads_spin.value())
        installer.cache_dir = self._downloads_dir()
        log_output = self._log_output_for_screen(QUEUE_SCREEN)
        self._controller = OperationController()
        self._active_operation_screen = QUEUE_SCREEN
        self._active_components.clear()
        self._set_action_buttons_enabled(False)
        self._set_queue_controls_enabled(False)
        self.progress_container.setVisible(True)
        self._set_transfer_controls_enabled(True)
        self._update_progress_controls_visibility()
        self.pause_button.setText("Pause")
        self.queue_pause_button.setText("Pause")
        self.progress_label.setText("Preparing install...")
        log_output.appendPlainText(f"Target: {target}")
        log_output.appendPlainText(f"Queue batch: {len(batch_entries)} item(s)")

        self._worker_thread = QThread(self)
        self._worker = InstallWorker(installer, target, credentials, self._controller)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.log.connect(log_output.appendPlainText)
        self._worker.component_status.connect(self._update_component_status)
        self._worker.progress.connect(self._update_progress)
        self._worker.cancelled.connect(self._install_cancelled)
        self._worker.error.connect(self._install_failed)
        self._worker.finished.connect(self._install_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.cancelled.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._clear_worker_refs)
        self._worker_thread.start()

    @staticmethod
    def _next_queue_batch_entries(pending_entries: list[QueueEntry]) -> list[QueueEntry]:
        if not pending_entries:
            return []
        target_path = pending_entries[0].target_path
        return [entry for entry in pending_entries if entry.target_path == target_path]

    def _toggle_pause(self) -> None:
        if self._controller is None:
            if self._queue_entries:
                self._start_queue_install()
            return
        if self._controller.is_paused:
            self._controller.resume()
            self.pause_button.setText("Pause")
            self.queue_pause_button.setText("Pause")
            self.progress_label.setText("Resuming transfer...")
        else:
            self._controller.pause()
            self.pause_button.setText("Resume")
            self.queue_pause_button.setText("Resume")
            self.progress_label.setText("Paused")

    def _cancel_install(self) -> None:
        if self._controller is None:
            return
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.progress_label.setText("Cancelling...")
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
            self.statusBar().showMessage(f"{spec.display_name}: {status}")

    def _update_progress(self, progress: InstallProgress) -> None:
        if progress.phase == "queued":
            self.progress_label.setText(f"{progress.detail} ({progress.overall_percent}% overall)")
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
        self.progress_label.setText(f"{progress.detail} ({progress.overall_percent}% overall)")

    def _install_finished(self, report: object) -> None:
        operation_label = self._screen_label(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        continue_queue = (
            self._active_operation_screen == QUEUE_SCREEN
            and any(entry.status != "Installed" for entry in self._queue_entries)
        )
        self._finish_install_ui()
        self.progress_label.setText("Install complete")
        cleanup_result = self._enforce_download_cache_policy()
        self._refresh_all_tables()
        self._refresh_queue_table()

        backup_text = ""
        backup_dir = getattr(report, "backup_dir", None)
        if backup_dir:
            backup_text = f"\nBackups stored in:\n{backup_dir}"
            log_output.appendPlainText(f"Backup directory: {backup_dir}")
        if cleanup_result.deleted_files:
            log_output.appendPlainText(
                f"Downloads cleanup removed {cleanup_result.deleted_files} file(s) from {self._downloads_dir()}."
            )

        if continue_queue and not self._closing:
            self._save_settings()
            self._start_queue_install()
            return

        if not self._closing:
            cleanup_text = ""
            if cleanup_result.deleted_files:
                cleanup_text = f"\nDownloads cleaned: {cleanup_result.deleted_files} file(s) removed."
            QMessageBox.information(
                self,
                "Install complete",
                f"{operation_label} installed successfully.{backup_text}{cleanup_text}",
            )
            self.progress_container.setVisible(False)
        self._save_settings()
        self._finalize_close_if_ready()

    def _install_cancelled(self, message: str) -> None:
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        self._finish_install_ui()
        self.progress_label.setText("Install cancelled")
        log_output.appendPlainText(message)
        self.statusBar().showMessage("Install cancelled")
        self._refresh_queue_table()
        if not self._closing:
            self.progress_container.setVisible(False)
        self._save_settings()
        self._finalize_close_if_ready()

    def _install_failed(self, message: str) -> None:
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        self._finish_install_ui()
        self.progress_label.setText("Install failed")
        log_output.appendPlainText(f"ERROR: {message}")
        self._refresh_queue_table()
        if not self._closing:
            QMessageBox.critical(self, "Install failed", message)
            self.progress_container.setVisible(False)
        self._save_settings()
        self._finalize_close_if_ready()

    def _finish_install_ui(self) -> None:
        self._active_components.clear()
        self._set_action_buttons_enabled(True)
        self._set_transfer_controls_enabled(False)
        self.pause_button.setText("Pause")
        self.queue_pause_button.setText("Pause")
        self._controller = None
        self._active_operation_screen = None
        self._set_queue_controls_enabled(True)
        self._update_progress_controls_visibility()

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self.validate_button.setEnabled(enabled)
        self.save_settings_button.setEnabled(enabled)
        self.clear_downloads_button.setEnabled(enabled)

    def _set_transfer_controls_enabled(self, enabled: bool) -> None:
        self.pause_button.setEnabled(enabled)
        self.cancel_button.setEnabled(enabled)

    def _update_progress_controls_visibility(self) -> None:
        hide_transfer_buttons = self.stack.currentIndex() == QUEUE_SCREEN or self._active_operation_screen == QUEUE_SCREEN
        self.pause_button.setVisible(not hide_transfer_buttons)
        self.cancel_button.setVisible(not hide_transfer_buttons)

    def _clear_worker_refs(self) -> None:
        self._worker = None
        self._worker_thread = None
        self._finalize_close_if_ready()

    def _validate_credentials_success(self, user: str) -> None:
        self._set_action_buttons_enabled(True)
        self._set_queue_controls_enabled(True)
        self._refresh_all_tables()
        self.statusBar().showMessage(f"Archive.org credentials validated for {user}")
        if not self._closing:
            QMessageBox.information(self, "Validation successful", f"Archive.org login succeeded for {user}.")
        self._finalize_close_if_ready()

    def _validate_credentials_error(self, message: str) -> None:
        self._set_action_buttons_enabled(True)
        self._set_queue_controls_enabled(True)
        self._refresh_all_tables()
        self.statusBar().showMessage("Archive.org credential validation failed")
        if not self._closing:
            QMessageBox.critical(self, "Validation failed", message)
        self._finalize_close_if_ready()

    def _clear_validate_refs(self) -> None:
        self._validate_worker = None
        self._validate_thread = None
        self._finalize_close_if_ready()

    def _target_dir(self) -> Path | None:
        raw = self.target_edit.text().strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    def _bitlcd_target_dir(self) -> Path | None:
        raw = self.bitlcd_target_edit.text().strip()
        if not raw:
            return None
        return Path(raw).expanduser()

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
        if screen_index not in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN}:
            return
        credentials = self._archive_credentials()
        for spec in self._components_for_screen(screen_index):
            if spec.key in self._remote_size_overrides:
                continue
            try:
                self._remote_size_overrides[spec.key] = self.archive_metadata.size_for_spec(spec, credentials)
            except Exception:
                self._remote_size_overrides[spec.key] = (spec.size_display, spec.size_bytes)

    def _component_size_display(self, spec: ComponentSpec) -> str:
        override = self._remote_size_overrides.get(spec.key)
        if override is None:
            return spec.size_display
        label, _ = override
        return label

    def _component_size_bytes(self, spec: ComponentSpec) -> int | None:
        override = self._remote_size_overrides.get(spec.key)
        if override is None:
            return spec.size_bytes
        _, size_bytes = override
        return size_bytes

    def _update_primary_action(self, screen_index: int, statuses: list) -> None:
        button = self._install_button_for_screen(screen_index)
        all_installed = bool(statuses) and all(status.status == "Installed" for status in statuses)
        button.setText("Up to Date" if all_installed else "Update")
        button.setEnabled(not all_installed)

    def _serialized_queue_entries(self) -> list[dict[str, str]]:
        serialized: list[dict[str, str]] = []
        for entry in self._queue_entries:
            if entry.status == "Installed":
                continue
            serialized.append(
                {
                    "component_key": entry.spec.key,
                    "source_label": entry.source_label,
                    "target_path": entry.target_path,
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
                    status="Queued",
                    percent=0.0,
                )
            )
        self._queue_entries = self._prune_installed_queue_entries(loaded_entries)
        self._refresh_queue_table()
        if self._queue_entries:
            self.statusBar().showMessage(f"Loaded {len(self._queue_entries)} queued item(s).")

    def _prune_installed_queue_entries(self, entries: list[QueueEntry]) -> list[QueueEntry]:
        if not entries:
            return []
        remaining: list[QueueEntry] = []
        status_cache: dict[tuple[str, str], dict[str, str]] = {}
        for entry in entries:
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
        if entry.source_label == "Game Pack":
            return self.game_packs_installer
        return self.base_installer

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._scan_timer.stop()
        self._save_settings()

        if self._controller is not None:
            self._controller.cancel()

        install_running = self._worker_thread is not None and self._worker_thread.isRunning()
        validation_running = self._validate_thread is not None and self._validate_thread.isRunning()

        if install_running or validation_running:
            self._close_after_workers = True
            self.statusBar().showMessage("Stopping background work...")
            event.ignore()
            return

        event.accept()

    def _finalize_close_if_ready(self) -> None:
        if not self._close_after_workers:
            return
        install_running = self._worker_thread is not None and self._worker_thread.isRunning()
        validation_running = self._validate_thread is not None and self._validate_thread.isRunning()
        if install_running or validation_running:
            return
        self._close_after_workers = False
        self.progress_container.setVisible(False)
        self.close()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_logo_pixmap()


class CheckBoxHeader(QHeaderView):
    toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self._checked = False
        self._syncing = False
        self._checkbox = QCheckBox(self.viewport())
        self._checkbox.setObjectName("headerSelector")
        self._checkbox.toggled.connect(self._on_checkbox_toggled)
        self.sectionResized.connect(lambda *_: self._position_checkbox())
        self.geometriesChanged.connect(self._position_checkbox)

    def set_checked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        self._syncing = True
        self._checkbox.setChecked(checked)
        self._syncing = False
        self._position_checkbox()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.logicalIndexAt(event.pos()) == 0:
            event.accept()
            return
        super().mousePressEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._position_checkbox()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_checkbox()

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self._checked = checked
        if self._syncing:
            return
        self.toggled.emit(checked)

    def _position_checkbox(self) -> None:
        if self.isSectionHidden(0):
            self._checkbox.hide()
            return
        x = self.sectionViewportPosition(0)
        width = self.sectionSize(0)
        if width <= 0:
            self._checkbox.hide()
            return
        size = self._checkbox.sizeHint()
        y = max(0, (self.height() - size.height()) // 2)
        left = x + max(0, (width - size.width()) // 2)
        self._checkbox.setGeometry(left, y, size.width(), size.height())
        self._checkbox.show()


class ComponentStatusCell(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)
        self._percent = 0.0

        self.label = QLabel("Pending")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        self.set_status("Pending", 0)

    def set_status(self, text: str, percent: float) -> None:
        clamped_percent = max(0.0, min(100.0, float(percent)))
        self._percent = clamped_percent
        active = text in {"Downloading", "Backing Up", "Installing"}

        self.label.setText(text)
        self.label.setVisible(not active)

        self.progress.setVisible(active)
        self.progress.setValue(int(round(clamped_percent)))
        self.progress.setFormat(f"{text} {clamped_percent:.1f}%")

    def percent(self) -> float:
        return self._percent


def _game_name_candidates(rom_name: str) -> tuple[str, ...]:
    path = Path(rom_name)
    candidates: list[str] = []
    current = path.name
    while current:
        if current not in candidates:
            candidates.append(current)
        stem = Path(current).stem
        if stem == current:
            break
        current = stem
    return tuple(candidates)


def _find_matching_media_file(directory: Path, base_names: tuple[str, ...]) -> Path | None:
    if not directory.exists() or not directory.is_dir():
        return None
    candidate_keys = {name.casefold() for name in base_names}
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        current = path.name.casefold()
        current_stem = path.stem.casefold()
        if current in candidate_keys or current_stem in candidate_keys:
            return path
        nested_stem = current_stem
        while True:
            reduced = Path(nested_stem).stem.casefold()
            if reduced == nested_stem:
                break
            if reduced in candidate_keys:
                return path
            nested_stem = reduced
    return None


def _read_story_text(story_path: Path | None) -> str:
    if story_path is None or not story_path.exists():
        return "No story file found."
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return story_path.read_text(encoding=encoding).strip() or "Story file is empty."
        except UnicodeDecodeError:
            continue
        except OSError:
            return "Unable to read the story file."
    return "Unable to decode the story file."


def _resolve_game_media_root(
    target_dir: Path | None,
    entry: GameManifestEntry,
    base_names: tuple[str, ...],
) -> Path | None:
    if target_dir is None:
        return None
    candidate_roots: list[Path] = _candidate_game_media_roots(target_dir, entry)

    best_root = None
    best_score = -1

    for media_root in candidate_roots:
        score = _score_game_media_root(media_root, base_names)
        if score > best_score:
            best_score = score
            best_root = media_root

    if best_score > 0:
        return best_root

    for media_root in _all_game_media_roots(target_dir):
        score = _score_game_media_root(media_root, base_names)
        if score > best_score:
            best_score = score
            best_root = media_root

    return best_root if best_score > 0 else None


def _candidate_game_media_roots(target_dir: Path, entry: GameManifestEntry) -> list[Path]:
    candidate_roots: list[Path] = []
    for collections_root in _game_media_search_roots(target_dir):
        direct_root = collections_root / entry.game_pack / "medium_artwork"
        if direct_root.exists() and direct_root not in candidate_roots:
            candidate_roots.append(direct_root)

    installed_collection = _find_installed_collection_root(target_dir, entry)
    if installed_collection is not None and installed_collection not in candidate_roots:
        candidate_roots.insert(0, installed_collection)

    return candidate_roots


def _game_media_search_roots(target_dir: Path) -> tuple[Path, ...]:
    return (
        target_dir / "content" / "retrofe" / "collections",
        target_dir / "base_assets" / "collections",
    )


def _all_game_media_roots(target_dir: Path) -> list[Path]:
    media_roots: list[Path] = []
    for collections_root in _game_media_search_roots(target_dir):
        if not collections_root.exists():
            continue
        for collection_dir in sorted(collections_root.iterdir(), key=lambda path: path.name.casefold()):
            if not collection_dir.is_dir():
                continue
            media_root = collection_dir / "medium_artwork"
            if media_root.exists() and media_root not in media_roots:
                media_roots.append(media_root)
    return media_roots


def _find_installed_collection_root(target_dir: Path, entry: GameManifestEntry) -> Path | None:
    collections_root = target_dir / "content" / "retrofe" / "collections"
    if not collections_root.exists():
        return None
    for collection_dir in collections_root.iterdir():
        if not collection_dir.is_dir():
            continue
        if (collection_dir / "roms" / entry.rom_path).exists():
            media_root = collection_dir / "medium_artwork"
            if media_root.exists():
                return media_root
            fallback_root = target_dir / "base_assets" / "collections" / collection_dir.name / "medium_artwork"
            if fallback_root.exists():
                return fallback_root
    return None


def _score_game_media_root(media_root: Path, base_names: tuple[str, ...]) -> int:
    if not media_root.exists() or not media_root.is_dir():
        return -1
    score = 0
    for folder_name in (*GAME_PRIMARY_ART_FOLDERS, "logo", "story", *GAME_DETAIL_MEDIA_FOLDERS):
        if _find_matching_media_file(media_root / folder_name, base_names) is not None:
            score += 1
    return score


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


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"

