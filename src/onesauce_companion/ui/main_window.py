from __future__ import annotations

import ctypes
from dataclasses import dataclass, replace
from datetime import datetime
import math
import random
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QDesktopServices, QFont, QFontDatabase, QFontMetricsF, QIcon, QImage, QIntValidator, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRawFont, QResizeEvent, QSyntaxHighlighter, QTextCharFormat, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QGraphicsOpacityEffect,
    QHeaderView,
    QCheckBox,
    QScrollArea,
    QSlider,
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

from onesauce_companion.manifest import BITLCD_MARQUEES, GAME_PACKS, OPTIONAL_COMPONENTS, REQUIRED_COMPONENTS
from onesauce_companion import __version__
from onesauce_companion.models import ComponentSpec, InstallProgress, QueueEntry
from onesauce_companion.services.archive_metadata import ArchiveMetadataService
from onesauce_companion.services.archive_org import ArchiveOrgCredentials
from onesauce_companion.services.app_logging import LOG_FILE_NAME
from onesauce_companion.services.collection_catalog import (
    CollectionCatalogEntry,
    build_collection_catalog,
    collection_directory_candidates,
    read_collection_info_attributes,
)
from onesauce_companion.services.collections import scan_collection_definitions
from onesauce_companion.services.component_catalogs import (
    ArchiveBackedComponentCatalog,
    build_bitlcd_component_specs,
    build_optional_component_specs,
    build_required_component_specs,
)
from onesauce_companion.services.control import OperationController
from onesauce_companion.services.download_cache import (
    clear_downloads_dir,
    default_downloads_dir,
    enforce_download_cache_policy,
)
from onesauce_companion.services.games import (
    GameManifestEntry,
    available_collections,
    build_collection_game_catalog,
    is_excluded_game,
    load_game_manifest,
    scan_excluded_games,
    scan_installed_games,
)
from onesauce_companion.services.github_releases import RELEASES_PAGE_URL
from onesauce_companion.services.hyperlist_metadata import lookup_hyperlist_metadata
from onesauce_companion.services.installer import Installer
from onesauce_companion.services.settings import AppSettings, SettingsStore
from onesauce_companion.services.system_packs import SystemPackCatalogService
from onesauce_companion.services.themes import ThemeCatalogEntry, ThemeLayoutPreview, ThemePreviewElement, _read_settings_conf, build_theme_layout_preview, scan_theme_catalog
from onesauce_companion.services.tweaks import (
    AUTOSTART_STATUS_ENABLED,
    AUTOSTART_STATUS_NOT_ENABLED,
    AUTOSTART_STATUS_PENDING,
    detect_autostart_state,
    detect_onesauce_settings_state,
    detect_settings_tweaks_state,
    disable_autostart,
    enable_autostart,
    enable_legends_pinball_micro_rotation_fix,
    install_autostart_fix,
    update_onesauce_setting,
)
from onesauce_companion.ui.workers import InstallWorker, ReleaseCheckWorker, ValidateCredentialsWorker
from shiboken6 import isValid

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_QT_MULTIMEDIA = True
except ImportError:  # pragma: no cover - optional runtime dependency in some environments
    QAudioOutput = None
    QMediaPlayer = None
    QVideoFrame = None
    QVideoSink = None
    QVideoWidget = None
    HAS_QT_MULTIMEDIA = False


APP_VERSION = f"v{__version__}"
SETTINGS_SCREEN = 0
BASE_COMPONENTS_SCREEN = 1
GAME_PACKS_SCREEN = 2
BITLCD_MARQUEES_SCREEN = 3
OPTIONAL_COMPONENTS_SCREEN = 4
QUEUE_SCREEN = 5
GAMES_SCREEN = 6
COLLECTIONS_SCREEN = 7
TWEAKS_SCREEN = 8
LOGS_SCREEN = 9
THEMES_SCREEN = 10

BASE_TABLE_COLUMNS = {
    "select": 0,
    "component": 1,
    "installed": 2,
    "available": 3,
    "size": 4,
    "status": 5,
}

OPTIONAL_TABLE_COLUMNS = {
    "select": 0,
    "component": 1,
    "type": 2,
    "installed": 3,
    "available": 4,
    "size": 5,
    "status": 6,
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
    "index": 0,
    "game_name": 1,
    "collection": 2,
    "status": 3,
}

COLLECTIONS_TABLE_COLUMNS = {
    "index": 0,
    "collection_name": 1,
    "parent_collections": 2,
    "game_count": 3,
}

GAME_PRIMARY_ART_FOLDERS = ("artwork_3d", "artwork_front", "artwork_front_s")
GAME_DETAIL_MEDIA_FOLDERS = ("screenshot", "screentitle", "video")
IMAGE_MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_MEDIA_SUFFIXES = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
STORY_MEDIA_SUFFIXES = {".txt"}

_BITLCD_MEDIA_INDEX: dict[str, dict[str, Path]] = {}
_VIDEO_THUMBNAIL_CACHE: dict[tuple[str, int], QPixmap] = {}

DEFAULT_LOG_HIGHLIGHT_COLORS = {
    "timestamp": "#c792ea",
    "info": "#8ad4ff",
    "debug": "#7ed0c3",
    "warning": "#f2c14e",
    "error": "#ff7d7d",
    "bracket": "#7fb3ff",
    "path": "#b6d78c",
}

LOG_HIGHLIGHT_LABELS = (
    ("timestamp", "Timestamps and Dates"),
    ("info", "Info"),
    ("debug", "Debug"),
    ("warning", "Warning"),
    ("error", "Error / Exception"),
    ("bracket", "Other Bracketed Text"),
    ("path", "Paths"),
)


@dataclass(frozen=True)
class ThemePreviewRenderData:
    pixmap: QPixmap | None = None
    text: str | None = None
    accent_text: str | None = None
    video_path: Path | None = None


@dataclass
class ThemePreviewVideoSession:
    element: ThemePreviewElement
    video_path: Path
    player: Any
    audio_output: Any
    video_sink: Any
    initial_seek_done: bool = False


class LogSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document, color_map: dict[str, str] | None = None) -> None:
        super().__init__(document)
        self._color_map = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
        if color_map:
            self._color_map.update(color_map)
        self._formats: list[tuple[str, QTextCharFormat]] = []
        self._rebuild_formats()

    def set_color_map(self, color_map: dict[str, str]) -> None:
        self._color_map = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
        self._color_map.update(color_map)
        self._rebuild_formats()
        self.rehighlight()

    def _rebuild_formats(self) -> None:
        self._formats.clear()

        timestamp_format = QTextCharFormat()
        timestamp_format.setForeground(QColor(self._color_map["timestamp"]))
        self._formats.append((r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\b", timestamp_format))
        self._formats.append((r"\b\d{2}/\d{2}/\d{4}(?: \d{2}:\d{2}:\d{2})?\b", timestamp_format))
        self._formats.append((r"\b\d{2}-\d{2}-\d{4}(?: \d{2}:\d{2}:\d{2})?\b", timestamp_format))
        self._formats.append((r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2} \d{4}\b", timestamp_format))
        self._formats.append((r"\[\d{2}:\d{2}:\d{2}\]", timestamp_format))
        self._formats.append((r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\]", timestamp_format))
        self._formats.append((r"\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2} \d{4}\]", timestamp_format))
        self._formats.append((r"\b\d{4}-\d{2}-\d{2}\b", timestamp_format))
        self._formats.append((r"\b\d{2}/\d{2}/\d{4}\b", timestamp_format))
        self._formats.append((r"\b\d{2}-\d{2}-\d{4}\b", timestamp_format))

        info_format = QTextCharFormat()
        info_format.setForeground(QColor(self._color_map["info"]))
        info_format.setFontWeight(QFont.Weight.DemiBold)
        self._formats.append((r"\bINFO\b|\bInfo\b|\[info\]|\[INFO\]", info_format))

        debug_format = QTextCharFormat()
        debug_format.setForeground(QColor(self._color_map["debug"]))
        debug_format.setFontWeight(QFont.Weight.DemiBold)
        self._formats.append((r"\bDEBUG\b|\bDebug\b|\[debug\]|\[DEBUG\]", debug_format))

        warning_format = QTextCharFormat()
        warning_format.setForeground(QColor(self._color_map["warning"]))
        warning_format.setFontWeight(QFont.Weight.Bold)
        self._formats.append((r"\bWARNING\b|\bWARN\b|\bWarning\b|\bWarn\b|\[warning\]|\[warn\]|\[WARNING\]|\[WARN\]", warning_format))

        error_format = QTextCharFormat()
        error_format.setForeground(QColor(self._color_map["error"]))
        error_format.setFontWeight(QFont.Weight.Bold)
        self._formats.append(
            (
                r"\bERROR\b|\bCRITICAL\b|\bFATAL\b|\bError\b|\bCritical\b|\bFatal\b|\[error\]|\[critical\]|\[fatal\]|\[ERROR\]|\[CRITICAL\]|\[FATAL\]|\bTraceback\b|\bException\b",
                error_format,
            )
        )

        bracket_format = QTextCharFormat()
        bracket_format.setForeground(QColor(self._color_map["bracket"]))
        self._formats.append(
            (
                r"\[(?!(?:\d{2}:\d{2}:\d{2}\]|"
                r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\]|"
                r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [ \d]\d \d{2}:\d{2}:\d{2} \d{4}\]|"
                r"(?i:info|debug|warning|warn|error|critical|fatal)\]))[^\]\r\n]+\]",
                bracket_format,
            )
        )

        path_format = QTextCharFormat()
        path_format.setForeground(QColor(self._color_map["path"]))
        self._formats.append((r"[A-Za-z]:\\[^\s]+", path_format))
        self._formats.append(
            (
                r"(?:[A-Za-z]:\\|\.{1,2}[\\/]|[\\/])(?:[^\\/\r\n]+(?: [^\\/\r\n]+)*[\\/])*[^\\/\r\n]+(?: [^\\/\r\n]+)*",
                path_format,
            )
        )

    def highlightBlock(self, text: str) -> None:  # type: ignore[override]
        for pattern, text_format in self._formats:
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), text_format)


class LogColorDialog(QDialog):
    def __init__(self, color_map: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Log Colors")
        self._color_map = dict(color_map)
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for row, (key, label_text) in enumerate(LOG_HIGHLIGHT_LABELS):
            label = QLabel(label_text)
            button = QPushButton(self._color_map[key])
            button.setMinimumWidth(110)
            button.clicked.connect(lambda _checked=False, color_key=key: self._choose_color(color_key))
            self._buttons[key] = button
            self._sync_color_button(color_key=key)
            grid.addWidget(label, row, 0)
            grid.addWidget(button, row, 1)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.accept)
        actions.addWidget(cancel_button)
        actions.addWidget(save_button)
        layout.addLayout(actions)

    def color_map(self) -> dict[str, str]:
        return dict(self._color_map)

    def _choose_color(self, color_key: str) -> None:
        selected = QColorDialog.getColor(QColor(self._color_map[color_key]), self, "Choose Log Highlight Color")
        if not selected.isValid():
            return
        self._color_map[color_key] = selected.name()
        self._sync_color_button(color_key)

    def _sync_color_button(self, color_key: str) -> None:
        button = self._buttons[color_key]
        color_value = self._color_map[color_key]
        button.setText(color_value.upper())
        button.setStyleSheet(
            f"background: {color_value}; color: {'#1f1f1f' if QColor(color_value).lightnessF() > 0.6 else '#ffffff'};"
        )


class ScaledImageLabel(QLabel):
    _active_expanded_label: "ScaledImageLabel | None" = None
    _window_filter_target: QWidget | None = None
    _app_filter_target: QApplication | None = None
    _floating_preview: QLabel | None = None
    folderRequested = Signal()
    uploadRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, max_height: int, minimum_width: int = 220) -> None:
        super().__init__()
        self._pixmap = QPixmap()
        self._max_height = max_height
        self._action_strip_height = 30
        self._action_padding = 6
        self._action_gap = 6
        self._action_button_size = 20
        self._action_icon_size = 18
        self._expanded = False
        self._window_filter_target: QWidget | None = None
        self._app_filter_target: QApplication | None = None
        self._floating_preview: QLabel | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setContentsMargins(0, 0, 0, self._action_strip_height)
        self.setMinimumHeight(max_height)
        self.setMaximumHeight(max_height)
        self.setMinimumWidth(minimum_width)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._folder_button = QPushButton(self)
        self._folder_button.setObjectName("videoControlButton")
        self._folder_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._folder_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._folder_button.setIcon(QIcon(str(_assets_dir() / "folder-white.svg")))
        self._folder_button.clicked.connect(self.folderRequested.emit)
        self._folder_button.hide()

        self._upload_button = QPushButton(self)
        self._upload_button.setObjectName("videoControlButton")
        self._upload_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._upload_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._upload_button.setIcon(QIcon(str(_assets_dir() / "upload-white.svg")))
        self._upload_button.clicked.connect(self.uploadRequested.emit)
        self._upload_button.hide()

        self._delete_button = QPushButton(self)
        self._delete_button.setObjectName("videoControlButton")
        self._delete_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._delete_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._delete_button.setIcon(QIcon(str(_assets_dir() / "delete-white.svg")))
        self._delete_button.clicked.connect(self.deleteRequested.emit)
        self._delete_button.hide()

        self._expand_button = QPushButton(self)
        self._expand_button.setObjectName("videoControlButton")
        self._expand_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._expand_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._expand_button.clicked.connect(self._toggle_expanded)
        self._expand_button.hide()
        self._sync_expand_button()

    def set_image(self, image_path: Path | None, placeholder: str) -> None:
        if self._expanded:
            self._set_expanded(False)
        if image_path is None or not image_path.exists():
            self._pixmap = QPixmap()
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setPixmap(QPixmap())
            self.setText(placeholder)
            self._expand_button.hide()
            self._position_action_buttons()
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._pixmap = QPixmap()
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setPixmap(QPixmap())
            self.setText(placeholder)
            self._expand_button.hide()
            self._position_action_buttons()
            return
        self._pixmap = pixmap
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setText("")
        self._expand_button.show()
        self._sync_expand_button()
        self._apply_scaled_pixmap()
        self._position_action_buttons()
        self._position_expand_button()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_scaled_pixmap()
        self._position_action_buttons()
        self._position_expand_button()
        if self._expanded:
            self._update_floating_preview()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._attach_window_filter()
        self._position_action_buttons()
        self._position_expand_button()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        window_filter_target = getattr(self, "_window_filter_target", None)
        app_filter_target = getattr(self, "_app_filter_target", None)
        expanded = bool(getattr(self, "_expanded", False))
        if watched == window_filter_target and expanded and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            self._update_floating_preview()
        elif expanded and app_filter_target is not None and event.type() == QEvent.Type.MouseButtonPress:
            self._handle_global_mouse_press(event)
        return super().eventFilter(watched, event)

    def _apply_scaled_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        available_height = max(1, self._max_height - self._action_strip_height)
        scaled = self._pixmap.scaled(
            max(1, self.width()),
            available_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


    def set_action_buttons_enabled(self, folder_enabled: bool, upload_enabled: bool, delete_enabled: bool) -> None:
        self._folder_button.setEnabled(folder_enabled)
        self._upload_button.setEnabled(upload_enabled)
        self._delete_button.setEnabled(delete_enabled)
        self._set_action_buttons_visible(folder_enabled, upload_enabled, delete_enabled)

    def _set_action_buttons_visible(self, folder_visible: bool, upload_visible: bool, delete_visible: bool) -> None:
        self._folder_button.setVisible(folder_visible)
        self._upload_button.setVisible(upload_visible)
        self._delete_button.setVisible(delete_visible)
        self._position_action_buttons()

    def _position_action_buttons(self) -> None:
        y_pos = max(0, self.height() - self._action_padding - self._folder_button.height())
        x_pos = self._action_padding
        for widget in (self._folder_button, self._upload_button, self._delete_button):
            if not widget.isVisible():
                continue
            widget.move(x_pos, y_pos)
            widget.raise_()
            x_pos += widget.width() + self._action_gap

    def _position_expand_button(self) -> None:
        if not self._expand_button.isVisible():
            return
        x_pos = max(0, self.width() - self._expand_button.width() - self._action_padding)
        y_pos = max(0, self.height() - self._expand_button.height() - self._action_padding)
        self._expand_button.move(x_pos, y_pos)
        self._expand_button.raise_()

    def _attach_window_filter(self) -> None:
        window = self.window()
        if not isinstance(window, QWidget) or window is self._window_filter_target:
            return
        if self._window_filter_target is not None:
            self._window_filter_target.removeEventFilter(self)
        self._window_filter_target = window
        self._window_filter_target.installEventFilter(self)

    def _attach_app_filter(self) -> None:
        app = QApplication.instance()
        if app is None or app is self._app_filter_target:
            return
        if self._app_filter_target is not None:
            self._app_filter_target.removeEventFilter(self)
        self._app_filter_target = app
        self._app_filter_target.installEventFilter(self)

    def _detach_app_filter(self) -> None:
        if self._app_filter_target is not None:
            self._app_filter_target.removeEventFilter(self)
            self._app_filter_target = None

    def _handle_global_mouse_press(self, event) -> None:
        if self._floating_preview is None:
            return
        if not hasattr(event, "globalPosition"):
            return
        global_pos = event.globalPosition().toPoint()
        preview_pos = self._floating_preview.mapFromGlobal(global_pos)
        if self._floating_preview.rect().contains(preview_pos):
            return
        for widget in (self._folder_button, self._upload_button, self._delete_button, self._expand_button):
            if not widget.isVisible():
                continue
            widget_pos = widget.mapFromGlobal(global_pos)
            if widget.rect().contains(widget_pos):
                return
        self._set_expanded(False)

    def _toggle_expanded(self) -> None:
        if self._pixmap.isNull():
            return
        self._set_expanded(not self._expanded)

    def _set_expanded(self, expanded: bool) -> None:
        if expanded:
            active = ScaledImageLabel._active_expanded_label
            if active is not None and active is not self:
                active._set_expanded(False)
            window = self.window()
            collapse_video = getattr(window, "_collapse_expanded_video", None)
            if callable(collapse_video):
                collapse_video()
            ScaledImageLabel._active_expanded_label = self
        elif ScaledImageLabel._active_expanded_label is self:
            ScaledImageLabel._active_expanded_label = None
        self._expanded = expanded
        self._sync_expand_button()
        if not expanded:
            self._detach_app_filter()
            if not self._pixmap.isNull():
                self._expand_button.show()
                self._position_expand_button()
            if self._floating_preview is not None:
                self._floating_preview.hide()
            return
        self._expand_button.hide()
        self._attach_window_filter()
        self._attach_app_filter()
        if self._window_filter_target is None:
            return
        if self._floating_preview is None:
            self._floating_preview = QLabel(self._window_filter_target)
            self._floating_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._floating_preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._floating_preview.setStyleSheet("background: #000000; border: 1px solid #444444;")
        self._floating_preview.show()
        self._floating_preview.raise_()
        self._update_floating_preview()

    def _sync_expand_button(self) -> None:
        self._expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))

    def _update_floating_preview(self) -> None:
        if self._floating_preview is None or self._window_filter_target is None or self._pixmap.isNull():
            return
        anchor = self.mapTo(self._window_filter_target, self.rect().bottomRight())
        base_size = self.pixmap().size() if self.pixmap() is not None else QSize(self.width(), self.height())
        base_width = max(220, base_size.width())
        base_height = max(180, base_size.height())
        target_width = min(self._window_filter_target.width() - 24, base_width * 3)
        target_height = min(self._window_filter_target.height() - 24, base_height * 3)
        scaled = self._pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_pos = max(12, anchor.x() - scaled.width() + 1)
        y_pos = max(12, anchor.y() - scaled.height() + 1)
        self._floating_preview.setPixmap(scaled)
        self._floating_preview.setGeometry(x_pos, y_pos, scaled.width(), scaled.height())


class OverlaySurface(QWidget):
    entered = Signal()
    left = Signal()
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

    def enterEvent(self, event) -> None:  # type: ignore[override]
        super().enterEvent(event)
        self.entered.emit()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        super().leaveEvent(event)
        self.left.emit()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class VideoOverlayContainer(QWidget):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._content_widget: QWidget | None = None
        self._hovered = False
        self._has_video = False
        self._is_playing = False
        self._play_icon = QPixmap(str(_assets_dir() / "play-button-white.svg"))
        self._pause_icon = QPixmap(str(_assets_dir() / "pause-white.svg"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.interaction_overlay = OverlaySurface(self)
        self.interaction_overlay.entered.connect(self._handle_overlay_enter)
        self.interaction_overlay.left.connect(self._handle_overlay_leave)
        self.interaction_overlay.clicked.connect(self._handle_overlay_click)

        self.overlay_label = QLabel(self.interaction_overlay)
        self.overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.overlay_opacity = QGraphicsOpacityEffect(self.overlay_label)
        self.overlay_opacity.setOpacity(0.0)
        self.overlay_label.setGraphicsEffect(self.overlay_opacity)
        self.overlay_animation = QPropertyAnimation(self.overlay_opacity, b"opacity", self)
        self.overlay_animation.setDuration(160)
        self.overlay_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.overlay_animation.finished.connect(self._finalize_overlay_animation)
        self.overlay_label.hide()

    def set_content_widget(self, widget: QWidget) -> None:
        self.layout().addWidget(widget)
        self._content_widget = widget
        self._reposition_overlay()

    def set_video_state(self, has_video: bool, is_playing: bool) -> None:
        self._has_video = has_video
        self._is_playing = is_playing
        self._update_overlay()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_overlay()
        self._update_overlay()

    def _handle_overlay_enter(self) -> None:
        self._hovered = True
        self._update_overlay()

    def _handle_overlay_leave(self) -> None:
        self._hovered = False
        self._update_overlay()

    def _handle_overlay_click(self) -> None:
        if self._has_video:
            self.clicked.emit()

    def _update_overlay(self) -> None:
        should_show = self._hovered and self._has_video
        if not should_show:
            self._fade_overlay(False)
            return
        base_pixmap = self._pause_icon if self._is_playing else self._play_icon
        if base_pixmap.isNull():
            self._fade_overlay(False)
            return
        target_width = max(48, self.width() // 3)
        target_height = max(48, self.height() // 3)
        scaled = base_pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.overlay_label.setPixmap(scaled)
        self.overlay_label.setFixedSize(scaled.size())
        self._reposition_overlay()
        self._fade_overlay(True)

    def _fade_overlay(self, visible: bool) -> None:
        self.overlay_animation.stop()
        current_opacity = self.overlay_opacity.opacity()
        target_opacity = 1.0 if visible else 0.0
        if visible:
            self.interaction_overlay.raise_()
            self.overlay_label.show()
            self.overlay_label.raise_()
        if abs(current_opacity - target_opacity) < 0.01:
            self.overlay_opacity.setOpacity(target_opacity)
            if not visible:
                self.overlay_label.hide()
            return
        self.overlay_animation.setStartValue(current_opacity)
        self.overlay_animation.setEndValue(target_opacity)
        self.overlay_animation.start()

    def _finalize_overlay_animation(self) -> None:
        if self.overlay_opacity.opacity() <= 0.01:
            self.overlay_label.hide()

    def _reposition_overlay(self) -> None:
        self.interaction_overlay.setGeometry(self.rect())
        self.interaction_overlay.raise_()
        pixmap = self.overlay_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        x_pos = max(0, (self.interaction_overlay.width() - self.overlay_label.width()) // 2)
        y_pos = max(0, (self.interaction_overlay.height() - self.overlay_label.height()) // 2)
        self.overlay_label.move(x_pos, y_pos)
        self.overlay_label.raise_()


class GameDetailsDialog(QDialog):
    def __init__(
        self,
        entry: GameManifestEntry,
        installed: bool,
        target_dir: Path | None,
        bitlcd_target_dir: Path | None,
        navigation_entries: list[GameManifestEntry] | None = None,
        navigation_index: int | None = None,
        installed_keys: set[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.installed = installed
        self.target_dir = target_dir
        self.bitlcd_target_dir = bitlcd_target_dir
        self._navigation_entries = list(navigation_entries or [entry])
        self._navigation_index = navigation_index if navigation_index is not None else 0
        self._installed_keys = set(installed_keys or set())
        self._media_player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
        self._video_widget: QVideoWidget | QLabel | None = None
        self._video_poster_label: QLabel | None = None
        self._video_host: QWidget | None = None
        self._video_host_layout: QVBoxLayout | None = None
        self._video_floating_container: QWidget | None = None
        self._video_floating_layout: QVBoxLayout | None = None
        self._video_play_button: QPushButton | None = None
        self._video_volume_button: QPushButton | None = None
        self._video_expand_button: QPushButton | None = None
        self._video_position_slider: QSlider | None = None
        self._video_folder_button: QPushButton | None = None
        self._video_upload_button: QPushButton | None = None
        self._video_delete_button: QPushButton | None = None
        self._video_time_label: QLabel | None = None
        self._video_duration_ms = 0
        self._video_slider_pressed = False
        self._video_expanded = False
        self._video_app_filter_target: QApplication | None = None
        self._video_current_path: Path | None = None
        self._media_base_names: tuple[str, ...] = ()
        self._media_contexts: dict[str, tuple[Path | None, Path | None]] = {}
        self._navigation_loading = False

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
        self.front_art_label = ScaledImageLabel(180, minimum_width=220)
        self.bezel_label = ScaledImageLabel(180, minimum_width=220)
        self.screentitle_label = ScaledImageLabel(180, minimum_width=220)
        self.screenshot_label = ScaledImageLabel(180, minimum_width=220)
        top_row.addWidget(self._build_media_group("Front Artwork", self.front_art_label), stretch=1)
        top_row.addWidget(self._build_media_group("Bezel", self.bezel_label), stretch=1)
        top_row.addWidget(self._build_media_group("Screen Title", self.screentitle_label), stretch=1)
        top_row.addWidget(self._build_media_group("Screenshot", self.screenshot_label), stretch=1)
        root.addLayout(top_row)

        content_grid = QGridLayout()
        content_grid.setHorizontalSpacing(16)
        content_grid.setVerticalSpacing(12)
        content_grid.setColumnStretch(0, 1)
        content_grid.setColumnStretch(1, 1)
        content_grid.setColumnStretch(2, 1)
        content_grid.setColumnStretch(3, 1)

        details_group = QGroupBox("Game Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(8)
        self.game_name_label = QLabel()
        self.collection_label = QLabel()
        self.collection_label.setTextFormat(Qt.TextFormat.RichText)
        self.collection_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.collection_label.setOpenExternalLinks(False)
        self.collection_label.linkActivated.connect(self._open_collection_for_current_game)
        self.subcollections_label = QLabel()
        self.source_pack_label = QLabel()
        self.status_label = QLabel()
        details_layout.addWidget(self.game_name_label)
        details_layout.addWidget(self.collection_label)
        details_layout.addWidget(self.subcollections_label)
        details_layout.addWidget(self.source_pack_label)
        details_layout.addWidget(self.status_label)
        self.story_text = QTextEdit()
        self.story_text.setReadOnly(True)
        self.story_text.setMinimumHeight(420)
        details_layout.addWidget(self.story_text, stretch=1)
        navigation_row = QHBoxLayout()
        navigation_row.setSpacing(10)
        self.navigation_position_label = QLabel("Game 1/1")
        navigation_row.addWidget(self.navigation_position_label)
        navigation_row.addStretch(1)
        self.previous_game_button = QPushButton("Previous")
        self.previous_game_button.setMinimumWidth(140)
        self.previous_game_button.clicked.connect(self._show_previous_game)
        self.next_game_button = QPushButton("Next")
        self.next_game_button.setMinimumWidth(140)
        self.next_game_button.clicked.connect(self._show_next_game)
        self.random_game_button = QPushButton("Random")
        self.random_game_button.setMinimumWidth(140)
        self.random_game_button.clicked.connect(self._show_random_game)
        navigation_row.addWidget(self.previous_game_button)
        navigation_row.addWidget(self.next_game_button)
        navigation_row.addWidget(self.random_game_button)
        details_layout.addLayout(navigation_row)
        content_grid.addWidget(details_group, 0, 0, 1, 3)

        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)

        self.logo_label = ScaledImageLabel(110, minimum_width=220)
        self.led_marquee_label = ScaledImageLabel(110, minimum_width=220)
        self.lcd_marquee_label = ScaledImageLabel(110, minimum_width=220)
        side_layout.addWidget(self._build_media_group("Logo", self.logo_label))
        side_layout.addWidget(self._build_media_group("LED Marquee", self.led_marquee_label))
        side_layout.addWidget(self._build_media_group("LCD Marquee", self.lcd_marquee_label))
        side_layout.addWidget(self._build_video_group(), stretch=1)
        content_grid.addWidget(side_panel, 0, 3)

        root.addLayout(content_grid, stretch=1)

        self._update_navigation_buttons()
        self._refresh_entry_view()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._video_expanded:
            self._set_video_expanded(False)
        if self._media_player is not None:
            self._media_player.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._video_expanded:
            self._update_expanded_video_geometry()

    def _refresh_entry_view(self) -> None:
        self._update_metadata_labels()
        self._populate()
        self._update_navigation_buttons()

    def _update_metadata_labels(self) -> None:
        self.setWindowTitle(self.entry.game_name)
        self.game_name_label.setText(f"Game Name: {self.entry.game_name}")
        self.collection_label.setText(f'Collection: <a href="{self.entry.collection_name}">{self.entry.collection_name}</a>')
        subcollections_visible = bool(self.entry.subcollections)
        self.subcollections_label.setVisible(subcollections_visible)
        if subcollections_visible:
            self.subcollections_label.setText(f"Sub-Collections: {', '.join(self.entry.subcollections)}")
        else:
            self.subcollections_label.clear()
        source_pack_visible = bool(self.entry.source_pack and self.entry.source_pack != self.entry.collection_name)
        self.source_pack_label.setVisible(source_pack_visible)
        if source_pack_visible:
            self.source_pack_label.setText(f"Source Pack: {self.entry.source_pack}")
        else:
            self.source_pack_label.clear()
        self.status_label.setText(f"Status: {'Installed' if self.installed else 'Not Installed'}")

    def _update_navigation_buttons(self) -> None:
        total_games = len(self._navigation_entries)
        has_navigation = total_games > 1
        self.navigation_position_label.setText(f"Game {self._navigation_index + 1}/{max(1, total_games)}")
        self.previous_game_button.setVisible(has_navigation)
        self.next_game_button.setVisible(has_navigation)
        self.random_game_button.setVisible(total_games > 0)
        if self._navigation_loading:
            self.previous_game_button.setEnabled(False)
            self.next_game_button.setEnabled(False)
            self.random_game_button.setEnabled(False)
            return
        self.previous_game_button.setEnabled(has_navigation and self._navigation_index > 0)
        self.next_game_button.setEnabled(has_navigation and self._navigation_index < total_games - 1)
        installed_candidates = sum(1 for entry in self._navigation_entries if entry.installed_key in self._installed_keys)
        self.random_game_button.setEnabled(installed_candidates > 1 or (installed_candidates == 1 and self._navigation_entries[self._navigation_index].installed_key not in self._installed_keys))

    def _open_collection_for_current_game(self, collection_name: str) -> None:
        parent = self.parent()
        open_collection = getattr(parent, "_open_collection_details_by_name", None)
        if callable(open_collection):
            open_collection(collection_name)

    def _load_navigation_entry(self, index: int) -> None:
        if index < 0 or index >= len(self._navigation_entries) or index == self._navigation_index:
            return
        self._navigation_loading = True
        self._update_navigation_buttons()
        QApplication.processEvents()
        try:
            if self._video_expanded:
                self._set_video_expanded(False)
            active = ScaledImageLabel._active_expanded_label
            if active is not None and active.window() is self:
                active._set_expanded(False)
            self._navigation_index = index
            self.entry = self._navigation_entries[index]
            self.installed = self.entry.installed_key in self._installed_keys
            self._refresh_entry_view()
        finally:
            self._navigation_loading = False
            self._update_navigation_buttons()

    def _show_previous_game(self) -> None:
        self._load_navigation_entry(self._navigation_index - 1)

    def _show_next_game(self) -> None:
        self._load_navigation_entry(self._navigation_index + 1)

    def _show_random_game(self) -> None:
        candidates = [
            index
            for index, entry in enumerate(self._navigation_entries)
            if index != self._navigation_index and entry.installed_key in self._installed_keys
        ]
        if not candidates:
            return
        self._load_navigation_entry(random.choice(candidates))

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if self._video_expanded and self._video_app_filter_target is not None and event.type() == QEvent.Type.MouseButtonPress:
            self._handle_video_global_mouse_press(event)
        return super().eventFilter(watched, event)

    def _build_media_group(self, title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)
        if isinstance(widget, ScaledImageLabel):
            widget.folderRequested.connect(lambda key=title: self._open_media_folder(_media_key_for_title(key)))
            widget.uploadRequested.connect(lambda key=title: self._upload_media(_media_key_for_title(key)))
            widget.deleteRequested.connect(lambda key=title: self._delete_media(_media_key_for_title(key)))
        return group

    def _build_video_group(self) -> QGroupBox:
        group = QGroupBox("Video")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        self._video_host = QWidget()
        self._video_host.setMinimumHeight(220)
        self._video_host_layout = QVBoxLayout(self._video_host)
        self._video_host_layout.setContentsMargins(0, 0, 0, 0)
        self._video_host_layout.setSpacing(0)

        if HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QVideoWidget is not None and QAudioOutput is not None:
            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumHeight(220)
            self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        else:
            placeholder = QLabel("Video playback is not available in this build.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setMinimumHeight(220)
            placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._video_widget = placeholder
        self._video_host_layout.addWidget(self._video_widget)

        self._video_empty_label = QLabel("No Video")
        self._video_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_empty_label.setMinimumHeight(220)
        self._video_empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._video_content_stack = QStackedWidget()
        self._video_content_stack.setMinimumHeight(220)
        self._video_poster_label = QLabel("Video preview unavailable")
        self._video_poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_poster_label.setMinimumHeight(220)
        self._video_poster_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video_poster_label.setStyleSheet("background: #000000; color: #8f8f8f;")
        self._video_content_stack.addWidget(self._video_host)
        self._video_content_stack.addWidget(self._video_poster_label)
        self._video_content_stack.addWidget(self._video_empty_label)
        layout.addWidget(self._video_content_stack, stretch=1)

        self._video_floating_container = QWidget(self)
        self._video_floating_container.hide()
        self._video_floating_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._video_floating_container.setStyleSheet("background: #000000; border: 1px solid #444444;")
        self._video_floating_layout = QVBoxLayout(self._video_floating_container)
        self._video_floating_layout.setContentsMargins(0, 0, 0, 0)
        self._video_floating_layout.setSpacing(0)

        self._video_primary_controls_widget = QWidget()
        controls_layout = QHBoxLayout(self._video_primary_controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        self._video_play_button = QPushButton()
        self._video_play_button.setObjectName("videoControlButton")
        self._video_play_button.setFixedSize(48, 48)
        self._video_play_button.setIconSize(QSize(28, 28))
        self._video_play_button.setEnabled(False)
        self._video_play_button.clicked.connect(self._toggle_video_playback)

        self._video_position_slider = QSlider(Qt.Orientation.Horizontal)
        self._video_position_slider.setObjectName("videoSeekSlider")
        self._video_position_slider.setEnabled(False)
        self._video_position_slider.setRange(0, 0)
        self._video_position_slider.sliderPressed.connect(self._handle_video_slider_pressed)
        self._video_position_slider.sliderReleased.connect(self._handle_video_slider_released)
        self._video_position_slider.sliderMoved.connect(self._handle_video_slider_moved)

        self._video_volume_button = QPushButton()
        self._video_volume_button.setObjectName("videoControlButton")
        self._video_volume_button.setFixedSize(40, 40)
        self._video_volume_button.setIconSize(QSize(24, 24))
        self._video_volume_button.setEnabled(False)
        self._video_volume_button.clicked.connect(self._toggle_video_mute)

        self._video_folder_button = QPushButton()
        self._video_folder_button.setObjectName("videoControlButton")
        self._video_folder_button.setFixedSize(20, 20)
        self._video_folder_button.setIconSize(QSize(18, 18))
        self._video_folder_button.setIcon(QIcon(str(_assets_dir() / "folder-white.svg")))
        self._video_folder_button.setEnabled(False)
        self._video_folder_button.clicked.connect(lambda: self._open_media_folder("video"))

        self._video_upload_button = QPushButton()
        self._video_upload_button.setObjectName("videoControlButton")
        self._video_upload_button.setFixedSize(20, 20)
        self._video_upload_button.setIconSize(QSize(18, 18))
        self._video_upload_button.setIcon(QIcon(str(_assets_dir() / "upload-white.svg")))
        self._video_upload_button.setEnabled(False)
        self._video_upload_button.clicked.connect(lambda: self._upload_media("video"))

        self._video_delete_button = QPushButton()
        self._video_delete_button.setObjectName("videoControlButton")
        self._video_delete_button.setFixedSize(20, 20)
        self._video_delete_button.setIconSize(QSize(18, 18))
        self._video_delete_button.setIcon(QIcon(str(_assets_dir() / "delete-white.svg")))
        self._video_delete_button.setEnabled(False)
        self._video_delete_button.hide()
        self._video_delete_button.clicked.connect(lambda: self._delete_media("video"))

        self._video_expand_button = QPushButton()
        self._video_expand_button.setObjectName("videoControlButton")
        self._video_expand_button.setFixedSize(20, 20)
        self._video_expand_button.setIconSize(QSize(18, 18))
        self._video_expand_button.setEnabled(False)
        self._video_expand_button.clicked.connect(self._toggle_video_expanded)

        self._video_time_label = QLabel("00:00 / 00:00")
        self._video_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._video_time_label.setMinimumWidth(96)

        controls_layout.addWidget(self._video_play_button)
        controls_layout.addWidget(self._video_position_slider, stretch=1)
        controls_layout.addWidget(self._video_volume_button)
        controls_layout.addWidget(self._video_time_label)
        layout.addWidget(self._video_primary_controls_widget)

        self._video_secondary_controls_widget = QWidget()
        secondary_controls = QHBoxLayout(self._video_secondary_controls_widget)
        secondary_controls.setContentsMargins(0, 0, 0, 0)
        secondary_controls.setSpacing(6)
        secondary_controls.addWidget(self._video_folder_button)
        secondary_controls.addWidget(self._video_upload_button)
        secondary_controls.addWidget(self._video_delete_button)
        secondary_controls.addStretch(1)
        secondary_controls.addWidget(self._video_expand_button)
        layout.addWidget(self._video_secondary_controls_widget)
        return group

    def _populate(self) -> None:
        rom_name = Path(self.entry.rom_path).name
        base_names = _game_name_candidates(rom_name)
        self._media_base_names = base_names

        if not self.installed:
            not_installed_message = "Game is not installed. Install the related system pack to view or manage story and media."
            self.front_art_label.set_image(None, "Game is not installed.")
            self.bezel_label.set_image(None, "Game is not installed.")
            self.logo_label.set_image(None, "Game is not installed.")
            self.led_marquee_label.set_image(None, "Game is not installed.")
            self.lcd_marquee_label.set_image(None, "Game is not installed.")
            self.screenshot_label.set_image(None, "Game is not installed.")
            self.screentitle_label.set_image(None, "Game is not installed.")
            for key, label in (
                ("front_art", self.front_art_label),
                ("bezel", self.bezel_label),
                ("logo", self.logo_label),
                ("led_marquee", self.led_marquee_label),
                ("lcd_marquee", self.lcd_marquee_label),
                ("screenshot", self.screenshot_label),
                ("screentitle", self.screentitle_label),
            ):
                self._set_media_context(key, label, None, None)
            self.story_text.setPlainText(not_installed_message)
            self._media_contexts["video"] = (None, None)
            self._load_video(None)
            self._update_video_media_buttons()
            return

        media_root = _resolve_game_media_root(self.target_dir, self.entry, base_names)
        def media_dir(name: str) -> Path | None:
            return None if media_root is None else media_root / name

        front_art_dir = media_dir("artwork_front")
        front_art_path = _find_matching_media_file(front_art_dir, base_names, IMAGE_MEDIA_SUFFIXES) if front_art_dir is not None else None
        self.front_art_label.set_image(front_art_path, "No Front Artwork")
        self._set_media_context("front_art", self.front_art_label, front_art_path, front_art_dir)

        bezel_dir = media_dir("bezel")
        bezel_path = _find_matching_media_file(bezel_dir, base_names, IMAGE_MEDIA_SUFFIXES) if bezel_dir is not None else None
        self.bezel_label.set_image(bezel_path, "No Bezel")
        self._set_media_context("bezel", self.bezel_label, bezel_path, bezel_dir)

        logo_dir = media_dir("logo")
        logo_path = _find_matching_media_file(logo_dir, base_names, IMAGE_MEDIA_SUFFIXES) if logo_dir is not None else None
        self.logo_label.set_image(logo_path, "No Logo")
        self._set_media_context("logo", self.logo_label, logo_path, logo_dir)

        led_marquee_dir = media_dir("led_marquee")
        led_marquee_path = _find_matching_media_file(led_marquee_dir, base_names, IMAGE_MEDIA_SUFFIXES) if led_marquee_dir is not None else None
        self.led_marquee_label.set_image(led_marquee_path, "No LED Marquee")
        self._set_media_context("led_marquee", self.led_marquee_label, led_marquee_path, led_marquee_dir)

        lcd_marquee_base = media_root if media_root is not None else Path()
        lcd_marquee_path = _find_matching_lcd_marquee_file(lcd_marquee_base, self.bitlcd_target_dir, self.entry, base_names) if media_root is not None else _find_matching_bitlcd_media_file(self.bitlcd_target_dir, self.entry, base_names)
        self.lcd_marquee_label.set_image(lcd_marquee_path, "No LCD Marquee")
        self._set_media_context(
            "lcd_marquee",
            self.lcd_marquee_label,
            lcd_marquee_path,
            _resolve_lcd_marquee_target_dir(media_root, self.bitlcd_target_dir, self.entry, lcd_marquee_path),
        )

        screenshot_dir = media_dir("screenshot")
        screenshot_path = _find_matching_media_file(screenshot_dir, base_names, IMAGE_MEDIA_SUFFIXES) if screenshot_dir is not None else None
        self.screenshot_label.set_image(screenshot_path, "No Screenshot")
        self._set_media_context("screenshot", self.screenshot_label, screenshot_path, screenshot_dir)

        screentitle_dir = media_dir("screentitle")
        screentitle_path = _find_matching_media_file(screentitle_dir, base_names, IMAGE_MEDIA_SUFFIXES) if screentitle_dir is not None else None
        self.screentitle_label.set_image(screentitle_path, "No Screen Title")
        self._set_media_context("screentitle", self.screentitle_label, screentitle_path, screentitle_dir)

        story_dir = media_dir("story")
        story_path = _find_matching_media_file(story_dir, base_names, STORY_MEDIA_SUFFIXES) if story_dir is not None else None
        self.story_text.setPlainText(_read_story_text(story_path))

        video_dir = media_dir("video")
        video_path = _find_matching_media_file(video_dir, base_names, VIDEO_MEDIA_SUFFIXES) if video_dir is not None else None
        self._media_contexts["video"] = (video_path, video_dir)
        self._load_video(video_path)
        self._update_video_media_buttons()

    def _set_media_context(self, key: str, label: ScaledImageLabel, current_path: Path | None, target_dir: Path | None) -> None:
        self._media_contexts[key] = (current_path, target_dir)
        folder_enabled = current_path is not None or target_dir is not None
        upload_enabled = target_dir is not None
        delete_enabled = current_path is not None and current_path.exists()
        label.set_action_buttons_enabled(folder_enabled, upload_enabled, delete_enabled)

    def _preferred_media_stem(self) -> str:
        return self._media_base_names[-1] if self._media_base_names else Path(self.entry.rom_path).stem

    def _open_media_folder(self, key: str) -> None:
        current_path, target_dir = self._media_contexts.get(key, (None, None))
        folder = current_path.parent if current_path is not None else target_dir
        if folder is None:
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _upload_media(self, key: str) -> None:
        current_path, target_dir = self._media_contexts.get(key, (None, None))
        if target_dir is None:
            return
        file_filter = "Video Files (*.mp4 *.avi *.mkv *.mov *.webm);;All Files (*)" if key == "video" else "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All Files (*)"
        selected, _ = QFileDialog.getOpenFileName(self, f"Select {key.replace('_', ' ').title()}", "", file_filter)
        if not selected:
            return
        source_path = Path(selected)
        destination = self._resolve_media_destination(key, source_path)
        if destination is None:
            return
        existing_path = current_path if current_path is not None and current_path.exists() else None
        needs_confirm = existing_path is not None or destination.exists()
        if needs_confirm:
            response = QMessageBox.question(
                self,
                "Overwrite Media",
                f"Replace existing media for {key.replace('_', ' ').title()}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if existing_path is not None and existing_path != destination and existing_path.exists():
                existing_path.unlink()
            shutil.copy2(source_path, destination)
        except OSError as exc:
            QMessageBox.warning(self, "Upload Failed", str(exc))
            return
        self._populate()

    def _delete_media(self, key: str) -> None:
        current_path, _ = self._media_contexts.get(key, (None, None))
        if current_path is None or not current_path.exists():
            return
        response = QMessageBox.question(
            self,
            "Delete Media",
            f"Delete existing media for {key.replace('_', ' ').title()}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        try:
            current_path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Delete Failed", str(exc))
            return
        self._populate()

    def _resolve_media_destination(self, key: str, source_path: Path) -> Path | None:
        current_path, target_dir = self._media_contexts.get(key, (None, None))
        if target_dir is None:
            return None
        if current_path is not None:
            return current_path.with_suffix(source_path.suffix)
        return target_dir / f"{self._preferred_media_stem()}{source_path.suffix}"

    def _set_video_empty_state(self, message: str) -> None:
        if getattr(self, "_video_content_stack", None) is not None and getattr(self, "_video_empty_label", None) is not None:
            self._video_empty_label.setText(message)
            self._video_content_stack.setCurrentWidget(self._video_empty_label)
        if getattr(self, "_video_primary_controls_widget", None) is not None:
            self._video_primary_controls_widget.hide()
        if getattr(self, "_video_secondary_controls_widget", None) is not None:
            self._video_secondary_controls_widget.hide()

    def _show_video_player(self) -> None:
        if getattr(self, "_video_content_stack", None) is not None and self._video_host is not None:
            self._video_content_stack.setCurrentWidget(self._video_host)
        if getattr(self, "_video_primary_controls_widget", None) is not None:
            self._video_primary_controls_widget.show()
        if getattr(self, "_video_secondary_controls_widget", None) is not None:
            self._video_secondary_controls_widget.show()

    def _show_video_poster(self, video_path: Path) -> None:
        if getattr(self, "_video_content_stack", None) is None or getattr(self, "_video_poster_label", None) is None:
            self._show_video_player()
            return
        poster = _extract_video_thumbnail(video_path)
        if poster is None or poster.isNull():
            self._show_video_player()
            return
        scaled = poster.scaled(
            max(1, self._video_content_stack.width()),
            max(1, self._video_content_stack.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._video_poster_label.setPixmap(scaled)
        self._video_poster_label.setText("")
        self._video_content_stack.setCurrentWidget(self._video_poster_label)
        if getattr(self, "_video_primary_controls_widget", None) is not None:
            self._video_primary_controls_widget.show()
        if getattr(self, "_video_secondary_controls_widget", None) is not None:
            self._video_secondary_controls_widget.show()

    def _update_video_media_buttons(self) -> None:
        current_path, target_dir = self._media_contexts.get("video", (None, None))
        folder_enabled = current_path is not None or target_dir is not None
        upload_enabled = target_dir is not None
        delete_enabled = current_path is not None and current_path.exists()
        if self._video_folder_button is not None:
            self._video_folder_button.setEnabled(folder_enabled)
            self._video_folder_button.setVisible(folder_enabled)
        if self._video_upload_button is not None:
            self._video_upload_button.setEnabled(upload_enabled)
            self._video_upload_button.setVisible(upload_enabled)
        if self._video_delete_button is not None:
            self._video_delete_button.setEnabled(delete_enabled)
            self._video_delete_button.setVisible(delete_enabled)

    def _load_video(self, video_path: Path | None) -> None:
        if self._video_expanded:
            self._set_video_expanded(False)
        self._video_current_path = video_path
        if self._media_player is not None:
            for signal, handler in (
                (self._media_player.playbackStateChanged, self._sync_video_controls),
                (self._media_player.positionChanged, self._update_video_position),
                (self._media_player.durationChanged, self._update_video_duration),
            ):
                try:
                    signal.disconnect(handler)
                except (RuntimeError, TypeError):
                    pass
            self._media_player.stop()
            self._media_player.deleteLater()
            self._media_player = None
        if self._audio_output is not None:
            self._audio_output.deleteLater()
            self._audio_output = None

        self._video_duration_ms = 0
        self._video_slider_pressed = False
        if self._video_position_slider is not None:
            self._video_position_slider.setEnabled(False)
            self._video_position_slider.setRange(0, 0)
            self._video_position_slider.setValue(0)
        if self._video_play_button is not None:
            self._video_play_button.setEnabled(False)
            self._video_play_button.setIcon(QIcon(str(_assets_dir() / "play-button-white.svg")))
        if self._video_volume_button is not None:
            self._video_volume_button.setEnabled(False)
            self._video_volume_button.setIcon(QIcon(str(_assets_dir() / "volume-max-white.svg")))
        if self._video_expand_button is not None:
            self._video_expand_button.setEnabled(False)
            self._video_expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))
        if self._video_time_label is not None:
            self._video_time_label.setText("00:00 / 00:00")

        if video_path is None or not video_path.exists():
            self._set_video_empty_state("No Video")
            if isinstance(self._video_widget, QLabel):
                self._video_widget.setText("No Video")
            return

        if not (HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QAudioOutput is not None and isinstance(self._video_widget, QVideoWidget)):
            self._show_video_poster(video_path)
            if isinstance(self._video_widget, QLabel):
                self._video_widget.setText(f"Video available:\n{video_path.name}")
            return

        self._audio_output = QAudioOutput(self)
        self._audio_output.setMuted(False)
        self._audio_output.setVolume(1.0)
        self._media_player = QMediaPlayer(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self._video_widget)
        self._media_player.setSource(QUrl.fromLocalFile(str(video_path)))
        self._media_player.playbackStateChanged.connect(self._sync_video_controls)
        self._media_player.positionChanged.connect(self._update_video_position)
        self._media_player.durationChanged.connect(self._update_video_duration)
        if self._video_play_button is not None:
            self._video_play_button.setEnabled(True)
        if self._video_volume_button is not None:
            self._video_volume_button.setEnabled(True)
        if self._video_expand_button is not None:
            self._video_expand_button.setEnabled(True)
        self._show_video_poster(video_path)
        self._sync_video_controls()
        self._sync_video_volume_button()
        self._sync_video_expand_button()

    def _toggle_video_playback(self) -> None:
        if self._media_player is None:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
        else:
            self._show_video_player()
            self._media_player.play()
        self._sync_video_controls()

    def _sync_video_controls(self, *_args) -> None:
        if self._video_play_button is None:
            return
        is_playing = (
            self._media_player is not None
            and self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self._video_play_button.setIcon(QIcon(str(_assets_dir() / ("pause-white.svg" if is_playing else "play-button-white.svg"))))
        self._video_play_button.setEnabled(self._media_player is not None)

    def _toggle_video_mute(self) -> None:
        if self._audio_output is None:
            return
        self._audio_output.setMuted(not self._audio_output.isMuted())
        self._sync_video_volume_button()

    def _sync_video_volume_button(self) -> None:
        if self._video_volume_button is None:
            return
        muted = self._audio_output is None or self._audio_output.isMuted()
        self._video_volume_button.setIcon(QIcon(str(_assets_dir() / ("volume-off-white.svg" if muted else "volume-max-white.svg"))))
        self._video_volume_button.setEnabled(self._audio_output is not None)

    def _toggle_video_expanded(self) -> None:
        if self._video_expand_button is None or not self._video_expand_button.isEnabled():
            return
        self._show_video_player()
        self._set_video_expanded(not self._video_expanded)


    def _collapse_expanded_video(self) -> None:
        if self._video_expanded:
            self._set_video_expanded(False)


    def _attach_video_app_filter(self) -> None:
        app = QApplication.instance()
        if app is None or app is self._video_app_filter_target:
            return
        if self._video_app_filter_target is not None:
            self._video_app_filter_target.removeEventFilter(self)
        self._video_app_filter_target = app
        self._video_app_filter_target.installEventFilter(self)

    def _detach_video_app_filter(self) -> None:
        if self._video_app_filter_target is not None:
            self._video_app_filter_target.removeEventFilter(self)
            self._video_app_filter_target = None

    def _handle_video_global_mouse_press(self, event) -> None:
        if self._video_floating_container is None or not hasattr(event, "globalPosition"):
            return
        global_pos = event.globalPosition().toPoint()
        local_pos = self._video_floating_container.mapFromGlobal(global_pos)
        if self._video_floating_container.rect().contains(local_pos):
            return
        controls = (
            self._video_play_button,
            self._video_position_slider,
            self._video_volume_button,
            self._video_folder_button,
            self._video_upload_button,
            self._video_delete_button,
            self._video_expand_button,
            self._video_time_label,
        )
        for widget in controls:
            if widget is None or not widget.isVisible():
                continue
            widget_pos = widget.mapFromGlobal(global_pos)
            if widget.rect().contains(widget_pos):
                return
        self._set_video_expanded(False)

    def _set_video_expanded(self, expanded: bool) -> None:
        if (
            self._video_widget is None
            or self._video_host is None
            or self._video_host_layout is None
            or self._video_floating_container is None
            or self._video_floating_layout is None
        ):
            return
        if expanded == self._video_expanded:
            self._sync_video_expand_button()
            return
        if expanded:
            active = ScaledImageLabel._active_expanded_label
            if active is not None and active.window() is self:
                active._set_expanded(False)
        self._video_expanded = expanded
        if expanded:
            if self._video_expand_button is not None:
                self._video_expand_button.hide()
            self._attach_video_app_filter()
            self._video_host_layout.removeWidget(self._video_widget)
            self._video_widget.setParent(self._video_floating_container)
            self._video_floating_layout.addWidget(self._video_widget)
            self._video_floating_container.show()
            self._update_expanded_video_geometry()
            self._video_floating_container.raise_()
        else:
            self._detach_video_app_filter()
            self._video_floating_layout.removeWidget(self._video_widget)
            self._video_widget.setParent(self._video_host)
            self._video_host_layout.addWidget(self._video_widget)
            self._video_floating_container.hide()
            if self._video_expand_button is not None:
                self._video_expand_button.show()
        if self._media_player is not None and isinstance(self._video_widget, QVideoWidget):
            self._media_player.setVideoOutput(self._video_widget)
        self._sync_video_expand_button()

    def _sync_video_expand_button(self) -> None:
        if self._video_expand_button is None:
            return
        self._video_expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))

    def _update_expanded_video_geometry(self) -> None:
        if not self._video_expanded or self._video_host is None or self._video_floating_container is None:
            return
        anchor = self._video_host.mapTo(self, self._video_host.rect().bottomRight())
        base_width = max(220, self._video_host.width())
        base_height = max(220, self._video_host.height())
        target_width = min(self.width() - 24, base_width * 3)
        target_height = min(self.height() - 24, base_height * 3)
        x_pos = max(12, anchor.x() - target_width + 1)
        y_pos = max(12, anchor.y() - target_height + 1)
        self._video_floating_container.setGeometry(x_pos, y_pos, target_width, target_height)

    def _update_video_duration(self, duration_ms: int) -> None:
        self._video_duration_ms = max(0, duration_ms)
        if self._video_position_slider is not None:
            self._video_position_slider.setEnabled(self._video_duration_ms > 0)
            self._video_position_slider.setRange(0, self._video_duration_ms)
        self._update_video_time_label(0 if self._media_player is None else self._media_player.position())

    def _update_video_position(self, position_ms: int) -> None:
        position_ms = max(0, position_ms)
        if self._video_position_slider is not None and not self._video_slider_pressed:
            self._video_position_slider.setValue(position_ms)
        self._update_video_time_label(position_ms)

    def _handle_video_slider_pressed(self) -> None:
        self._video_slider_pressed = True

    def _handle_video_slider_released(self) -> None:
        self._video_slider_pressed = False
        if self._media_player is None or self._video_position_slider is None:
            return
        self._media_player.setPosition(self._video_position_slider.value())

    def _handle_video_slider_moved(self, position_ms: int) -> None:
        self._update_video_time_label(position_ms)

    def _update_video_time_label(self, position_ms: int) -> None:
        if self._video_time_label is None:
            return
        self._video_time_label.setText(
            f"{self._format_media_time(position_ms)} / {self._format_media_time(self._video_duration_ms)}"
        )

    def _format_media_time(self, milliseconds: int) -> str:
        total_seconds = max(0, milliseconds) // 1000
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


class CollectionDetailsDialog(QDialog):
    def __init__(
        self,
        entry: CollectionCatalogEntry,
        target_dir: Path | None,
        navigation_entries: list[CollectionCatalogEntry] | None = None,
        navigation_index: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.target_dir = target_dir
        self._navigation_entries = list(navigation_entries or [entry])
        self._navigation_index = navigation_index if navigation_index is not None else 0
        self._navigation_loading = False
        self._media_player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
        self._video_widget: QVideoWidget | QLabel | None = None
        self._video_poster_label: QLabel | None = None
        self._video_host: QWidget | None = None
        self._video_host_layout: QVBoxLayout | None = None
        self._video_floating_container: QWidget | None = None
        self._video_floating_layout: QVBoxLayout | None = None
        self._video_play_button: QPushButton | None = None
        self._video_volume_button: QPushButton | None = None
        self._video_expand_button: QPushButton | None = None
        self._video_position_slider: QSlider | None = None
        self._video_time_label: QLabel | None = None
        self._video_duration_ms = 0
        self._video_slider_pressed = False
        self._video_expanded = False
        self._video_app_filter_target: QApplication | None = None
        self._video_group: QGroupBox | None = None
        self._video_current_path: Path | None = None
        self._collection_video_paths: tuple[Path, ...] = ()
        self._collection_video_index = 0

        self.setWindowTitle(entry.name)
        if isinstance(parent, QWidget):
            self.resize(parent.size())
        else:
            self.resize(1280, 960)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        self.front_art_label = ScaledImageLabel(110, minimum_width=220)
        self.device_label = ScaledImageLabel(180, minimum_width=220)
        self.logo_label = ScaledImageLabel(180, minimum_width=220)
        top_row.addWidget(self._build_media_group("Device", self.device_label), stretch=1)
        top_row.addWidget(self._build_media_group("Logo", self.logo_label), stretch=1)
        root.addLayout(top_row)

        content_grid = QGridLayout()
        content_grid.setHorizontalSpacing(16)
        content_grid.setVerticalSpacing(12)
        content_grid.setColumnStretch(0, 1)
        content_grid.setColumnStretch(1, 1)
        content_grid.setColumnStretch(2, 1)
        content_grid.setColumnStretch(3, 1)

        details_group = QGroupBox("Collection Details")
        details_layout = QVBoxLayout(details_group)
        details_layout.setSpacing(8)
        self.collection_name_label = QLabel()
        self.parent_collections_label = QLabel()
        self.parent_collections_label.setTextFormat(Qt.TextFormat.RichText)
        self.parent_collections_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.parent_collections_label.setOpenExternalLinks(False)
        self.parent_collections_label.setWordWrap(True)
        self.parent_collections_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.parent_collections_label.linkActivated.connect(self._open_related_collection)
        self.child_collections_label = QLabel()
        self.child_collections_label.setTextFormat(Qt.TextFormat.RichText)
        self.child_collections_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.child_collections_label.setOpenExternalLinks(False)
        self.child_collections_label.setWordWrap(True)
        self.child_collections_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.child_collections_label.linkActivated.connect(self._open_related_collection)
        self.status_label = QLabel()
        self.game_count_label = QLabel()
        self.game_count_label.setTextFormat(Qt.TextFormat.RichText)
        self.game_count_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.game_count_label.setOpenExternalLinks(False)
        self.game_count_label.linkActivated.connect(self._show_games_for_current_collection)
        details_layout.addWidget(self.collection_name_label)
        details_layout.addWidget(self.parent_collections_label)
        details_layout.addWidget(self.child_collections_label)
        details_layout.addWidget(self.status_label)
        details_layout.addWidget(self.game_count_label)
        self.collection_attributes_widget = QWidget()
        self.collection_attributes_layout = QVBoxLayout(self.collection_attributes_widget)
        self.collection_attributes_layout.setContentsMargins(0, 0, 0, 0)
        self.collection_attributes_layout.setSpacing(4)
        details_layout.addWidget(self.collection_attributes_widget)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMinimumHeight(420)
        details_layout.addWidget(self.info_text, stretch=1)
        navigation_row = QHBoxLayout()
        navigation_row.setSpacing(10)
        self.navigation_position_label = QLabel("Collection 1/1")
        navigation_row.addWidget(self.navigation_position_label)
        navigation_row.addStretch(1)
        self.previous_collection_button = QPushButton("Previous")
        self.previous_collection_button.setMinimumWidth(140)
        self.previous_collection_button.clicked.connect(self._show_previous_collection)
        self.next_collection_button = QPushButton("Next")
        self.next_collection_button.setMinimumWidth(140)
        self.next_collection_button.clicked.connect(self._show_next_collection)
        self.random_collection_button = QPushButton("Random")
        self.random_collection_button.setMinimumWidth(140)
        self.random_collection_button.clicked.connect(self._show_random_collection)
        navigation_row.addWidget(self.previous_collection_button)
        navigation_row.addWidget(self.next_collection_button)
        navigation_row.addWidget(self.random_collection_button)
        details_layout.addLayout(navigation_row)
        content_grid.addWidget(details_group, 0, 0, 1, 3)

        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(12)
        self.led_marquee_label = ScaledImageLabel(110, minimum_width=220)
        side_layout.addWidget(self._build_media_group("Front Artwork", self.front_art_label))
        side_layout.addWidget(self._build_media_group("LED Marquee", self.led_marquee_label))
        side_layout.addWidget(self._build_video_group(), stretch=1)
        content_grid.addWidget(side_panel, 0, 3)

        root.addLayout(content_grid, stretch=1)
        self._refresh_view()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._video_expanded:
            self._set_video_expanded(False)
        if self._media_player is not None:
            self._media_player.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._video_expanded:
            self._update_expanded_video_geometry()
        elif (
            getattr(self, "_video_content_stack", None) is not None
            and getattr(self, "_video_poster_label", None) is not None
            and self._video_current_path is not None
            and self._video_content_stack.currentWidget() is self._video_poster_label
        ):
            self._show_video_poster(self._video_current_path)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if self._video_expanded and self._video_app_filter_target is not None and event.type() == QEvent.Type.MouseButtonPress:
            self._handle_video_global_mouse_press(event)
        return super().eventFilter(watched, event)

    def _refresh_view(self) -> None:
        self.setWindowTitle(self.entry.name)
        self.collection_name_label.setText(f"Collection Name: {self.entry.name}")
        has_parents = bool(self.entry.parent_collections)
        parent_links = " | ".join(f'<a href="{name}">{name}</a>' for name in self.entry.parent_collections)
        self.parent_collections_label.setVisible(has_parents)
        self.parent_collections_label.setText(
            f"Parent Collections: {parent_links}" if has_parents else ""
        )
        has_children = bool(self.entry.child_collections)
        child_links = " | ".join(f'<a href="{name}">{name}</a>' for name in self.entry.child_collections)
        self.child_collections_label.setVisible(has_children)
        self.child_collections_label.setText(
            f"Child Collections: {child_links}" if has_children else ""
        )
        self.status_label.setText(f"Status: {'Installed' if self.entry.installed else 'Not Installed'}")
        self.game_count_label.setText(f'# of Games: <a href="{self.entry.name}">{self.entry.game_count:,}</a>')
        self._populate_attribute_labels()
        self._populate_media()
        self._update_navigation_buttons()

    def _populate_attribute_labels(self) -> None:
        while self.collection_attributes_layout.count():
            item = self.collection_attributes_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        attributes = read_collection_info_attributes(self.target_dir, self.entry.name)
        self.collection_attributes_widget.setVisible(bool(attributes))
        for key, value in attributes:
            label = QLabel(f"{key}: {value}")
            self.collection_attributes_layout.addWidget(label)

    def _open_related_collection(self, collection_name: str) -> None:
        for index, entry in enumerate(self._navigation_entries):
            if entry.name == collection_name:
                self._load_navigation_entry(index)
                return
        catalog_entries = build_collection_catalog(self.target_dir)
        for entry in catalog_entries:
            if entry.name != collection_name:
                continue
            self._navigation_entries = [entry]
            self._navigation_index = 0
            self.entry = entry
            self._refresh_view()
            return
        self._update_navigation_buttons()

    def _show_games_for_current_collection(self, collection_name: str) -> None:
        parent = self.parent()
        show_games = getattr(parent, "_show_games_for_collection", None)
        if callable(show_games):
            show_games(collection_name)
            self.accept()

    def _update_navigation_buttons(self) -> None:
        total = len(self._navigation_entries)
        has_navigation = total > 1
        self.navigation_position_label.setText(f"Collection {self._navigation_index + 1}/{max(1, total)}")
        self.previous_collection_button.setVisible(has_navigation)
        self.next_collection_button.setVisible(has_navigation)
        self.random_collection_button.setVisible(total > 0)
        if self._navigation_loading:
            self.previous_collection_button.setEnabled(False)
            self.next_collection_button.setEnabled(False)
            self.random_collection_button.setEnabled(False)
            return
        self.previous_collection_button.setEnabled(has_navigation and self._navigation_index > 0)
        self.next_collection_button.setEnabled(has_navigation and self._navigation_index < total - 1)
        self.random_collection_button.setEnabled(total > 1)

    def _load_navigation_entry(self, index: int) -> None:
        if index < 0 or index >= len(self._navigation_entries) or index == self._navigation_index:
            return
        self._navigation_loading = True
        self._update_navigation_buttons()
        QApplication.processEvents()
        try:
            if self._video_expanded:
                self._set_video_expanded(False)
            active = ScaledImageLabel._active_expanded_label
            if active is not None and active.window() is self:
                active._set_expanded(False)
            self._navigation_index = index
            self.entry = self._navigation_entries[index]
            self._refresh_view()
        finally:
            self._navigation_loading = False
            self._update_navigation_buttons()

    def _show_previous_collection(self) -> None:
        self._load_navigation_entry(self._navigation_index - 1)

    def _show_next_collection(self) -> None:
        self._load_navigation_entry(self._navigation_index + 1)

    def _show_random_collection(self) -> None:
        if len(self._navigation_entries) <= 1:
            return
        candidates = [index for index in range(len(self._navigation_entries)) if index != self._navigation_index]
        if not candidates:
            return
        self._load_navigation_entry(random.choice(candidates))

    def _build_media_group(self, title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)
        if isinstance(widget, ScaledImageLabel):
            widget.set_action_buttons_enabled(False, False, False)
        return group

    def _build_video_group(self) -> QGroupBox:
        self._video_group = QGroupBox("Video")
        layout = QVBoxLayout(self._video_group)
        layout.setSpacing(10)

        self._video_host = QWidget()
        self._video_host.setMinimumHeight(220)
        self._video_host_layout = QVBoxLayout(self._video_host)
        self._video_host_layout.setContentsMargins(0, 0, 0, 0)
        self._video_host_layout.setSpacing(0)

        if HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QVideoWidget is not None and QAudioOutput is not None:
            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumHeight(220)
            self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        else:
            placeholder = QLabel("Video playback is not available in this build.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setMinimumHeight(220)
            placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._video_widget = placeholder
        self._video_host_layout.addWidget(self._video_widget)

        self._video_empty_label = QLabel("No Video")
        self._video_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_empty_label.setMinimumHeight(220)
        self._video_empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._video_content_stack = QStackedWidget()
        self._video_content_stack.setMinimumHeight(220)
        self._video_poster_label = QLabel("Video preview unavailable")
        self._video_poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_poster_label.setMinimumHeight(220)
        self._video_poster_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video_poster_label.setStyleSheet("background: #000000; color: #8f8f8f;")
        self._video_content_stack.addWidget(self._video_host)
        self._video_content_stack.addWidget(self._video_poster_label)
        self._video_content_stack.addWidget(self._video_empty_label)
        layout.addWidget(self._video_content_stack, stretch=1)

        self._video_floating_container = QWidget(self)
        self._video_floating_container.hide()
        self._video_floating_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._video_floating_container.setStyleSheet("background: #000000; border: 1px solid #444444;")
        self._video_floating_layout = QVBoxLayout(self._video_floating_container)
        self._video_floating_layout.setContentsMargins(0, 0, 0, 0)
        self._video_floating_layout.setSpacing(0)

        self._video_primary_controls_widget = QWidget()
        controls_layout = QHBoxLayout(self._video_primary_controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        self._video_previous_button = QPushButton()
        self._video_previous_button.setObjectName("videoControlButton")
        self._video_previous_button.setFixedSize(40, 40)
        self._video_previous_button.setIconSize(QSize(24, 24))
        self._video_previous_button.setEnabled(False)
        self._video_previous_button.setIcon(QIcon(str(_assets_dir() / "previous-circle.svg")))
        self._video_previous_button.clicked.connect(self._show_previous_video)
        self._video_previous_button.hide()

        self._video_play_button = QPushButton()
        self._video_play_button.setObjectName("videoControlButton")
        self._video_play_button.setFixedSize(48, 48)
        self._video_play_button.setIconSize(QSize(28, 28))
        self._video_play_button.setEnabled(False)
        self._video_play_button.clicked.connect(self._toggle_video_playback)

        self._video_next_button = QPushButton()
        self._video_next_button.setObjectName("videoControlButton")
        self._video_next_button.setFixedSize(40, 40)
        self._video_next_button.setIconSize(QSize(24, 24))
        self._video_next_button.setEnabled(False)
        self._video_next_button.setIcon(QIcon(str(_assets_dir() / "next-circle.svg")))
        self._video_next_button.clicked.connect(self._show_next_video)
        self._video_next_button.hide()

        self._video_position_slider = QSlider(Qt.Orientation.Horizontal)
        self._video_position_slider.setObjectName("videoSeekSlider")
        self._video_position_slider.setEnabled(False)
        self._video_position_slider.setRange(0, 0)
        self._video_position_slider.sliderPressed.connect(self._handle_video_slider_pressed)
        self._video_position_slider.sliderReleased.connect(self._handle_video_slider_released)
        self._video_position_slider.sliderMoved.connect(self._handle_video_slider_moved)

        self._video_volume_button = QPushButton()
        self._video_volume_button.setObjectName("videoControlButton")
        self._video_volume_button.setFixedSize(40, 40)
        self._video_volume_button.setIconSize(QSize(24, 24))
        self._video_volume_button.setEnabled(False)
        self._video_volume_button.clicked.connect(self._toggle_video_mute)

        self._video_expand_button = QPushButton()
        self._video_expand_button.setObjectName("videoControlButton")
        self._video_expand_button.setFixedSize(20, 20)
        self._video_expand_button.setIconSize(QSize(18, 18))
        self._video_expand_button.setEnabled(False)
        self._video_expand_button.clicked.connect(self._toggle_video_expanded)

        self._video_time_label = QLabel("00:00 / 00:00")
        self._video_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._video_time_label.setMinimumWidth(96)

        controls_layout.addWidget(self._video_previous_button)
        controls_layout.addWidget(self._video_play_button)
        controls_layout.addWidget(self._video_next_button)
        controls_layout.addWidget(self._video_position_slider, stretch=1)
        controls_layout.addWidget(self._video_volume_button)
        controls_layout.addWidget(self._video_time_label)
        layout.addWidget(self._video_primary_controls_widget)

        self._video_secondary_controls_widget = QWidget()
        secondary_controls = QHBoxLayout(self._video_secondary_controls_widget)
        secondary_controls.setContentsMargins(0, 0, 0, 0)
        secondary_controls.setSpacing(6)
        secondary_controls.addStretch(1)
        secondary_controls.addWidget(self._video_expand_button)
        layout.addWidget(self._video_secondary_controls_widget)
        return self._video_group

    def _populate_media(self) -> None:
        media_root = _resolve_collection_media_root(self.target_dir, self.entry.name)
        self.front_art_label.set_image(_find_named_collection_media_file(media_root, "artwork_front", IMAGE_MEDIA_SUFFIXES), "No Front Artwork")
        self.device_label.set_image(_find_named_collection_media_file(media_root, "device", IMAGE_MEDIA_SUFFIXES), "No Device")
        self.logo_label.set_image(_find_named_collection_media_file(media_root, "logo", IMAGE_MEDIA_SUFFIXES), "No Logo")
        self.led_marquee_label.set_image(_find_named_collection_media_file(media_root, "led_marquee", IMAGE_MEDIA_SUFFIXES), "No LED Marquee")
        for label in (
            self.front_art_label,
            self.device_label,
            self.logo_label,
            self.led_marquee_label,
        ):
            label.set_action_buttons_enabled(False, False, False)
        story_path = _find_named_collection_media_file(media_root, "story", STORY_MEDIA_SUFFIXES)
        self.info_text.setPlainText(_read_story_text(story_path))
        self._collection_video_paths = _find_collection_videos(media_root)
        self._collection_video_index = 0
        self._sync_video_navigation_buttons()
        self._load_video(self._collection_video_paths[0] if self._collection_video_paths else None)

    def _set_video_empty_state(self, message: str) -> None:
        if getattr(self, "_video_content_stack", None) is not None and getattr(self, "_video_empty_label", None) is not None:
            self._video_empty_label.setText(message)
            self._video_content_stack.setCurrentWidget(self._video_empty_label)
        if getattr(self, "_video_primary_controls_widget", None) is not None:
            self._video_primary_controls_widget.hide()
        if getattr(self, "_video_secondary_controls_widget", None) is not None:
            self._video_secondary_controls_widget.hide()

    def _show_video_player(self) -> None:
        if getattr(self, "_video_content_stack", None) is not None and self._video_host is not None:
            self._video_content_stack.setCurrentWidget(self._video_host)
        if getattr(self, "_video_primary_controls_widget", None) is not None:
            self._video_primary_controls_widget.show()
        if getattr(self, "_video_secondary_controls_widget", None) is not None:
            self._video_secondary_controls_widget.show()

    def _show_video_poster(self, video_path: Path) -> None:
        if getattr(self, "_video_content_stack", None) is None or getattr(self, "_video_poster_label", None) is None:
            self._show_video_player()
            return
        poster = _extract_video_thumbnail(video_path)
        if poster is None or poster.isNull():
            self._show_video_player()
            return
        scaled = poster.scaled(
            max(1, self._video_content_stack.width()),
            max(1, self._video_content_stack.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._video_poster_label.setPixmap(scaled)
        self._video_poster_label.setText("")
        self._video_content_stack.setCurrentWidget(self._video_poster_label)
        if getattr(self, "_video_primary_controls_widget", None) is not None:
            self._video_primary_controls_widget.show()
        if getattr(self, "_video_secondary_controls_widget", None) is not None:
            self._video_secondary_controls_widget.show()

    def _load_video(self, video_path: Path | None) -> None:
        if self._video_expanded:
            self._set_video_expanded(False)
        self._video_current_path = video_path
        if self._media_player is not None:
            for signal, handler in (
                (self._media_player.playbackStateChanged, self._sync_video_controls),
                (self._media_player.positionChanged, self._update_video_position),
                (self._media_player.durationChanged, self._update_video_duration),
            ):
                try:
                    signal.disconnect(handler)
                except (RuntimeError, TypeError):
                    pass
            self._media_player.stop()
            self._media_player.deleteLater()
            self._media_player = None
        if self._audio_output is not None:
            self._audio_output.deleteLater()
            self._audio_output = None

        self._video_duration_ms = 0
        self._video_slider_pressed = False
        if self._video_position_slider is not None:
            self._video_position_slider.setEnabled(False)
            self._video_position_slider.setRange(0, 0)
            self._video_position_slider.setValue(0)
        if getattr(self, "_video_previous_button", None) is not None:
            self._video_previous_button.setEnabled(False)
        if self._video_play_button is not None:
            self._video_play_button.setEnabled(False)
            self._video_play_button.setIcon(QIcon(str(_assets_dir() / "play-button-white.svg")))
        if getattr(self, "_video_next_button", None) is not None:
            self._video_next_button.setEnabled(False)
        if self._video_volume_button is not None:
            self._video_volume_button.setEnabled(False)
            self._video_volume_button.setIcon(QIcon(str(_assets_dir() / "volume-max-white.svg")))
        if self._video_expand_button is not None:
            self._video_expand_button.setEnabled(False)
            self._video_expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))
        if self._video_time_label is not None:
            self._video_time_label.setText("00:00 / 00:00")
        if getattr(self, "_video_poster_label", None) is not None:
            self._video_poster_label.setPixmap(QPixmap())
            self._video_poster_label.setText("Video preview unavailable")

        if video_path is None or not video_path.exists():
            self._set_video_empty_state("No Video")
            if isinstance(self._video_widget, QLabel):
                self._video_widget.setText("No Video")
            return

        if not (HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QAudioOutput is not None and isinstance(self._video_widget, QVideoWidget)):
            self._show_video_poster(video_path)
            if isinstance(self._video_widget, QLabel):
                self._video_widget.setText(f"Video available:\n{video_path.name}")
            return

        self._audio_output = QAudioOutput(self)
        self._audio_output.setMuted(False)
        self._audio_output.setVolume(1.0)
        self._media_player = QMediaPlayer(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self._video_widget)
        self._media_player.setSource(QUrl.fromLocalFile(str(video_path)))
        self._media_player.playbackStateChanged.connect(self._sync_video_controls)
        self._media_player.positionChanged.connect(self._update_video_position)
        self._media_player.durationChanged.connect(self._update_video_duration)
        if self._video_play_button is not None:
            self._video_play_button.setEnabled(True)
        self._sync_video_navigation_buttons()
        if self._video_volume_button is not None:
            self._video_volume_button.setEnabled(True)
        if self._video_expand_button is not None:
            self._video_expand_button.setEnabled(True)
        self._show_video_poster(video_path)
        self._sync_video_controls()
        self._sync_video_volume_button()
        self._sync_video_expand_button()

    def _sync_video_navigation_buttons(self) -> None:
        has_multiple = len(self._collection_video_paths) > 1
        if self._video_group is not None:
            if has_multiple:
                self._video_group.setTitle(f"Video {self._collection_video_index + 1}/{len(self._collection_video_paths)}")
            else:
                self._video_group.setTitle("Video")
        if getattr(self, "_video_previous_button", None) is not None:
            self._video_previous_button.setVisible(has_multiple)
            self._video_previous_button.setEnabled(has_multiple)
        if getattr(self, "_video_next_button", None) is not None:
            self._video_next_button.setVisible(has_multiple)
            self._video_next_button.setEnabled(has_multiple)

    def _show_previous_video(self) -> None:
        if len(self._collection_video_paths) <= 1:
            return
        self._collection_video_index = (self._collection_video_index - 1) % len(self._collection_video_paths)
        self._load_video(self._collection_video_paths[self._collection_video_index])

    def _show_next_video(self) -> None:
        if len(self._collection_video_paths) <= 1:
            return
        self._collection_video_index = (self._collection_video_index + 1) % len(self._collection_video_paths)
        self._load_video(self._collection_video_paths[self._collection_video_index])

    def _toggle_video_playback(self) -> None:
        if self._media_player is None:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
        else:
            self._show_video_player()
            self._media_player.play()
        self._sync_video_controls()

    def _sync_video_controls(self, *_args) -> None:
        if self._video_play_button is None:
            return
        is_playing = (
            self._media_player is not None
            and self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self._video_play_button.setIcon(QIcon(str(_assets_dir() / ("pause-white.svg" if is_playing else "play-button-white.svg"))))
        self._video_play_button.setEnabled(self._media_player is not None)

    def _toggle_video_mute(self) -> None:
        if self._audio_output is None:
            return
        self._audio_output.setMuted(not self._audio_output.isMuted())
        self._sync_video_volume_button()

    def _sync_video_volume_button(self) -> None:
        if self._video_volume_button is None:
            return
        muted = self._audio_output is None or self._audio_output.isMuted()
        self._video_volume_button.setIcon(QIcon(str(_assets_dir() / ("volume-off-white.svg" if muted else "volume-max-white.svg"))))
        self._video_volume_button.setEnabled(self._audio_output is not None)

    def _toggle_video_expanded(self) -> None:
        if self._video_expand_button is None or not self._video_expand_button.isEnabled():
            return
        self._show_video_player()
        self._set_video_expanded(not self._video_expanded)

    def _collapse_expanded_video(self) -> None:
        if self._video_expanded:
            self._set_video_expanded(False)

    def _attach_video_app_filter(self) -> None:
        app = QApplication.instance()
        if app is None or app is self._video_app_filter_target:
            return
        if self._video_app_filter_target is not None:
            self._video_app_filter_target.removeEventFilter(self)
        self._video_app_filter_target = app
        self._video_app_filter_target.installEventFilter(self)

    def _detach_video_app_filter(self) -> None:
        if self._video_app_filter_target is not None:
            self._video_app_filter_target.removeEventFilter(self)
            self._video_app_filter_target = None

    def _handle_video_global_mouse_press(self, event) -> None:
        if self._video_floating_container is None or not hasattr(event, "globalPosition"):
            return
        global_pos = event.globalPosition().toPoint()
        local_pos = self._video_floating_container.mapFromGlobal(global_pos)
        if self._video_floating_container.rect().contains(local_pos):
            return
        for widget in (self._video_play_button, self._video_position_slider, self._video_volume_button, self._video_expand_button, self._video_time_label):
            if widget is None or not widget.isVisible():
                continue
            widget_pos = widget.mapFromGlobal(global_pos)
            if widget.rect().contains(widget_pos):
                return
        self._set_video_expanded(False)

    def _set_video_expanded(self, expanded: bool) -> None:
        if (
            self._video_widget is None
            or self._video_host is None
            or self._video_host_layout is None
            or self._video_floating_container is None
            or self._video_floating_layout is None
        ):
            return
        if expanded == self._video_expanded:
            self._sync_video_expand_button()
            return
        if expanded:
            active = ScaledImageLabel._active_expanded_label
            if active is not None and active.window() is self:
                active._set_expanded(False)
        self._video_expanded = expanded
        if expanded:
            if self._video_expand_button is not None:
                self._video_expand_button.hide()
            self._attach_video_app_filter()
            self._video_host_layout.removeWidget(self._video_widget)
            self._video_widget.setParent(self._video_floating_container)
            self._video_floating_layout.addWidget(self._video_widget)
            self._video_floating_container.show()
            self._update_expanded_video_geometry()
            self._video_floating_container.raise_()
        else:
            self._detach_video_app_filter()
            self._video_floating_layout.removeWidget(self._video_widget)
            self._video_widget.setParent(self._video_host)
            self._video_host_layout.addWidget(self._video_widget)
            self._video_floating_container.hide()
            if self._video_expand_button is not None:
                self._video_expand_button.show()
        if self._media_player is not None and isinstance(self._video_widget, QVideoWidget):
            self._media_player.setVideoOutput(self._video_widget)
        self._sync_video_expand_button()

    def _sync_video_expand_button(self) -> None:
        if self._video_expand_button is None:
            return
        self._video_expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))

    def _update_expanded_video_geometry(self) -> None:
        if not self._video_expanded or self._video_host is None or self._video_floating_container is None:
            return
        anchor = self._video_host.mapTo(self, self._video_host.rect().bottomRight())
        base_width = max(220, self._video_host.width())
        base_height = max(220, self._video_host.height())
        target_width = min(self.width() - 24, base_width * 3)
        target_height = min(self.height() - 24, base_height * 3)
        x_pos = max(12, anchor.x() - target_width + 1)
        y_pos = max(12, anchor.y() - target_height + 1)
        self._video_floating_container.setGeometry(x_pos, y_pos, target_width, target_height)

    def _update_video_duration(self, duration_ms: int) -> None:
        self._video_duration_ms = max(0, duration_ms)
        if self._video_position_slider is not None:
            self._video_position_slider.setEnabled(self._video_duration_ms > 0)
            self._video_position_slider.setRange(0, self._video_duration_ms)
        self._update_video_time_label(0 if self._media_player is None else self._media_player.position())

    def _update_video_position(self, position_ms: int) -> None:
        position_ms = max(0, position_ms)
        if self._video_position_slider is not None and not self._video_slider_pressed:
            self._video_position_slider.setValue(position_ms)
        self._update_video_time_label(position_ms)

    def _handle_video_slider_pressed(self) -> None:
        self._video_slider_pressed = True

    def _handle_video_slider_released(self) -> None:
        self._video_slider_pressed = False
        if self._media_player is None or self._video_position_slider is None:
            return
        self._media_player.setPosition(self._video_position_slider.value())

    def _handle_video_slider_moved(self, position_ms: int) -> None:
        self._update_video_time_label(position_ms)

    def _update_video_time_label(self, position_ms: int) -> None:
        if self._video_time_label is None:
            return
        self._video_time_label.setText(
            f"{self._format_media_time(position_ms)} / {self._format_media_time(self._video_duration_ms)}"
        )

    def _format_media_time(self, milliseconds: int) -> str:
        total_seconds = max(0, milliseconds) // 1000
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


class ThemeLayoutPreviewWidget(QWidget):
    _active_expanded_preview: "ThemeLayoutPreviewWidget | None" = None
    _font_family_cache: dict[str, str | None] = {}
    _raw_font_cache: dict[tuple[str, int], QRawFont | None] = {}

    _COLOR_MAP = {
        "image": QColor("#ffb347"),
        "reloadable_image": QColor("#4fd2ff"),
        "reloadable_panning_image": QColor("#4fd2ff"),
        "video": QColor("#d88cff"),
        "reloadable_video": QColor("#86f07b"),
        "text": QColor("#7faeff"),
        "reloadable_text": QColor("#5ec8ff"),
        "reloadable_scrolling_text": QColor("#4fc6b5"),
        "scrolling_text": QColor("#55d4c1"),
        "menu": QColor("#f3db63"),
    }
    elementSelected = Signal(object)
    previousRequested = Signal()
    playPauseRequested = Signal()
    nextRequested = Signal()
    muteRequested = Signal()
    wheelAnimationFinished = Signal()
    wheelAnimationIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview: ThemeLayoutPreview | None = None
        self._selected_element: ThemePreviewElement | None = None
        self._element_hitboxes: list[tuple[QPainterPath, ThemePreviewElement]] = []
        self._render_data: dict[ThemePreviewElement, ThemePreviewRenderData] = {}
        self._show_wireframes = True
        self._show_media = True
        self._show_text = True
        self._expanded = False
        self._window_filter_target: QWidget | None = None
        self._app_filter_target: QApplication | None = None
        self._floating_preview: QWidget | None = None
        self._floating_canvas_label: QLabel | None = None
        self._action_padding = 6
        self._action_button_size = 20
        self._action_icon_size = 18
        self._control_spacing = 8
        self._nav_control_spacing = 0
        self._controls_enabled = False
        self._mute_enabled = False
        self._animation_enabled = False
        self._muted = False
        self._transition_active: bool = False
        self._transition_start_ms: float = 0.0
        self._transition_duration_ms: int = 400
        self._transition_timer = QTimer(self)
        self._transition_timer.setSingleShot(False)
        self._transition_timer.setInterval(16)
        self._transition_timer.timeout.connect(self.update)
        self._wheel_anim_active: bool = False
        self._wheel_anim_start_ms: float = 0.0
        self._wheel_anim_duration_ms: int = 1000
        self._wheel_anim_advance_count: int = 0
        self._wheel_anim_target_advance: int = 0
        self._wheel_anim_start_game_0: int = 0
        self._wheel_anim_total_games: int = 0
        self._wheel_anim_logos: dict[int, QPixmap] = {}
        self._wheel_anim_slot_elements: list = []
        self._wheel_anim_sel_idx: int = 0
        self._wheel_anim_extra_groups: list[tuple[list, dict[int, QPixmap], int]] = []
        self._wheel_anim_last_emitted_index: int | None = None
        self._wheel_anim_timer = QTimer(self)
        self._wheel_anim_timer.setInterval(16)
        self._wheel_anim_timer.timeout.connect(self._on_wheel_anim_tick)
        self._scroll_anim_opacity: float = 1.0
        self._scroll_fading_out: bool = False
        self._scroll_fade_start_ms: float = 0.0
        self._scroll_fade_duration_ms: int = 1200
        self._scroll_fade_timer = QTimer(self)
        self._scroll_fade_timer.setInterval(16)
        self._scroll_fade_timer.timeout.connect(self._on_scroll_fade_tick)
        self._idle_anim_timer = QTimer(self)
        self._idle_anim_timer.setInterval(16)
        self._idle_anim_timer.timeout.connect(self._on_idle_anim_tick)
        self._idle_anim_start_ms: float = 0.0
        self._idle_anim_alphas: dict[ThemePreviewElement, float] = {}
        self._idle_anim_values: dict[ThemePreviewElement, dict[str, float]] = {}
        self._event_anim_timer = QTimer(self)
        self._event_anim_timer.setInterval(16)
        self._event_anim_timer.timeout.connect(self._on_event_anim_tick)
        self._event_anim_name: str | None = None
        self._event_anim_start_ms: float = 0.0
        self._event_anim_values: dict[ThemePreviewElement, dict[str, float]] = {}
        self._resume_idle_after_transition: bool = False
        self._pulsing_overlay_elements: frozenset[ThemePreviewElement] = frozenset()
        self._covered_selected_menu_elements: frozenset[ThemePreviewElement] = frozenset()
        self._pulsing_overlay_targets: dict[ThemePreviewElement, ThemePreviewElement] = {}
        self._floating_preview_dirty: bool = False
        self._floating_preview_update_timer = QTimer(self)
        self._floating_preview_update_timer.setSingleShot(True)
        self._floating_preview_update_timer.setInterval(50)
        self._floating_preview_update_timer.timeout.connect(self._flush_floating_preview_update)
        self._floating_preview_update_interval_ms: int = 50
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._play_button = QPushButton(self)
        self._play_button.setObjectName("videoControlButton")
        self._play_button.setFixedSize(42, 42)
        self._play_button.setIconSize(QSize(24, 24))
        self._play_button.setFlat(True)
        self._play_button.clicked.connect(self.playPauseRequested.emit)
        self._play_button.hide()
        self._previous_button = QPushButton(self)
        self._previous_button.setObjectName("videoControlButton")
        self._previous_button.setFixedSize(38, 38)
        self._previous_button.setIconSize(QSize(22, 22))
        self._previous_button.setFlat(True)
        self._previous_button.setIcon(QIcon(str(_assets_dir() / "previous-circle.svg")))
        self._previous_button.clicked.connect(self.previousRequested.emit)
        self._previous_button.hide()
        self._next_button = QPushButton(self)
        self._next_button.setObjectName("videoControlButton")
        self._next_button.setFixedSize(38, 38)
        self._next_button.setIconSize(QSize(22, 22))
        self._next_button.setFlat(True)
        self._next_button.setIcon(QIcon(str(_assets_dir() / "next-circle.svg")))
        self._next_button.clicked.connect(self.nextRequested.emit)
        self._next_button.hide()
        self._volume_button = QPushButton(self)
        self._volume_button.setObjectName("videoControlButton")
        self._volume_button.setFixedSize(38, 38)
        self._volume_button.setIconSize(QSize(22, 22))
        self._volume_button.setFlat(True)
        self._volume_button.clicked.connect(self.muteRequested.emit)
        self._volume_button.hide()
        self._expand_button = QPushButton(self)
        self._expand_button.setObjectName("videoControlButton")
        self._expand_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._expand_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._expand_button.setFlat(True)
        self._expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))
        self._expand_button.clicked.connect(self._toggle_expanded)
        self._expand_button.hide()
        self._sync_action_buttons()

    def set_preview(self, preview: ThemeLayoutPreview | None) -> None:
        if self._expanded:
            self._set_expanded(False)
        self._preview = preview
        self._selected_element = None
        self._element_hitboxes = []
        self._render_data = {}
        self._stop_idle_animation()
        self._stop_event_animation()
        self._pulsing_overlay_elements = frozenset()
        self._covered_selected_menu_elements = frozenset()
        self._pulsing_overlay_targets = {}
        self._floating_preview_dirty = False
        self._floating_preview_update_timer.stop()
        self.elementSelected.emit(None)
        if preview is None:
            self._expand_button.hide()
            self._stop_idle_animation()
        else:
            self._expand_button.show()
            self._restart_idle_animation()
            # Precompute pulsing overlay / covered selected menu element pairs
            selected_menu_logos = [
                e for e in preview.elements
                if e.kind == "menu" and e.selected and (e.slot_name or "").casefold() == "logo"
            ]
            pulsing: set[ThemePreviewElement] = set()
            covered: set[ThemePreviewElement] = set()
            pulsing_targets: dict[ThemePreviewElement, ThemePreviewElement] = {}
            for element in preview.elements:
                if element.kind not in {"image", "reloadable_image"}:
                    continue
                if (element.slot_name or "").casefold() != "logo":
                    continue
                if element.source_path:
                    continue
                if not element.idle_anim_sets:
                    continue
                for sel in selected_menu_logos:
                    if abs((element.x + element.width / 2.0) - (sel.x + sel.width / 2.0)) > 40.0:
                        continue
                    if abs((element.y + element.height / 2.0) - (sel.y + sel.height / 2.0)) > 40.0:
                        continue
                    if (element.layer or 0) >= (sel.layer or 0):
                        continue
                    pulsing.add(element)
                    covered.add(sel)
                    pulsing_targets[element] = sel
                    break
            self._pulsing_overlay_elements = frozenset(pulsing)
            self._covered_selected_menu_elements = frozenset(covered)
            self._pulsing_overlay_targets = pulsing_targets
        self._sync_action_buttons()
        self.update()

    def set_render_data(self, render_data: dict[ThemePreviewElement, ThemePreviewRenderData], *, transition: bool = False) -> None:
        should_manage_idle = self._animation_enabled and self._has_idle_animation() and not self._wheel_anim_active
        actual_transition = transition and bool(self._render_data)
        if actual_transition and should_manage_idle:
            self._stop_idle_animation()
        if actual_transition:
            self._transition_active = True
            self._transition_start_ms = time.monotonic() * 1000.0
            self._resume_idle_after_transition = should_manage_idle
            if not self._transition_timer.isActive():
                self._transition_timer.start()
        else:
            self._resume_idle_after_transition = False
        self._render_data = dict(render_data)
        if self._expanded:
            self._request_floating_preview_update(animation=actual_transition)
        self.update()

    def start_wheel_animation(
        self,
        slot_elements: list,
        logos: dict,
        sel_idx: int,
        start_game_0: int,
        advance_count: int,
        total_games: int,
        duration_ms: int,
        target_advance: int | None = None,
        extra_groups: list[tuple[list, dict[int, QPixmap], int]] | None = None,
    ) -> None:
        self._wheel_anim_slot_elements = slot_elements
        self._wheel_anim_logos = logos
        self._wheel_anim_sel_idx = sel_idx
        self._wheel_anim_extra_groups = list(extra_groups or [])
        self._wheel_anim_start_game_0 = start_game_0
        self._wheel_anim_advance_count = advance_count
        self._wheel_anim_target_advance = target_advance if target_advance is not None else advance_count
        self._wheel_anim_total_games = max(1, total_games)
        self._wheel_anim_duration_ms = max(1, duration_ms)
        self._wheel_anim_start_ms = time.monotonic() * 1000.0
        self._wheel_anim_last_emitted_index = start_game_0
        self._scroll_fade_timer.stop()
        self._scroll_fading_out = False
        self._scroll_anim_opacity = 1.0
        self._wheel_anim_active = True
        self._start_event_animation("menuscroll")
        self._stop_idle_animation(clear_values=False)
        self._wheel_anim_timer.start()

    def stop_wheel_animation(self) -> None:
        if self._wheel_anim_active:
            self._wheel_anim_active = False
            self._wheel_anim_timer.stop()
        self._scroll_fade_timer.stop()
        self._scroll_fading_out = False
        self._scroll_anim_opacity = 1.0
        self._wheel_anim_extra_groups = []
        self._wheel_anim_last_emitted_index = None
        self._stop_event_animation()
        self._start_event_animation("highlightenter")
        # Restart idle animation if the preview has idle-animated elements and animation is enabled
        preview = self._preview
        if preview is not None and self._animation_enabled and any(e.idle_anim_sets for e in preview.elements):
            self._restart_idle_animation()
        self.update()

    def _on_wheel_anim_tick(self) -> None:
        elapsed = time.monotonic() * 1000.0 - self._wheel_anim_start_ms
        if elapsed >= self._wheel_anim_duration_ms:
            self._wheel_anim_active = False
            self._wheel_anim_timer.stop()
            self._scroll_fading_out = True
            self._scroll_fade_start_ms = time.monotonic() * 1000.0
            self._scroll_fade_timer.start()
            if self._expanded:
                self._request_floating_preview_update(animation=True)
            self.update()
            self.wheelAnimationFinished.emit()
            return
        t = min(1.0, elapsed / self._wheel_anim_duration_ms)
        eased = 1.0 - (1.0 - t) ** 1.3
        current_index = (self._wheel_anim_start_game_0 + int(eased * self._wheel_anim_advance_count)) % max(1, self._wheel_anim_total_games)
        # Emit only when the currently highlighted scroll item changes.
        if current_index != self._wheel_anim_last_emitted_index:
            self._wheel_anim_last_emitted_index = current_index
            self.wheelAnimationIndexChanged.emit(current_index)
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    def _on_scroll_fade_tick(self) -> None:
        elapsed = time.monotonic() * 1000.0 - self._scroll_fade_start_ms
        self._scroll_anim_opacity = max(0.0, 1.0 - elapsed / self._scroll_fade_duration_ms)
        if self._scroll_anim_opacity <= 0.0:
            self._scroll_fade_timer.stop()
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    def _on_idle_anim_tick(self) -> None:
        preview = self._preview
        if preview is None:
            self._idle_anim_timer.stop()
            return
        elapsed_ms = time.monotonic() * 1000.0 - self._idle_anim_start_ms
        new_alphas: dict[ThemePreviewElement, float] = {}
        new_values: dict[ThemePreviewElement, dict[str, float]] = {}
        for element in preview.elements:
            if not element.idle_anim_sets:
                continue
            total_ms = sum(s[0] for s in element.idle_anim_sets) * 1000.0
            if total_ms <= 0:
                continue
            t_secs = (elapsed_ms % total_ms) / 1000.0
            cursor = 0.0
            current_values: dict[str, float] = {
                "alpha": element.alpha if element.alpha is not None else 1.0,
                "width": element.width,
                "height": element.height,
            }
            if element.max_width is not None:
                current_values["maxwidth"] = element.max_width
            if element.max_height is not None:
                current_values["maxheight"] = element.max_height
            for duration, steps in element.idle_anim_sets:
                if t_secs < cursor + duration:
                    set_t = (t_secs - cursor) / duration if duration > 0 else 1.0
                    for prop, from_val, to_val, algorithm in steps:
                        eased_t = self._idle_animation_progress(set_t, algorithm)
                        current_values[prop] = from_val + (to_val - from_val) * eased_t
                    break
                for prop, _, to_val, _ in steps:
                    current_values[prop] = to_val
                cursor += duration
            else:
                # Past all sets: use final value of the last step per property
                last_steps = element.idle_anim_sets[-1][1]
                for prop, _, to_val, _ in last_steps:
                    current_values[prop] = to_val
            new_values[element] = current_values
            new_alphas[element] = current_values.get("alpha", 1.0)
        self._idle_anim_alphas = new_alphas
        self._idle_anim_values = new_values
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    def _start_event_animation(self, event_name: str) -> None:
        preview = self._preview
        if preview is None or not self._animation_enabled:
            self._stop_event_animation()
            return
        normalized = event_name.casefold()
        has_matching_sets = False
        for element in preview.elements:
            for candidate_name, menu_index_expr, sets in element.event_anim_sets:
                if candidate_name != normalized:
                    continue
                if not self._menu_index_matches_preview_state(menu_index_expr, element):
                    continue
                if sets:
                    has_matching_sets = True
                    break
            if has_matching_sets:
                break
        if not has_matching_sets:
            self._stop_event_animation()
            return
        self._event_anim_name = normalized
        self._event_anim_start_ms = time.monotonic() * 1000.0
        self._event_anim_values = {}
        self._on_event_anim_tick()
        if not self._event_anim_timer.isActive():
            self._event_anim_timer.start()

    def _stop_event_animation(self) -> None:
        self._event_anim_timer.stop()
        self._event_anim_name = None
        self._event_anim_values = {}

    def _on_event_anim_tick(self) -> None:
        preview = self._preview
        event_name = self._event_anim_name
        if preview is None or not event_name:
            self._stop_event_animation()
            return
        elapsed_ms = time.monotonic() * 1000.0 - self._event_anim_start_ms
        new_values: dict[ThemePreviewElement, dict[str, float]] = {}
        any_active = False
        for element in preview.elements:
            matching_sets: tuple[tuple[float, tuple[tuple[str, float | None, float | None, str], ...]], ...] | None = None
            for candidate_name, menu_index_expr, sets in element.event_anim_sets:
                if candidate_name != event_name:
                    continue
                if not self._menu_index_matches_preview_state(menu_index_expr, element):
                    continue
                matching_sets = sets
                break
            if not matching_sets:
                continue
            total_ms = sum(duration for duration, _ in matching_sets) * 1000.0
            current_values: dict[str, float] = {
                "alpha": element.alpha if element.alpha is not None else 1.0,
                "width": element.width,
                "height": element.height,
            }
            if element.max_width is not None:
                current_values["maxwidth"] = element.max_width
            if element.max_height is not None:
                current_values["maxheight"] = element.max_height
            if total_ms <= 0:
                for _, steps in matching_sets:
                    for prop, _, to_val, _ in steps:
                        if prop == "nop" or to_val is None:
                            continue
                        current_values[prop] = to_val
                new_values[element] = current_values
                continue

            t_secs = elapsed_ms / 1000.0
            cursor = 0.0
            for duration, steps in matching_sets:
                if t_secs < cursor + duration:
                    set_t = (t_secs - cursor) / duration if duration > 0 else 1.0
                    for prop, from_val, to_val, algorithm in steps:
                        if prop == "nop":
                            continue
                        if from_val is None and to_val is None:
                            continue
                        if to_val is None:
                            continue
                        start_val = from_val if from_val is not None else current_values.get(prop, to_val)
                        eased_t = self._idle_animation_progress(set_t, algorithm)
                        current_values[prop] = start_val + (to_val - start_val) * eased_t
                    any_active = True
                    break
                for prop, _, to_val, _ in steps:
                    if prop == "nop" or to_val is None:
                        continue
                    current_values[prop] = to_val
                cursor += duration
            else:
                last_steps = matching_sets[-1][1]
                for prop, _, to_val, _ in last_steps:
                    if prop == "nop" or to_val is None:
                        continue
                    current_values[prop] = to_val
            new_values[element] = current_values
        self._event_anim_values = new_values
        if not any_active:
            self._event_anim_timer.stop()
            self._event_anim_name = None
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    def _idle_animation_progress(self, t: float, algorithm: str | None) -> float:
        t = max(0.0, min(1.0, t))
        key = (algorithm or "linear").replace("_", "").replace("-", "").casefold()
        if key == "easeinquadratic":
            return t * t
        if key == "easeoutquadratic":
            return 1.0 - ((1.0 - t) * (1.0 - t))
        if key == "easeinoutquadratic":
            if t < 0.5:
                return 2.0 * t * t
            return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0
        return t

    def _has_idle_animation(self) -> bool:
        preview = self._preview
        return preview is not None and any(
            e.idle_anim_sets or (
                e.kind == "reloadable_panning_image"
                and (
                    (e.pan_speed is not None and e.pan_speed > 0)
                    or (e.pan_zoom_speed is not None and e.pan_zoom_speed > 0)
                )
            )
            for e in preview.elements
        )

    def _stop_idle_animation(self, *, clear_values: bool = True) -> None:
        self._idle_anim_timer.stop()
        if clear_values:
            self._idle_anim_alphas = {}
            self._idle_anim_values = {}
        self._resume_idle_after_transition = False

    def _restart_idle_animation(self) -> None:
        if not self._animation_enabled or not self._has_idle_animation():
            self._stop_idle_animation()
            return
        self._idle_anim_alphas = {}
        self._idle_anim_values = {}
        self._idle_anim_start_ms = time.monotonic() * 1000.0
        self._on_idle_anim_tick()
        if not self._idle_anim_timer.isActive():
            self._idle_anim_timer.start()

    def _draw_animated_wheel(self, painter: QPainter, fitted: QRectF, scale_x: float, scale_y: float) -> None:
        elapsed = time.monotonic() * 1000.0 - self._wheel_anim_start_ms
        t = min(1.0, elapsed / self._wheel_anim_duration_ms)
        eased = 1.0 - (1.0 - t) ** 1.3  # very mild ease-out
        scroll_pos = eased * self._wheel_anim_advance_count
        int_s = int(scroll_pos)
        frac = scroll_pos - int_s
        total = self._wheel_anim_total_games
        start_game = self._wheel_anim_start_game_0
        groups = [(self._wheel_anim_slot_elements, self._wheel_anim_logos, self._wheel_anim_sel_idx)] + list(self._wheel_anim_extra_groups)
        for elements, pixmaps, sel_idx in groups:
            n = len(elements)
            if n == 0:
                continue
            for k in range(-(sel_idx + 1), (n - sel_idx + 1)):
                game_idx = (start_game + int_s + k) % total
                pixmap = pixmaps.get(game_idx)
                if pixmap is None:
                    continue
                v = sel_idx + k - frac
                if v < -0.5 or v > n - 0.5:
                    continue
                floor_idx = int(v)
                sub_frac = v - floor_idx
                if 0 <= floor_idx < n - 1:
                    ea = elements[floor_idx]
                    eb = elements[floor_idx + 1]
                    ex = ea.x + (eb.x - ea.x) * sub_frac
                    ey = ea.y + (eb.y - ea.y) * sub_frac
                    ew = ea.width + (eb.width - ea.width) * sub_frac
                    eh = ea.height + (eb.height - ea.height) * sub_frac
                    angle_a = ea.angle or 0.0
                    angle_b = eb.angle or 0.0
                    eangle = angle_a + (angle_b - angle_a) * sub_frac
                    alpha_a = ea.alpha if ea.alpha is not None else 1.0
                    alpha_b = eb.alpha if eb.alpha is not None else 1.0
                    ealpha = alpha_a + (alpha_b - alpha_a) * sub_frac
                elif floor_idx >= n - 1:
                    ea = elements[n - 1]
                    ex, ey, ew, eh = ea.x, ea.y, ea.width, ea.height
                    eangle = ea.angle or 0.0
                    ealpha = ea.alpha if ea.alpha is not None else 1.0
                else:
                    ea = elements[0]
                    ex, ey, ew, eh = ea.x, ea.y, ea.width, ea.height
                    eangle = ea.angle or 0.0
                    ealpha = ea.alpha if ea.alpha is not None else 1.0
                draw_rect = QRectF(
                    fitted.x() + ex * scale_x,
                    fitted.y() + ey * scale_y,
                    max(2.0, ew * scale_x),
                    max(2.0, eh * scale_y),
                )
                visible_rect = draw_rect.intersected(fitted)
                if visible_rect.isEmpty():
                    continue
                self._draw_wheel_logo(painter, pixmap, ea, draw_rect, visible_rect, eangle, ealpha)

    def _draw_wheel_logo(
        self,
        painter: QPainter,
        pixmap: QPixmap,
        element: ThemePreviewElement,
        draw_rect: QRectF,
        clip_rect: QRectF,
        angle: float,
        opacity: float = 1.0,
    ) -> None:
        image_rect = draw_rect.adjusted(1, 1, -1, -1)
        if image_rect.width() <= 1 or image_rect.height() <= 1:
            return
        if opacity <= 0.001:
            return
        if self._should_expand_width_constrained_media(element):
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
        elif self._should_fit_media_rect(element):
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        else:
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
        if abs(angle) > 0.1:
            scaled = self._scaled_rotated_pixmap(pixmap, image_rect, aspect_mode, angle)
        else:
            scaled = pixmap.scaled(
                image_rect.size().toSize(),
                aspect_mode,
                Qt.TransformationMode.SmoothTransformation,
            )
        sx = image_rect.x() + (image_rect.width() - scaled.width()) / 2
        sy = image_rect.y() + (image_rect.height() - scaled.height()) / 2
        painter.save()
        painter.setClipRect(clip_rect)
        if opacity < 1.0:
            painter.setOpacity(max(0.0, min(1.0, opacity)))
        if abs(angle) > 0.1:
            center = image_rect.center()
            painter.translate(center)
            painter.rotate(angle)
            painter.translate(-center)
        painter.drawPixmap(int(sx), int(sy), scaled)
        painter.restore()

    def select_element(self, element: ThemePreviewElement | None) -> None:
        self._selected_element = element
        if self._expanded:
            self._request_floating_preview_update(immediate=True)
        self.update()

    def set_show_wireframes(self, show_wireframes: bool) -> None:
        self._show_wireframes = show_wireframes
        if self._expanded:
            self._request_floating_preview_update(immediate=True)
        self.update()

    def set_show_media(self, show_media: bool) -> None:
        self._show_media = show_media
        if self._expanded:
            self._request_floating_preview_update(immediate=True)
        self.update()

    def set_show_text(self, show_text: bool) -> None:
        self._show_text = show_text
        if self._expanded:
            self._request_floating_preview_update(immediate=True)
        self.update()

    def set_animation_controls(self, *, can_play: bool, can_mute: bool, is_playing: bool, is_muted: bool) -> None:
        self._controls_enabled = can_play
        self._mute_enabled = can_mute
        self._animation_enabled = is_playing
        self._muted = is_muted
        self._sync_action_buttons()
        if not is_playing:
            self._stop_idle_animation()
            self.update()
            return
        if self._wheel_anim_active:
            return
        if self._transition_active:
            self._resume_idle_after_transition = self._has_idle_animation()
            return
        if self._has_idle_animation() and not self._idle_anim_timer.isActive():
            self._restart_idle_animation()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_action_buttons()
        if self._expanded:
            self._request_floating_preview_update(immediate=True)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._attach_window_filter()
        if self._preview is not None and not self._expanded:
            self._expand_button.show()
        self._sync_action_buttons()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched == self._window_filter_target and self._expanded and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            self._request_floating_preview_update(immediate=True)
        elif self._expanded and self._app_filter_target is not None and event.type() == QEvent.Type.MouseButtonPress:
            self._handle_global_mouse_press(event)
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        self._paint_preview(painter, QRectF(self.rect()), record_hitboxes=True)
        if self._transition_active:
            elapsed_ms = time.monotonic() * 1000.0 - self._transition_start_ms
            t = min(1.0, elapsed_ms / max(1, self._transition_duration_ms))
            if t >= 1.0:
                self._transition_active = False
                self._transition_timer.stop()
                if self._resume_idle_after_transition:
                    self._resume_idle_after_transition = False
                    self._restart_idle_animation()
            else:
                # ease-in cubic: new content fades in from the background colour
                eased = t ** 3
                overlay_alpha = int(255 * (1.0 - eased))
                painter.fillRect(self.rect(), QColor(0x17, 0x17, 0x17, overlay_alpha))

    def _paint_preview(self, painter: QPainter, target_rect: QRectF, *, record_hitboxes: bool) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background_rect = target_rect if not self._expanded else self._preview_content_rect(target_rect)
        painter.fillRect(background_rect, QColor("#171717"))

        canvas_rect = self._preview_content_rect(target_rect)
        if canvas_rect.width() <= 0 or canvas_rect.height() <= 0:
            return

        preview = self._preview
        if preview is None:
            self._draw_empty_state(painter, canvas_rect, "Select a theme to inspect its layout preview.")
            return

        fitted = self._preview_canvas_rect(preview, canvas_rect)

        painter.setPen(QPen(QColor("#404040"), 1.0))
        painter.setBrush(QColor("#0d0d0d"))
        painter.drawRoundedRect(fitted, 10, 10)

        if preview.error and not preview.elements:
            self._draw_empty_state(painter, fitted.adjusted(12, 12, -12, -12), preview.error)
            return

        aspect_width = max(1.0, preview.canvas_width)
        aspect_height = max(1.0, preview.canvas_height)
        scale_x = fitted.width() / aspect_width
        scale_y = fitted.height() / aspect_height
        label_font = QFont(self.font())
        label_font.setPointSizeF(max(8.0, label_font.pointSizeF() - 1.0))
        painter.setFont(label_font)
        metrics = painter.fontMetrics()
        effective_animation_values = {
            element: self._effective_preview_animation_values(element)
            for element in preview.elements
        }
        display_rects = {
            element: self._element_display_rect(
                element,
                fitted,
                scale_x,
                scale_y,
                self._formatted_element_text(element, self._render_data[element].text)
                if element in self._render_data and self._render_data[element].text
                else None,
                render_data=self._render_data.get(element),
                animated_values=effective_animation_values.get(element),
            )
            for element in preview.elements
        }
        id_to_element = {e.elem_id: e for e in preview.elements if e.elem_id}
        if record_hitboxes:
            self._element_hitboxes = []
        for element in self._ordered_elements(preview.elements):
            if self._wheel_anim_active and element.kind == "menu":
                continue
            if self._wheel_anim_active and element in self._pulsing_overlay_elements:
                continue
            color = QColor(self._COLOR_MAP.get(element.kind, QColor("#9f9f9f")))
            render_data = self._render_data.get(element)
            display_text = self._formatted_element_text(element, render_data.text) if render_data is not None and render_data.text else None
            scaled_rect = display_rects.get(element) or self._element_display_rect(
                element,
                fitted,
                scale_x,
                scale_y,
                display_text,
                render_data=render_data,
                animated_values=effective_animation_values.get(element),
            )
            visible_rect = scaled_rect.intersected(fitted)
            if visible_rect.isEmpty():
                continue
            if element in self._pulsing_overlay_elements:
                target_element = self._pulsing_overlay_targets.get(element)
                target_rect = display_rects.get(target_element) if target_element is not None else None
                if target_rect is not None and not self._pulse_overlay_is_visually_distinct(scaled_rect, target_rect):
                    continue
            element_path = self._element_hitbox_path(element, scaled_rect, fitted, scale_x, scale_y)
            if record_hitboxes:
                self._element_hitboxes.append((element_path, element))

            fill = QColor(color)
            is_selected = self._selected_element == element
            fill.setAlpha(24 if render_data and render_data.pixmap is not None and self._show_media else (72 if is_selected else 42))
            border = QPen(color, 2.6 if is_selected else 1.4)
            # Reflection: if this element mirrors another element's pixmap.
            reflection_drawn = False
            if self._show_media and element.reflection_id:
                source_element = id_to_element.get(element.reflection_id)
                if source_element is not None:
                    source_data = self._render_data.get(source_element)
                    if source_data is not None and source_data.pixmap is not None and not source_data.pixmap.isNull():
                        self._draw_reflection_pixmap(painter, source_data.pixmap, element, visible_rect, scaled_rect)
                        reflection_drawn = True
            if self._show_media and not reflection_drawn and render_data is not None and render_data.pixmap is not None and not render_data.pixmap.isNull():
                is_scroll_fading = self._scroll_fading_out and element.alpha == 0.0 and element.kind not in {"menu", "video", "reloadable_video"}
                base_opacity = max(0.0, min(1.0, element.alpha if element.alpha is not None else 1.0))
                # Determine effective opacity: idle animation override > base alpha, with scroll fade applied multiplicatively.
                animated_alpha = effective_animation_values.get(element, {}).get("alpha")
                if animated_alpha is not None:
                    effective_opacity = max(0.0, min(1.0, animated_alpha))
                else:
                    effective_opacity = base_opacity
                if is_scroll_fading:
                    effective_opacity *= self._scroll_anim_opacity
                if effective_opacity < 1.0:
                    painter.setOpacity(effective_opacity)
                if element.transform_points and len(element.transform_points) >= 4:
                    self._draw_transformed_pixmap(painter, render_data.pixmap, element, fitted, scale_x, scale_y)
                else:
                    self._draw_rect_pixmap(painter, render_data.pixmap, element, visible_rect, scaled_rect)
                if effective_opacity < 1.0:
                    painter.setOpacity(1.0)
            if self._show_wireframes:
                painter.setPen(border)
                painter.setBrush(fill)
                painter.drawPath(element_path)

            if self._show_text and display_text:
                text_alpha = effective_animation_values.get(element, {}).get("alpha")
                if text_alpha is None:
                    text_alpha = element.alpha if element.alpha is not None else 1.0
                text_alpha = max(0.0, min(1.0, text_alpha))
                if text_alpha > 0.0:
                    if text_alpha < 1.0:
                        painter.setOpacity(text_alpha)
                    self._draw_element_text(painter, element, visible_rect, scaled_rect, fitted, display_text, scale_x, scale_y)
                    if text_alpha < 1.0:
                        painter.setOpacity(1.0)

            if not self._show_wireframes or visible_rect.width() < 42:
                continue
            label_text = metrics.elidedText(element.label, Qt.TextElideMode.ElideRight, max(34, int(visible_rect.width() - 18)))
            label_width = min(visible_rect.width() - 10.0, metrics.horizontalAdvance(label_text) + 14.0)
            if label_width <= 22:
                continue
            label_height = metrics.height() + 4.0
            label_y = max(fitted.top() + 2.0, visible_rect.top() - label_height / 2.0)
            label_rect = QRectF(visible_rect.left() + 6.0, label_y, label_width, label_height)
            painter.setPen(border)
            painter.setBrush(QColor("#111111"))
            painter.drawRoundedRect(label_rect, 4, 4)
            painter.drawText(label_rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label_text)

        if self._wheel_anim_active:
            self._draw_animated_wheel(painter, fitted, scale_x, scale_y)

    def _pulse_overlay_is_visually_distinct(self, overlay_rect: QRectF, base_rect: QRectF, *, tolerance: float | None = None) -> bool:
        if overlay_rect.isEmpty() or base_rect.isEmpty():
            return True
        effective_tolerance = tolerance
        if effective_tolerance is None:
            effective_tolerance = max(1.0, min(base_rect.width(), base_rect.height()) * 0.02)
        if overlay_rect.left() < base_rect.left() - effective_tolerance:
            return True
        if overlay_rect.top() < base_rect.top() - effective_tolerance:
            return True
        if overlay_rect.right() > base_rect.right() + effective_tolerance:
            return True
        if overlay_rect.bottom() > base_rect.bottom() + effective_tolerance:
            return True
        return False

    def _active_preview_menu_index(self) -> int:
        preview = self._preview
        if preview is None:
            return 0
        return 1 if preview.selected_collection else 0

    def _menu_index_matches_preview_state(self, expression: str | None, element: ThemePreviewElement) -> bool:
        if not expression:
            return True
        expr = expression.strip()
        if not expr:
            return True
        active_index = self._active_preview_menu_index()
        if expr == "i":
            return element.kind == "menu" and element.selected
        if expr.startswith("!"):
            try:
                return active_index != int(expr[1:])
            except ValueError:
                return False
        if expr.startswith(">"):
            try:
                return active_index > int(expr[1:])
            except ValueError:
                return False
        if expr.startswith("<"):
            try:
                return active_index < int(expr[1:])
            except ValueError:
                return False
        try:
            return active_index == int(expr)
        except ValueError:
            return False

    def _preview_state_values_for_element(self, element: ThemePreviewElement) -> dict[str, float]:
        if not element.event_anim_targets:
            return {}
        event_order = ("menuscroll",) if self._wheel_anim_active else ("menuenter", "highlightenter")
        values: dict[str, float] = {}
        for desired_event in event_order:
            for event_name, menu_index_expr, steps in element.event_anim_targets:
                if event_name != desired_event:
                    continue
                if not self._menu_index_matches_preview_state(menu_index_expr, element):
                    continue
                for prop_name, to_value in steps:
                    values[prop_name] = to_value
        return values

    def _effective_preview_animation_values(self, element: ThemePreviewElement) -> dict[str, float]:
        values = self._preview_state_values_for_element(element)
        event_values = self._event_anim_values.get(element)
        if event_values:
            values.update(event_values)
        idle_values = self._idle_anim_values.get(element)
        if idle_values:
            values.update(idle_values)
        return values

    def _soften_pulse_overlay_pixmap(self, pixmap: QPixmap) -> QPixmap:
        if pixmap.isNull():
            return pixmap
        width = pixmap.width()
        height = pixmap.height()
        if width < 8 or height < 8:
            return pixmap
        reduced = pixmap.scaled(
            max(1, int(round(width * 0.88))),
            max(1, int(round(height * 0.88))),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if reduced.isNull():
            return pixmap
        softened = reduced.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return softened if not softened.isNull() else pixmap

    def _draw_element_text(self, painter: QPainter, element: ThemePreviewElement, visible_rect: QRectF, draw_rect: QRectF, canvas_rect: QRectF, text: str, scale_x: float, scale_y: float) -> None:
        if visible_rect.width() < 1 or visible_rect.height() < 1:
            return
        painter.save()
        text_font = self._preview_font_for_element(element, scale_x, scale_y)
        painter.setFont(text_font)
        painter.setPen(self._text_color_for_element(element))
        scrolling = element.kind in {"scrolling_text", "reloadable_scrolling_text"}
        constrained_width = (not element.explicit_width) and element.max_width is not None
        constrained_height = (not element.explicit_height) and element.max_height is not None
        if not element.explicit_width and not element.explicit_height and not constrained_width and not constrained_height:
            # Natural (unsized) text: clip to the canvas boundary so off-canvas portions
            # (e.g. elements at y=-15 peeking above the screen top) are correctly hidden,
            # matching hardware behaviour.  Use canvas_rect rather than visible_rect because
            # visible_rect is sized from default element dimensions which may be smaller than
            # the actual rendered font.
            painter.setClipRect(canvas_rect)
            painter.drawText(self._natural_text_draw_point(text_font, text, draw_rect), text)
            painter.restore()
            return
        if draw_rect.width() <= 4 or draw_rect.height() <= 4:
            painter.restore()
            return
        flags = self._text_alignment_flags(element)
        if (element.explicit_width or constrained_width) and (element.explicit_height or constrained_height):
            if scrolling and (element.scroll_direction or "").casefold() == "vertical":
                self._draw_scrolling_multiline_text(painter, element, visible_rect, draw_rect, text, scale_x, scale_y)
                painter.restore()
                return
            flags |= Qt.TextFlag.TextWordWrap
            # Clip to the canvas-intersected area so off-canvas portions are hidden,
            # but draw text at the true element rect so positioning matches hardware.
            painter.setClipRect(visible_rect)
            painter.drawText(draw_rect, flags, text)
        elif element.explicit_width or constrained_width:
            if scrolling and (element.scroll_direction or "").casefold() == "horizontal":
                self._draw_scrolling_singleline_text(painter, element, visible_rect, draw_rect, text, scale_x, scale_y)
                painter.restore()
                return
            # Single-line: clip at element right minus small right padding so long text
            # is hard-cut, not ellipsized. Expand height to avoid vertical clip issues.
            pad = max(4.0, 8.0 * scale_x)
            font_height = QFontMetricsF(text_font).height()
            clip = QRectF(visible_rect.left(), visible_rect.top() - font_height, draw_rect.width() - pad, font_height * 3)
            painter.setClipRect(clip)
            painter.drawText(self._natural_text_draw_point(text_font, text, draw_rect), text)
        else:
            painter.setClipRect(visible_rect)
            painter.drawText(draw_rect, flags, text)
        painter.restore()

    def _scroll_cycle_offset(self, overflow: float, element: ThemePreviewElement) -> float:
        if overflow <= 0.0 or not self._animation_enabled:
            return 0.0
        start_delay = max(0.0, element.scroll_start_time or 0.0)
        end_delay = max(0.0, element.scroll_end_time or 0.0)
        speed = max(1.0, element.scroll_speed or 40.0)
        travel_duration = overflow / speed
        cycle = start_delay + travel_duration + end_delay
        if cycle <= 0.0:
            return 0.0
        epoch_ms = self._idle_anim_start_ms or (time.monotonic() * 1000.0)
        elapsed = max(0.0, (time.monotonic() * 1000.0 - epoch_ms) / 1000.0)
        phase = elapsed % cycle
        if phase <= start_delay:
            return 0.0
        if phase >= start_delay + travel_duration:
            return overflow
        return min(overflow, (phase - start_delay) * speed)

    def _draw_scrolling_singleline_text(
        self,
        painter: QPainter,
        element: ThemePreviewElement,
        visible_rect: QRectF,
        draw_rect: QRectF,
        text: str,
        scale_x: float,
        scale_y: float,
    ) -> None:
        text_font = painter.font()
        natural_point = self._natural_text_draw_point(text_font, text, draw_rect)
        natural_bounds = self._natural_text_bounds(text_font, text)
        pad = max(4.0, 8.0 * scale_x)
        clip_width = max(1.0, draw_rect.width() - pad)
        overflow = max(0.0, natural_bounds.width() - clip_width)
        font_height = QFontMetricsF(text_font).height()
        clip = QRectF(visible_rect.left(), visible_rect.top() - font_height, clip_width, font_height * 3)
        painter.setClipRect(clip)
        offset = self._scroll_cycle_offset(overflow, element)
        painter.drawText(QPointF(natural_point.x() - offset, natural_point.y()), text)

    def _draw_scrolling_multiline_text(
        self,
        painter: QPainter,
        element: ThemePreviewElement,
        visible_rect: QRectF,
        draw_rect: QRectF,
        text: str,
        scale_x: float,
        scale_y: float,
    ) -> None:
        text_font = painter.font()
        metrics = QFontMetricsF(text_font)
        flags = self._text_alignment_flags(element) | Qt.TextFlag.TextWordWrap
        layout_rect = QRectF(0.0, 0.0, draw_rect.width(), max(draw_rect.height(), 10000.0))
        text_bounds = metrics.boundingRect(layout_rect.toRect(), int(flags), text)
        content_height = max(draw_rect.height(), float(text_bounds.height()))
        overflow = max(0.0, content_height - draw_rect.height())
        painter.setClipRect(visible_rect)
        offset = self._scroll_cycle_offset(overflow, element)
        scroll_rect = QRectF(draw_rect.left(), draw_rect.top() - offset, draw_rect.width(), content_height)
        painter.drawText(scroll_rect, flags, text)

    def _draw_empty_state(self, painter: QPainter, rect: QRectF, message: str) -> None:
        painter.setPen(QColor("#8a8a8a"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, message)

    def _preview_content_rect(self, target_rect: QRectF) -> QRectF:
        rect = QRectF(target_rect).adjusted(18, 18, -18, -18)
        reserved = self._action_row_reserved_height()
        if reserved > 0:
            rect.adjust(0, 0, 0, -reserved)
        return rect

    def _action_row_reserved_height(self) -> float:
        if self._preview is None:
            return 0.0
        if self._expanded:
            return 0.0
        buttons = [
            self._previous_button,
            self._play_button,
            self._next_button,
            self._volume_button,
            self._expand_button,
        ]
        heights = [button.height() for button in buttons if button is not None]
        if not heights:
            return 0.0
        return max(heights) + (self._action_padding * 2) + 6.0

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        selected_element = None
        click_pos = event.position()
        for path, element in reversed(self._element_hitboxes):
            if path.contains(click_pos):
                selected_element = element
                break
        self._selected_element = selected_element
        self.elementSelected.emit(selected_element)
        self.update()
        event.accept()

    def _preview_canvas_rect(self, preview: ThemeLayoutPreview, bounds: QRectF) -> QRectF:
        aspect_width = max(1.0, preview.canvas_width)
        aspect_height = max(1.0, preview.canvas_height)
        target_aspect = aspect_width / aspect_height
        fitted = QRectF(bounds)
        if fitted.width() / fitted.height() > target_aspect:
            scaled_width = fitted.height() * target_aspect
            fitted.setX(fitted.x() + (fitted.width() - scaled_width) / 2.0)
            fitted.setWidth(scaled_width)
        else:
            scaled_height = fitted.width() / target_aspect
            fitted.setY(fitted.y() + (fitted.height() - scaled_height) / 2.0)
            fitted.setHeight(scaled_height)
        return fitted

    def _ordered_elements(self, elements: tuple[ThemePreviewElement, ...]) -> list[ThemePreviewElement]:
        with_layers = [element for element in elements if element.layer is not None]
        without_layers = [element for element in elements if element.layer is None]
        ordered = sorted(with_layers, key=lambda element: (element.layer or 0, element.width * element.height, element.label.casefold()))
        ordered.extend(sorted(without_layers, key=lambda element: (-(element.width * element.height), element.label.casefold())))
        return ordered

    def _element_display_rect(
        self,
        element: ThemePreviewElement,
        fitted: QRectF,
        scale_x: float,
        scale_y: float,
        display_text: str | None,
        *,
        render_data: ThemePreviewRenderData | None = None,
        animated_values: dict[str, float] | None = None,
    ) -> QRectF:
        if not display_text or element.kind not in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"}:
            animated_rect = self._media_display_rect(
                element,
                fitted,
                scale_x,
                scale_y,
                render_data,
                animated_values,
            )
            if animated_rect is not None:
                return animated_rect
            return QRectF(
                fitted.x() + (element.x * scale_x),
                fitted.y() + (element.y * scale_y),
                max(2.0, element.width * scale_x),
                max(2.0, element.height * scale_y),
            )
        font = self._preview_font_for_element(element, scale_x, scale_y)
        raw_layout = self._retrofe_text_layout(element, display_text, scale_y)
        tight_bounds = self._natural_text_bounds(font, display_text)
        natural_width = raw_layout["width"] if raw_layout is not None else tight_bounds.width()
        natural_height = raw_layout["height"] if raw_layout is not None else tight_bounds.height()
        width = max(2.0, element.width * scale_x) if element.explicit_width else max(2.0, float(natural_width))
        height = max(2.0, element.height * scale_y) if element.explicit_height else max(2.0, float(natural_height))
        if not element.explicit_width and element.max_width is not None:
            width = max(2.0, element.max_width * scale_x)
        if not element.explicit_height and element.max_height is not None:
            height = max(2.0, element.max_height * scale_y)
        anchor_x = element.anchor_x
        anchor_y = element.anchor_y
        if anchor_x is None:
            anchor_x = self._derived_text_anchor(element.x, element.width, element.x_origin)
        if anchor_y is None:
            anchor_y = self._derived_text_anchor(element.y, element.height, element.y_origin)
        if anchor_x is None or anchor_y is None:
            return QRectF(
                fitted.x() + (element.x * scale_x),
                fitted.y() + (element.y * scale_y),
                width,
                height,
            )
        x = self._anchored_coordinate(fitted.x() + (anchor_x * scale_x), width, element.x_origin)
        y = self._anchored_coordinate(fitted.y() + (anchor_y * scale_y), height, element.y_origin)
        rect = QRectF(x, y, width, height)
        return self._adjust_natural_text_rect(element, rect, scale_x, scale_y)

    def _media_display_rect(
        self,
        element: ThemePreviewElement,
        fitted: QRectF,
        scale_x: float,
        scale_y: float,
        render_data: ThemePreviewRenderData | None,
        animated_values: dict[str, float] | None,
    ) -> QRectF | None:
        if render_data is None or render_data.pixmap is None or render_data.pixmap.isNull():
            return None
        if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"}:
            return None
        animated_values = animated_values or {}
        animated_width = animated_values.get("width")
        animated_height = animated_values.get("height")
        animated_max_width = animated_values.get("maxwidth")
        animated_max_height = animated_values.get("maxheight")
        has_animation_sizing = (
            animated_width is None
            and animated_height is None
            and animated_max_width is None
            and animated_max_height is None
        )
        has_static_constraint = any(
            value is not None
            for value in (element.min_width, element.min_height, element.max_width, element.max_height)
        )
        if has_animation_sizing and element.explicit_width and element.explicit_height and not has_static_constraint:
            return None

        intrinsic_width = float(render_data.pixmap.width())
        intrinsic_height = float(render_data.pixmap.height())
        if intrinsic_width <= 0 or intrinsic_height <= 0:
            return None

        explicit_width = element.explicit_width or animated_width is not None
        explicit_height = element.explicit_height or animated_height is not None
        width_value = animated_width if animated_width is not None else element.width
        height_value = animated_height if animated_height is not None else element.height

        width_px = width_value * scale_x if explicit_width else None
        height_px = height_value * scale_y if explicit_height else None

        if not explicit_width and not explicit_height:
            # Unsized media lives in layout-space pixels, so intrinsic media dimensions
            # still need to be scaled into the current preview canvas. Treating intrinsic
            # pixels as final widget pixels makes the same asset render at different
            # relative sizes in embedded vs expanded preview.
            box_width = intrinsic_width * scale_x
            box_height = intrinsic_height * scale_y
        elif explicit_width and not explicit_height:
            box_width = max(1.0, width_px or intrinsic_width)
            box_height = intrinsic_height * box_width / intrinsic_width
        elif explicit_height and not explicit_width:
            box_height = max(1.0, height_px or intrinsic_height)
            box_width = intrinsic_width * box_height / intrinsic_height
        else:
            box_width = max(1.0, width_px or intrinsic_width)
            box_height = max(1.0, height_px or intrinsic_height)

        box_width, box_height = self._apply_media_constraints(
            box_width,
            box_height,
            min_width=(element.min_width * scale_x) if element.min_width is not None else None,
            min_height=(element.min_height * scale_y) if element.min_height is not None else None,
            max_width=(animated_max_width * scale_x) if animated_max_width is not None else ((element.max_width * scale_x) if element.max_width is not None else None),
            max_height=(animated_max_height * scale_y) if animated_max_height is not None else ((element.max_height * scale_y) if element.max_height is not None else None),
        )

        base_rect = QRectF(
            fitted.x() + (element.x * scale_x),
            fitted.y() + (element.y * scale_y),
            max(2.0, element.width * scale_x),
            max(2.0, element.height * scale_y),
        )
        anchor_x = self._derived_rect_anchor(base_rect, element.x_origin, axis="x")
        anchor_y = self._derived_rect_anchor(base_rect, element.y_origin, axis="y")
        x = self._anchored_coordinate(anchor_x, box_width, element.x_origin)
        y = self._anchored_coordinate(anchor_y, box_height, element.y_origin)
        return QRectF(x, y, max(2.0, box_width), max(2.0, box_height))

    def _apply_media_constraints(
        self,
        width: float,
        height: float,
        *,
        min_width: float | None,
        min_height: float | None,
        max_width: float | None,
        max_height: float | None,
    ) -> tuple[float, float]:
        if width <= 0 or height <= 0:
            return (width, height)

        if height < (min_height or 0) or width < (min_width or 0):
            scale_h = (min_height / height) if min_height is not None and min_height > 0 else 0.0
            scale_w = (min_width / width) if min_width is not None and min_width > 0 else 0.0
            if min_width is not None and width >= min_width and min_height is not None and height < min_height:
                height = min_height
            elif min_height is not None and min_width is not None and width < min_width and height >= min_height:
                height = scale_w * height
                width = min_width
            elif scale_h > 0 or scale_w > 0:
                if scale_h > scale_w:
                    width = min_width if min_width is not None else width
                    height *= scale_h
                else:
                    width *= scale_h if scale_h > 0 else scale_w
                    height = min_height if min_height is not None and scale_h > scale_w else height * scale_w

        if width > (max_width or float("inf")) or height > (max_height or float("inf")):
            scale_h = (max_height / height) if max_height is not None and max_height > 0 else float("inf")
            scale_w = (max_width / width) if max_width is not None and max_width > 0 else float("inf")
            if max_width is not None and width <= max_width and max_height is not None and height > max_height:
                width = scale_h * width
                height = max_height
            elif max_height is not None and height <= max_height and max_width is not None and width > max_width:
                height = scale_w * height
                width = max_width
            else:
                scale = min(scale_h, scale_w)
                if scale != float("inf"):
                    width *= scale
                    height *= scale
        return (width, height)

    def _derived_text_anchor(self, position: float, size: float, origin: str | None) -> float | None:
        origin_key = (origin or "").casefold()
        if origin_key in {"center", "middle"}:
            return position + (size / 2.0)
        if origin_key in {"right", "bottom"}:
            return position + size
        if origin_key in {"left", "top", ""}:
            return position
        return None

    def _derived_rect_anchor(self, rect: QRectF, origin: str | None, *, axis: str) -> float:
        origin_key = (origin or "").casefold()
        start = rect.left() if axis == "x" else rect.top()
        center = rect.center().x() if axis == "x" else rect.center().y()
        end = rect.right() if axis == "x" else rect.bottom()
        if origin_key in {"center", "middle"}:
            return center
        if origin_key in {"right", "bottom"}:
            return end
        return start

    def _element_hitbox_path(self, element: ThemePreviewElement, display_rect: QRectF, fitted: QRectF, scale_x: float, scale_y: float) -> QPainterPath:
        path = QPainterPath()
        if element.transform_points and len(element.transform_points) >= 4:
            polygon = self._scaled_transform_polygon(element, fitted, scale_x, scale_y)
            path.addPolygon(polygon)
            path.closeSubpath()
            return path
        path.addRect(display_rect)
        return path

    def _scaled_transform_polygon(self, element: ThemePreviewElement, fitted: QRectF, scale_x: float, scale_y: float) -> QPolygonF:
        points = list(element.transform_points[:4])
        if len(points) == 4:
            points = [points[0], points[1], points[3], points[2]]
        return QPolygonF(
            [
                QPointF(fitted.x() + (point[0] * scale_x), fitted.y() + (point[1] * scale_y))
                for point in points
            ]
        )

    def _draw_transformed_pixmap(
        self,
        painter: QPainter,
        pixmap: QPixmap,
        element: ThemePreviewElement,
        fitted: QRectF,
        scale_x: float,
        scale_y: float,
    ) -> None:
        polygon = self._scaled_transform_polygon(element, fitted, scale_x, scale_y)
        if polygon.size() < 4:
            return
        source = QPolygonF(
            [
                QPointF(0.0, 0.0),
                QPointF(float(pixmap.width()), 0.0),
                QPointF(float(pixmap.width()), float(pixmap.height())),
                QPointF(0.0, float(pixmap.height())),
            ]
        )
        transform = QTransform.quadToQuad(source, polygon)
        painter.save()
        clip_path = QPainterPath()
        clip_path.addPolygon(polygon)
        clip_path.closeSubpath()
        painter.setClipPath(clip_path)
        painter.setTransform(transform, True)
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()

    def _draw_reflection_pixmap(
        self,
        painter: QPainter,
        source_pixmap: QPixmap,
        element: ThemePreviewElement,
        visible_rect: QRectF,
        element_rect: QRectF,
    ) -> None:
        """Draw a vertically-flipped, fade-gradient copy of *source_pixmap* into *element_rect*, clipped to *visible_rect*."""
        full_rect = QRectF(element_rect)
        if full_rect.width() <= 1 or full_rect.height() <= 1:
            return
        aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
        scaled = source_pixmap.scaled(
            full_rect.size().toSize(),
            aspect_mode,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Flip vertically
        flipped = scaled.transformed(QTransform().scale(1, -1))
        # Apply a top-to-bottom fade: opaque at top, fully transparent at bottom
        faded = QPixmap(flipped.size())
        faded.fill(Qt.GlobalColor.transparent)
        fade_painter = QPainter(faded)
        fade_painter.drawPixmap(0, 0, flipped)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(flipped.height()))
        opacity = 0.55
        if element.reflection_scale is not None and element.reflection_scale > 0:
            opacity = min(0.75, element.reflection_scale)
        gradient.setColorAt(0.0, QColor(0, 0, 0, int(opacity * 255)))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        fade_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade_painter.fillRect(faded.rect(), gradient)
        fade_painter.end()
        # Draw the faded reflection, clipped to the visible area
        draw_rect = self._aligned_media_rect(full_rect, faded, element)
        painter.save()
        painter.setClipRect(visible_rect)
        painter.drawPixmap(int(draw_rect.x()), int(draw_rect.y()), faded)
        painter.restore()

    def _draw_rect_pixmap(self, painter: QPainter, pixmap: QPixmap, element: ThemePreviewElement, visible_rect: QRectF, element_rect: QRectF) -> None:
        full_rect = QRectF(element_rect)
        if full_rect.width() <= 1 or full_rect.height() <= 1:
            return
        if element.kind == "reloadable_panning_image":
            self._draw_panning_pixmap(painter, pixmap, element, visible_rect, full_rect)
            return
        slot_key = (element.slot_name or "").casefold()
        if element.kind == "image":
            # Static decorative images are always stretched to fill their defined dimensions.
            scale_size = full_rect.size().toSize()
            aspect_mode = Qt.AspectRatioMode.IgnoreAspectRatio
        elif element.explicit_height and not element.explicit_width:
            # Height-only constraint: fill height exactly, let width follow aspect ratio.
            # Using a very large width target ensures height is the binding dimension.
            # +1 pixel guarantees full coverage regardless of sub-pixel rounding.
            scale_size = QSize(32767, int(round(full_rect.height())) + 1)
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        elif element.explicit_width and not element.explicit_height:
            if self._should_expand_width_constrained_media(element):
                scale_size = full_rect.size().toSize()
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
            else:
                # Width-only constraint: fill width exactly, let height follow aspect ratio.
                scale_size = QSize(int(round(full_rect.width())), 32767)
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        elif slot_key == "marquee":
            # CoinOPS marquees are authored to span the header width. Fill width exactly and
            # let height overflow/crop within the box rather than shrinking to fit inside it.
            scale_size = QSize(int(round(full_rect.width())), 32767)
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        elif self._should_fit_media_rect(element):
            scale_size = full_rect.size().toSize()
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
        else:
            scale_size = full_rect.size().toSize()
            aspect_mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding
        if element.angle is not None and abs(element.angle) > 0.1:
            scaled_pixmap = self._scaled_rotated_pixmap(pixmap, full_rect, aspect_mode, element.angle)
        else:
            scaled_pixmap = pixmap.scaled(
                scale_size,
                aspect_mode,
                Qt.TransformationMode.SmoothTransformation,
            )
        if self._expanded and element in self._pulsing_overlay_elements:
            scaled_pixmap = self._soften_pulse_overlay_pixmap(scaled_pixmap)
        draw_rect = self._aligned_media_rect(full_rect, scaled_pixmap, element)
        painter.save()
        painter.setClipRect(visible_rect)
        if element.angle is not None and abs(element.angle) > 0.1:
            center = draw_rect.center()
            painter.translate(center)
            painter.rotate(element.angle)
            painter.translate(-center)
        painter.drawPixmap(int(draw_rect.x()), int(draw_rect.y()), scaled_pixmap)
        painter.restore()

    def _draw_panning_pixmap(
        self,
        painter: QPainter,
        pixmap: QPixmap,
        element: ThemePreviewElement,
        visible_rect: QRectF,
        full_rect: QRectF,
    ) -> None:
        scaled_pixmap, draw_rect = self._panning_draw_rect(pixmap, element, full_rect)

        painter.save()
        painter.setClipRect(visible_rect)
        painter.drawPixmap(int(draw_rect.x()), int(draw_rect.y()), scaled_pixmap)
        painter.restore()

    def _panning_draw_rect(
        self,
        pixmap: QPixmap,
        element: ThemePreviewElement,
        full_rect: QRectF,
    ) -> tuple[QPixmap, QRectF]:
        zoom = max(1.0, element.zoom_scale_to or 1.0)
        scale_size = QSize(
            max(1, int(round(full_rect.width() * zoom))),
            max(1, int(round(full_rect.height() * zoom))),
        )
        scaled_pixmap = pixmap.scaled(
            scale_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        draw_rect = self._aligned_media_rect(full_rect, scaled_pixmap, element)

        if self._animation_enabled and element.pan_speed is not None and element.pan_speed > 0:
            overflow_x = max(0.0, draw_rect.width() - full_rect.width())
            overflow_y = max(0.0, draw_rect.height() - full_rect.height())
            threshold = max(0.0, element.pan_threshold or 0.0)
            ratio_x = overflow_x / max(1.0, full_rect.width())
            ratio_y = overflow_y / max(1.0, full_rect.height())
            elapsed_secs = time.monotonic()

            def _ping_pong(distance: float) -> float:
                if distance <= 0.0:
                    return 0.0
                progress = (elapsed_secs * element.pan_speed) / max(1.0, distance)
                phase = progress % 2.0
                return phase if phase <= 1.0 else (2.0 - phase)

            if ratio_y >= ratio_x and ratio_y > threshold:
                draw_rect.moveTop(full_rect.top() - (overflow_y * _ping_pong(overflow_y)))
            elif ratio_x > threshold:
                draw_rect.moveLeft(full_rect.left() - (overflow_x * _ping_pong(overflow_x)))

        return scaled_pixmap, draw_rect

    def _scaled_rotated_pixmap(
        self,
        pixmap: QPixmap,
        bounds: QRectF,
        aspect_mode: Qt.AspectRatioMode,
        angle: float,
    ) -> QPixmap:
        width = float(pixmap.width())
        height = float(pixmap.height())
        if width <= 1 or height <= 1:
            return pixmap
        if bounds.width() <= 1 or bounds.height() <= 1:
            return pixmap
        radians = math.radians(abs(angle))
        cos_theta = abs(math.cos(radians))
        sin_theta = abs(math.sin(radians))
        if aspect_mode == Qt.AspectRatioMode.KeepAspectRatioByExpanding:
            scale = max(bounds.width() / width, bounds.height() / height)
        else:
            rotated_width = (width * cos_theta) + (height * sin_theta)
            rotated_height = (width * sin_theta) + (height * cos_theta)
            scale = min(bounds.width() / max(1.0, rotated_width), bounds.height() / max(1.0, rotated_height))
        target_width = max(1, int(round(width * scale)))
        target_height = max(1, int(round(height * scale)))
        return pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _should_fit_media_rect(self, element: ThemePreviewElement) -> bool:
        # Panning images fill (and overflow) their container — never fit-within.
        if element.kind == "reloadable_panning_image":
            return False
        # Elements where only one dimension is constrained must fit within it; the unconstrained
        # axis follows the image's natural aspect ratio.
        if not element.explicit_width or not element.explicit_height:
            return True
        slot_key = (element.slot_name or "").casefold()
        return element.kind == "menu" or slot_key in {
            "logo",
            "artwork_front",
            "artwork_front_s",
            "led_marquee",
            "lcd_marquee",
            "manufacturer",
            "genre",
            "playlist",
            "firstletter",
            "rightstrip",
            "score",
            "ctrltype",
            "numberbuttons",
            "numberplayers",
            "device",
            "display",
        }

    def _should_expand_width_constrained_media(self, element: ThemePreviewElement) -> bool:
        slot_key = (element.slot_name or "").casefold()
        return (
            element.explicit_width
            and not element.explicit_height
            and element.min_height is not None
            and slot_key in {"artwork_front", "artwork_front_s"}
        )

    def _aligned_media_rect(self, bounds: QRectF, pixmap: QPixmap, element: ThemePreviewElement) -> QRectF:
        x_origin = (element.x_origin or "").casefold()
        y_origin = (element.y_origin or "").casefold()
        if x_origin in {"center", "middle"}:
            x_pos = bounds.center().x() - (pixmap.width() / 2.0)
        elif x_origin in {"right", "bottom"}:
            x_pos = bounds.right() - pixmap.width()
        else:
            # Default (no xOrigin or "left"/"top"): anchor at the element's left edge.
            x_pos = bounds.left()
        if y_origin in {"center", "middle"}:
            y_pos = bounds.center().y() - (pixmap.height() / 2.0)
        elif y_origin in {"right", "bottom"}:
            y_pos = bounds.bottom() - pixmap.height()
        else:
            # Default (no yOrigin or "left"/"top"): anchor at the element's top edge.
            y_pos = bounds.top()
        return QRectF(x_pos, y_pos, float(pixmap.width()), float(pixmap.height()))

    def _sync_action_buttons(self) -> None:
        preview_visible = self._preview is not None
        self._previous_button.setVisible(preview_visible)
        self._previous_button.setEnabled(preview_visible and self._controls_enabled)
        self._play_button.setVisible(preview_visible)
        self._play_button.setEnabled(preview_visible and self._controls_enabled)
        self._play_button.setIcon(QIcon(str(_assets_dir() / ("pause-white.svg" if self._animation_enabled else "play-button-white.svg"))))
        self._next_button.setVisible(preview_visible)
        self._next_button.setEnabled(preview_visible and self._controls_enabled)
        self._volume_button.setVisible(preview_visible)
        self._volume_button.setEnabled(preview_visible and self._mute_enabled)
        self._volume_button.setIcon(QIcon(str(_assets_dir() / ("volume-off-white.svg" if self._muted else "volume-max-white.svg"))))
        if preview_visible and not self._expanded:
            self._expand_button.show()
        elif not self._expanded:
            self._expand_button.hide()
        self._position_action_buttons()
        self._sync_floating_buttons()

    def _position_action_buttons(self) -> None:
        if self._preview is None:
            return
        baseline = max(
            self._previous_button.height(),
            self._play_button.height(),
            self._next_button.height(),
            self._volume_button.height(),
            self._expand_button.height(),
        )
        y_pos = max(0, self.height() - baseline - self._action_padding)
        x_cursor = self._action_padding
        self._previous_button.move(x_cursor, y_pos + max(0, baseline - self._previous_button.height()))
        x_cursor += self._previous_button.width() + self._nav_control_spacing
        self._play_button.move(x_cursor, y_pos + max(0, baseline - self._play_button.height()))
        x_cursor += self._play_button.width() + self._nav_control_spacing
        self._next_button.move(x_cursor, y_pos + max(0, baseline - self._next_button.height()))
        x_cursor += self._next_button.width() + self._control_spacing
        self._volume_button.move(
            x_cursor,
            y_pos + max(0, baseline - self._volume_button.height()),
        )
        x_pos = max(0, self.width() - self._expand_button.width() - self._action_padding)
        self._expand_button.move(x_pos, y_pos + max(0, baseline - self._expand_button.height()))
        self._previous_button.raise_()
        self._play_button.raise_()
        self._next_button.raise_()
        self._volume_button.raise_()
        self._expand_button.raise_()

    def _attach_window_filter(self) -> None:
        window = self.window()
        if not isinstance(window, QWidget) or window is self._window_filter_target:
            return
        if self._window_filter_target is not None:
            self._window_filter_target.removeEventFilter(self)
        self._window_filter_target = window
        self._window_filter_target.installEventFilter(self)

    def _attach_app_filter(self) -> None:
        app = QApplication.instance()
        if app is None or app is self._app_filter_target:
            return
        if self._app_filter_target is not None:
            self._app_filter_target.removeEventFilter(self)
        self._app_filter_target = app
        self._app_filter_target.installEventFilter(self)

    def _detach_app_filter(self) -> None:
        if self._app_filter_target is not None:
            self._app_filter_target.removeEventFilter(self)
            self._app_filter_target = None

    def _handle_global_mouse_press(self, event) -> None:
        if self._floating_preview is None or not hasattr(event, "globalPosition"):
            return
        global_pos = event.globalPosition().toPoint()
        preview_pos = self._floating_preview.mapFromGlobal(global_pos)
        if self._floating_preview.rect().contains(preview_pos):
            return
        self._set_expanded(False)

    def _toggle_expanded(self) -> None:
        if self._preview is None:
            return
        self._set_expanded(not self._expanded)

    def _set_expanded(self, expanded: bool) -> None:
        if expanded:
            active = ThemeLayoutPreviewWidget._active_expanded_preview
            if active is not None and active is not self:
                active._set_expanded(False)
            ThemeLayoutPreviewWidget._active_expanded_preview = self
        elif ThemeLayoutPreviewWidget._active_expanded_preview is self:
            ThemeLayoutPreviewWidget._active_expanded_preview = None
        self._expanded = expanded
        if not expanded:
            self._detach_app_filter()
            self._floating_preview_update_timer.stop()
            self._floating_preview_dirty = False
            if self._preview is not None:
                self._expand_button.show()
                self._sync_action_buttons()
            if self._floating_preview is not None:
                self._floating_preview.hide()
            return
        self._expand_button.hide()
        self._attach_window_filter()
        self._attach_app_filter()
        if self._window_filter_target is None:
            return
        if self._floating_preview is None:
            self._floating_preview = QWidget(self._window_filter_target)
            self._floating_preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._floating_preview.setStyleSheet("background: transparent; border: 1px solid #444444;")
            self._floating_canvas_label = QLabel(self._floating_preview)
            self._floating_canvas_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._floating_previous_button = QPushButton(self._floating_preview)
            self._floating_previous_button.setObjectName("videoControlButton")
            self._floating_previous_button.setFixedSize(38, 38)
            self._floating_previous_button.setIconSize(QSize(22, 22))
            self._floating_previous_button.setFlat(True)
            self._floating_previous_button.setStyleSheet("background: transparent; border: none;")
            self._floating_previous_button.setIcon(QIcon(str(_assets_dir() / "previous-circle.svg")))
            self._floating_previous_button.clicked.connect(self.previousRequested.emit)
            self._floating_play_button = QPushButton(self._floating_preview)
            self._floating_play_button.setObjectName("videoControlButton")
            self._floating_play_button.setFixedSize(42, 42)
            self._floating_play_button.setIconSize(QSize(24, 24))
            self._floating_play_button.setFlat(True)
            self._floating_play_button.setStyleSheet("background: transparent; border: none;")
            self._floating_play_button.clicked.connect(self.playPauseRequested.emit)
            self._floating_next_button = QPushButton(self._floating_preview)
            self._floating_next_button.setObjectName("videoControlButton")
            self._floating_next_button.setFixedSize(38, 38)
            self._floating_next_button.setIconSize(QSize(22, 22))
            self._floating_next_button.setFlat(True)
            self._floating_next_button.setStyleSheet("background: transparent; border: none;")
            self._floating_next_button.setIcon(QIcon(str(_assets_dir() / "next-circle.svg")))
            self._floating_next_button.clicked.connect(self.nextRequested.emit)
            self._floating_volume_button = QPushButton(self._floating_preview)
            self._floating_volume_button.setObjectName("videoControlButton")
            self._floating_volume_button.setFixedSize(38, 38)
            self._floating_volume_button.setIconSize(QSize(22, 22))
            self._floating_volume_button.setFlat(True)
            self._floating_volume_button.setStyleSheet("background: transparent; border: none;")
            self._floating_volume_button.clicked.connect(self.muteRequested.emit)
            self._floating_expand_button = QPushButton(self._floating_preview)
            self._floating_expand_button.setObjectName("videoControlButton")
            self._floating_expand_button.setFixedSize(self._action_button_size, self._action_button_size)
            self._floating_expand_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
            self._floating_expand_button.setFlat(True)
            self._floating_expand_button.setStyleSheet("background: transparent; border: none;")
            self._floating_expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))
            self._floating_expand_button.clicked.connect(self._toggle_expanded)
        self._floating_preview.show()
        self._floating_preview.raise_()
        self._sync_floating_buttons()
        self._request_floating_preview_update(immediate=True)

    def _request_floating_preview_update(self, *, immediate: bool = False, animation: bool = False) -> None:
        if not self._expanded or self._floating_preview is None:
            return
        self._floating_preview_dirty = True
        desired_interval = 16 if animation else 50
        if self._floating_preview_update_interval_ms != desired_interval:
            self._floating_preview_update_interval_ms = desired_interval
            self._floating_preview_update_timer.setInterval(desired_interval)
        if immediate:
            self._floating_preview_update_timer.stop()
            self._flush_floating_preview_update()
            return
        if not self._floating_preview_update_timer.isActive():
            self._floating_preview_update_timer.start()

    def _flush_floating_preview_update(self) -> None:
        if not self._floating_preview_dirty:
            return
        self._floating_preview_dirty = False
        self._update_floating_preview()

    def _update_floating_preview(self) -> None:
        if (
            self._floating_preview is None
            or self._floating_canvas_label is None
            or self._window_filter_target is None
            or self._preview is None
        ):
            return
        anchor = self.mapTo(self._window_filter_target, self.rect().bottomRight())
        target_width = min(self._window_filter_target.width() - 24, max(520, self.width() * 2))
        target_height = min(self._window_filter_target.height() - 24, max(360, self.height() * 2))
        canvas = QPixmap(max(1, target_width), max(1, target_height))
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        self._paint_preview(painter, QRectF(canvas.rect()), record_hitboxes=False)
        painter.end()
        x_pos = max(12, anchor.x() - canvas.width() + 1)
        y_pos = max(12, anchor.y() - canvas.height() + 1)
        self._floating_preview.setGeometry(x_pos, y_pos, canvas.width(), canvas.height())
        self._floating_canvas_label.setGeometry(0, 0, canvas.width(), canvas.height())
        self._floating_canvas_label.setPixmap(canvas)
        self._position_floating_action_buttons()

    def _sync_floating_buttons(self) -> None:
        if self._floating_preview is None:
            return
        for button in (
            getattr(self, "_floating_previous_button", None),
            getattr(self, "_floating_play_button", None),
            getattr(self, "_floating_next_button", None),
            getattr(self, "_floating_volume_button", None),
            getattr(self, "_floating_expand_button", None),
        ):
            if button is None:
                continue
            button.setVisible(self._expanded and self._preview is not None)
        if getattr(self, "_floating_previous_button", None) is not None:
            self._floating_previous_button.setEnabled(self._controls_enabled)
        if getattr(self, "_floating_play_button", None) is not None:
            self._floating_play_button.setEnabled(self._controls_enabled)
            self._floating_play_button.setIcon(QIcon(str(_assets_dir() / ("pause-white.svg" if self._animation_enabled else "play-button-white.svg"))))
        if getattr(self, "_floating_next_button", None) is not None:
            self._floating_next_button.setEnabled(self._controls_enabled)
        if getattr(self, "_floating_volume_button", None) is not None:
            self._floating_volume_button.setEnabled(self._mute_enabled)
            self._floating_volume_button.setIcon(QIcon(str(_assets_dir() / ("volume-off-white.svg" if self._muted else "volume-max-white.svg"))))
        if getattr(self, "_floating_expand_button", None) is not None:
            self._floating_expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))
        self._position_floating_action_buttons()

    def _position_floating_action_buttons(self) -> None:
        if self._floating_preview is None:
            return
        previous_button = getattr(self, "_floating_previous_button", None)
        play_button = getattr(self, "_floating_play_button", None)
        next_button = getattr(self, "_floating_next_button", None)
        volume_button = getattr(self, "_floating_volume_button", None)
        expand_button = getattr(self, "_floating_expand_button", None)
        if previous_button is None or play_button is None or next_button is None or volume_button is None or expand_button is None:
            return
        baseline = max(previous_button.height(), play_button.height(), next_button.height(), volume_button.height(), expand_button.height())
        y_pos = max(0, self._floating_preview.height() - baseline - self._action_padding)
        x_cursor = self._action_padding
        previous_button.move(x_cursor, y_pos + max(0, baseline - previous_button.height()))
        x_cursor += previous_button.width() + self._nav_control_spacing
        play_button.move(x_cursor, y_pos + max(0, baseline - play_button.height()))
        x_cursor += play_button.width() + self._nav_control_spacing
        next_button.move(x_cursor, y_pos + max(0, baseline - next_button.height()))
        x_cursor += next_button.width() + self._control_spacing
        volume_button.move(
            x_cursor,
            y_pos + max(0, baseline - volume_button.height()),
        )
        expand_button.move(
            max(0, self._floating_preview.width() - expand_button.width() - self._action_padding),
            y_pos + max(0, baseline - expand_button.height()),
        )
        previous_button.raise_()
        play_button.raise_()
        next_button.raise_()
        volume_button.raise_()
        expand_button.raise_()

    def _preview_font_for_element(self, element: ThemePreviewElement, scale_x: float, scale_y: float) -> QFont:
        font = QFont(self.font())
        family = self._font_family_for_path(element.font_path)
        if family:
            font.setFamily(family)
        requested_size = (element.font_size or element.load_font_size or 10.0) * scale_y
        pixel_size = requested_size
        raw_font, _ = self._raw_font_for_element(element, scale_y)
        if raw_font is not None:
            line_height = raw_font.ascent() + raw_font.descent() + raw_font.leading()
            if line_height > 0:
                pixel_size = requested_size * (requested_size / line_height)
        font.setPixelSize(max(5, int(round(pixel_size))))
        font.setBold(False)
        font.setWeight(QFont.Weight.Normal)
        return font

    def _natural_text_bounds(self, font: QFont, text: str) -> QRectF:
        metrics = QFontMetricsF(font)
        width = metrics.horizontalAdvance(text)
        height = metrics.height()
        return QRectF(0.0, 0.0, width, height)

    def _natural_text_draw_point(self, font: QFont, text: str, visible_rect: QRectF) -> QPointF:
        # Position baseline at rect.top() + ascent. Using the full ascent (not tight ink top)
        # gives the natural top and left padding that RetroFE's font rendering produces.
        return QPointF(visible_rect.left(), visible_rect.top() + QFontMetricsF(font).ascent())

    def _raw_font_for_element(self, element: ThemePreviewElement, scale_y: float) -> tuple[QRawFont | None, float]:
        pixel_size = max(5, int(round((element.font_size or element.load_font_size or 10.0) * scale_y)))
        font_path = element.font_path
        if not font_path:
            return (None, float(pixel_size))
        cache_key = (font_path, pixel_size)
        cached = self._raw_font_cache.get(cache_key)
        if cached is not None or cache_key in self._raw_font_cache:
            return (cached, float(pixel_size))
        raw_font = QRawFont(font_path, pixel_size)
        if not raw_font.isValid():
            raw_font = None
        self._raw_font_cache[cache_key] = raw_font
        return (raw_font, float(pixel_size))

    def _retrofe_text_layout(
        self,
        element: ThemePreviewElement,
        text: str,
        scale_y: float,
        *,
        max_width: float | None = None,
    ) -> dict[str, object] | None:
        raw_font, target_font_size = self._raw_font_for_element(element, scale_y)
        if raw_font is None or not text:
            return None
        glyph_indices = raw_font.glyphIndexesForString(text)
        if not glyph_indices:
            return None
        advances = raw_font.advancesForGlyphIndexes(glyph_indices)
        line_height = max(1.0, raw_font.ascent() + raw_font.descent() + raw_font.leading())
        scale = target_font_size / line_height
        image_max_width = max_width if max_width is not None and max_width > 0 else float("inf")
        image_width = 0.0
        glyphs: list[dict[str, object]] = []
        for glyph_index, advance in zip(glyph_indices, advances):
            bounds = raw_font.pathForGlyph(glyph_index).boundingRect()
            min_x = bounds.x()
            max_y = -bounds.y()
            if min_x < 0:
                image_width += min_x
            if (image_width + advance.x()) * scale > image_max_width:
                break
            glyph_image = raw_font.alphaMapForGlyph(glyph_index, QRawFont.AntialiasingType.PixelAntialiasing)
            glyphs.append(
                {
                    "image": glyph_image,
                    "advance": advance.x(),
                    "min_x": min_x,
                    "max_y": max_y,
                }
            )
            image_width += advance.x()
        return {
            "glyphs": glyphs,
            "width": max(0.0, image_width * scale),
            "height": max(1.0, target_font_size),
            "scale": scale,
            "ascent": raw_font.ascent(),
        }


    def _apply_natural_text_padding(
        self,
        display_rects: dict[ThemePreviewElement, QRectF],
        elements: tuple[ThemePreviewElement, ...],
        scale_y: float,
    ) -> None:
        return

    def _adjust_natural_text_rect(
        self,
        element: ThemePreviewElement,
        rect: QRectF,
        scale_x: float,
        scale_y: float,
    ) -> QRectF:
        return QRectF(rect)

    @classmethod
    def _font_family_for_path(cls, font_path: str | None) -> str | None:
        if not font_path:
            return None
        cached = cls._font_family_cache.get(font_path)
        if cached is not None or font_path in cls._font_family_cache:
            return cached
        family: str | None = None
        path = Path(font_path)
        if path.exists():
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    family = families[0]
        cls._font_family_cache[font_path] = family
        return family

    def _text_color_for_element(self, element: ThemePreviewElement) -> QColor:
        raw = (element.font_color or "").strip().lstrip("#")
        if len(raw) in {3, 6, 8}:
            color = QColor(f"#{raw}")
            if color.isValid():
                return color
        return QColor("#cccccc")

    def _formatted_element_text(self, element: ThemePreviewElement, text: str) -> str:
        format_key = (element.text_format or "").casefold()
        if format_key == "uppercase":
            return text.upper()
        if format_key == "lowercase":
            return text.lower()
        return text

    def _text_alignment_flags(self, element: ThemePreviewElement) -> Qt.AlignmentFlag:
        x_origin = (element.x_origin or "").casefold()
        y_origin = (element.y_origin or "").casefold()
        horizontal = Qt.AlignmentFlag.AlignLeft
        vertical = Qt.AlignmentFlag.AlignTop
        if x_origin in {"center", "middle"}:
            horizontal = Qt.AlignmentFlag.AlignHCenter
        elif x_origin in {"right", "bottom"}:
            horizontal = Qt.AlignmentFlag.AlignRight
        if y_origin in {"center", "middle"}:
            vertical = Qt.AlignmentFlag.AlignVCenter
        elif y_origin in {"right", "bottom"}:
            vertical = Qt.AlignmentFlag.AlignBottom
        return horizontal | vertical

    def _anchored_coordinate(self, anchor: float, size: float, origin: str | None) -> float:
        origin_key = (origin or "").casefold()
        if origin_key in {"center", "middle"}:
            return anchor - (size / 2.0)
        if origin_key in {"right", "bottom"}:
            return anchor - size
        return anchor


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._required_specs = REQUIRED_COMPONENTS
        self._game_pack_specs = GAME_PACKS
        self._bitlcd_specs = BITLCD_MARQUEES
        self._optional_specs = OPTIONAL_COMPONENTS
        self.base_installer = Installer(self._required_specs)
        self.game_packs_installer = Installer(self._game_pack_specs)
        self.bitlcd_installer = Installer(self._bitlcd_specs)
        self.optional_components_installer = Installer(self._optional_specs)
        self.archive_metadata = ArchiveMetadataService()
        self.required_component_catalog = ArchiveBackedComponentCatalog(self._required_specs, build_required_component_specs)
        self.system_pack_catalog = SystemPackCatalogService()
        self.bitlcd_catalog = ArchiveBackedComponentCatalog(self._bitlcd_specs, build_bitlcd_component_specs)
        self.optional_component_catalog = ArchiveBackedComponentCatalog(self._optional_specs, build_optional_component_specs)
        self.settings_store = SettingsStore()
        self._worker_thread: QThread | None = None
        self._worker: InstallWorker | None = None
        self._validate_thread: QThread | None = None
        self._validate_worker: ValidateCredentialsWorker | None = None
        self._release_check_thread: QThread | None = None
        self._release_check_worker: ReleaseCheckWorker | None = None
        self._controller: OperationController | None = None
        self._loading_settings = False
        self._loading_tweaks_settings = False
        self._closing = False
        self._close_after_workers = False
        self._last_video_loop_value = "0"
        self._last_attract_mode_time_value = "0"
        self._last_attract_mode_next_time_value = "0"
        self._theme_preview_render_data: dict[ThemePreviewElement, ThemePreviewRenderData] = {}
        self._theme_preview_video_sessions: dict[ThemePreviewElement, ThemePreviewVideoSession] = {}
        self._theme_preview_animation_enabled = False
        self._theme_games_cache: dict[str, tuple[GameManifestEntry, ...]] = {}
        self._media_root_cache: dict[str, Path | None] = {}
        self._theme_preview_muted = False
        self._theme_preview_cycle_timer = QTimer(self)
        self._theme_preview_cycle_timer.setSingleShot(True)
        self._theme_preview_cycle_timer.timeout.connect(self._advance_theme_preview_attract_mode)
        self._theme_preview_scroll_timer = QTimer(self)
        self._theme_preview_scroll_timer.setSingleShot(False)
        self._theme_preview_scroll_timer.timeout.connect(self._step_theme_preview_attract_animation)
        self._theme_preview_pending_indices: deque[int] = deque()
        self._theme_video_dirty = False
        self._theme_preview_wheel_spinning = False
        self._theme_video_repaint_timer = QTimer(self)
        self._theme_video_repaint_timer.setSingleShot(False)
        self._theme_video_repaint_timer.setInterval(33)  # ~30 fps repaint cap
        self._theme_video_repaint_timer.timeout.connect(self._flush_theme_video_repaint)
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
        self._base_game_entries = load_game_manifest()
        self._game_entries = self._base_game_entries
        self._collection_options = available_collections()
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
        self._theme_entries: tuple[ThemeCatalogEntry, ...] = tuple()
        self._themes_catalog_target: str | None = None
        self._selected_theme_name: str | None = None
        self._theme_preview: ThemeLayoutPreview | None = None
        self._selected_theme_element: ThemePreviewElement | None = None
        self._selected_theme_collection_name: str | None = None
        self._selected_theme_game_key: tuple[str, str] | None = None
        self._theme_preview_previous_stopped_game_key: tuple[str, str] | None = None
        self._theme_preview_last_stopped_game_key: tuple[str, str] | None = None
        self._theme_element_index_map: list[ThemePreviewElement | None] = []
        self._selected_log_key: str | None = None
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

        self.settings_nav_button = QPushButton("Settings")
        self.settings_nav_button.setObjectName("navButton")
        self.settings_nav_button.setCheckable(True)
        self.settings_nav_button.clicked.connect(lambda: self._change_screen(SETTINGS_SCREEN))

        self.tweaks_nav_button = QPushButton("Settings")
        self.tweaks_nav_button.setObjectName("navButton")
        self.tweaks_nav_button.setCheckable(True)
        self.tweaks_nav_button.clicked.connect(lambda: self._change_screen(TWEAKS_SCREEN))

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

        self.queue_nav_button = QPushButton("Queue")
        self.queue_nav_button.setObjectName("navButton")
        self.queue_nav_button.setCheckable(True)
        self.queue_nav_button.clicked.connect(lambda: self._change_screen(QUEUE_SCREEN))

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

        sidebar_layout.addWidget(self._build_nav_section("Companion", self.settings_nav_button, self.queue_nav_button))
        sidebar_layout.addWidget(
            self._build_nav_section(
                "Install",
                self.base_components_nav_button,
                self.game_packs_nav_button,
                self.bitlcd_nav_button,
                self.optional_components_nav_button,
            )
        )
        sidebar_layout.addWidget(
            self._build_nav_section(
                "OnesaUCE",
                self.games_nav_button,
                self.collections_nav_button,
                self.themes_nav_button,
                self.logs_nav_button,
                self.tweaks_nav_button,
            )
        )
        sidebar_layout.addStretch(1)
        version_row = QWidget()
        version_row_layout = QHBoxLayout(version_row)
        version_row_layout.setContentsMargins(0, 0, 0, 0)
        version_row_layout.setSpacing(0)
        version_row_layout.addStretch(1)
        self.sidebar_version_label = QLabel(APP_VERSION)
        self.sidebar_version_label.setObjectName("sidebarVersion")
        self.sidebar_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon = QLabel()
        self.sidebar_version_icon.setObjectName("sidebarVersionIcon")
        self.sidebar_version_icon.setPixmap(_cherry_icon_pixmap())
        self.sidebar_version_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon.setContentsMargins(0, 6, 0, 0)
        self.sidebar_version_icon_2 = QLabel()
        self.sidebar_version_icon_2.setObjectName("sidebarVersionIcon")
        self.sidebar_version_icon_2.setPixmap(_strawberry_icon_pixmap())
        self.sidebar_version_icon_2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sidebar_version_icon_2.setContentsMargins(0, 6, 0, 0)
        version_row_layout.addWidget(self.sidebar_version_label)
        version_row_layout.addSpacing(6)
        version_row_layout.addWidget(self.sidebar_version_icon)
        version_row_layout.addWidget(self.sidebar_version_icon_2)
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

        title = QLabel()
        title.setObjectName("titleLogo")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        logo_path = _assets_dir() / "onesauce_companion_logo.png"
        self._logo_pixmap = QPixmap(str(logo_path))
        if not self._logo_pixmap.isNull():
            self._title_logo = title
        else:
            title.setText("OnesaUCE")
            self._title_logo = None
        content_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)

        self.startup_loading_label = QLabel("Loading...")
        self.startup_loading_label.setObjectName("startupLoading")
        self.startup_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.startup_loading_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(content_container, stretch=1)

        self.stack.addWidget(self._build_settings_screen())
        self.stack.addWidget(self._build_base_components_screen())
        self.stack.addWidget(self._build_game_packs_screen())
        self.stack.addWidget(self._build_bitlcd_marquees_screen())
        self.stack.addWidget(self._build_optional_components_screen())
        self.stack.addWidget(self._build_queue_screen())
        self.stack.addWidget(self._build_games_screen())
        self.stack.addWidget(self._build_collections_screen())
        self.stack.addWidget(self._build_tweaks_screen())
        self.stack.addWidget(self._build_logs_screen())
        self.stack.addWidget(self._build_themes_screen())

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_message_queue: deque[tuple[str, int]] = deque()
        self._status_message_timer = QTimer(self)
        self._status_message_timer.setSingleShot(True)
        self._status_message_timer.timeout.connect(self._show_next_status_message)
        self._current_status_message: str | None = None
        self._push_status_message("Ready")

        self.menuBar().hide()
        QTimer.singleShot(0, self._update_logo_pixmap)

    def _build_nav_group(self, *buttons: QPushButton) -> QWidget:
        container = QWidget()
        container.setObjectName("navGroup")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 22, 8, 8)
        layout.setSpacing(8)
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
        layout.setContentsMargins(0, max(1, label.sizeHint().height() // 2), 0, 0)
        layout.setSpacing(0)
        nav_group = self._build_nav_group(*buttons)
        layout.addWidget(nav_group)
        label.raise_()
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

        target_layout.addWidget(QLabel("Target folder"), 0, 0)
        target_layout.addWidget(self.target_edit, 0, 1)
        target_layout.addWidget(browse_button, 0, 2)
        self.root_warning = self._build_target_warning(
            "OnesaUCE will not run unless it is installed to the root of the drive."
        )
        self.ntfs_warning = self._build_target_warning(
            "OnesaUCE will not run unless the drive has been formatted NTFS."
        )
        self.bitlcd_warning = self._build_target_warning(
            r"BitLCD will not see marquees that are not within the \bitlcd\thirdparty folder structure."
        )
        target_layout.addWidget(self.root_warning, 1, 0, 1, 3)
        target_layout.addWidget(self.ntfs_warning, 2, 0, 1, 3)
        target_layout.addWidget(QLabel("BitLCD folder"), 3, 0)
        target_layout.addWidget(self.bitlcd_target_edit, 3, 1)
        target_layout.addWidget(bitlcd_browse_button, 3, 2)
        target_layout.addWidget(self.bitlcd_warning, 4, 0, 1, 3)
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
        self.auto_resume_downloads_checkbox = QCheckBox()
        self.auto_resume_downloads_checkbox.setChecked(False)
        auto_resume_label = QLabel("Automatically Resume Downloads on Start")
        auto_resume_row = QWidget()
        auto_resume_layout = QHBoxLayout(auto_resume_row)
        auto_resume_layout.setContentsMargins(0, 0, 0, 0)
        auto_resume_layout.setSpacing(6)
        auto_resume_layout.addWidget(self.auto_resume_downloads_checkbox)
        auto_resume_layout.addWidget(auto_resume_label)
        auto_resume_layout.addStretch(1)
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
        downloads_layout.addWidget(auto_resume_row, 4, 0, 1, 3)
        downloads_layout.addWidget(downloads_note, 5, 0, 1, 3)
        downloads_layout.addLayout(downloads_actions_row, 6, 0, 1, 3)
        layout.addWidget(downloads_group)
        layout.addStretch(1)
        return container

    def _build_tweaks_screen(self) -> QWidget:
        container = QScrollArea()
        container.setWidgetResizable(True)
        container.setFrameShape(QFrame.Shape.NoFrame)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        screen = QWidget()
        container.setWidget(screen)
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(18)

        autostart_group = QGroupBox("Autostart")
        autostart_layout = QVBoxLayout(autostart_group)
        autostart_layout.setSpacing(12)

        self.tweaks_autostart_warning = self._build_target_warning(
            "The OnesaUCE base component must first be installed before Autostart can be configured."
        )
        autostart_layout.addWidget(self.tweaks_autostart_warning)

        self.tweaks_autostart_status_row = QWidget()
        status_row_layout = QHBoxLayout(self.tweaks_autostart_status_row)
        status_row_layout.setContentsMargins(0, 0, 0, 0)
        status_row_layout.setSpacing(8)
        status_row_layout.addWidget(QLabel("Autostart Status:"))
        self.tweaks_autostart_status_value = QLabel(AUTOSTART_STATUS_NOT_ENABLED)
        self.tweaks_autostart_status_value.setObjectName("sidebarVersion")
        status_row_layout.addWidget(self.tweaks_autostart_status_value)
        status_row_layout.addStretch(1)
        autostart_layout.addWidget(self.tweaks_autostart_status_row)

        self.tweaks_autostart_action_row = QWidget()
        action_row_layout = QHBoxLayout(self.tweaks_autostart_action_row)
        action_row_layout.setContentsMargins(0, 0, 0, 0)
        action_row_layout.setSpacing(10)
        self.tweaks_autostart_primary_button = QPushButton("Enable Autostart")
        self.tweaks_autostart_primary_button.setMinimumWidth(200)
        self.tweaks_autostart_primary_button.clicked.connect(self._handle_autostart_primary_action)
        action_row_layout.addWidget(self.tweaks_autostart_primary_button)
        action_row_layout.addStretch(1)
        autostart_layout.addWidget(self.tweaks_autostart_action_row)

        self.tweaks_autostart_fix_intro = QLabel(
            "Autostart may cause certain Legends cabinets to freeze during startup. If so, you can enable the fix for it."
        )
        self.tweaks_autostart_fix_intro.setWordWrap(True)
        autostart_layout.addWidget(self.tweaks_autostart_fix_intro)

        self.tweaks_autostart_fix_button = QPushButton("Install Freeze Fix")
        self.tweaks_autostart_fix_button.setMinimumWidth(160)
        self.tweaks_autostart_fix_button.clicked.connect(self._handle_install_autostart_fix)
        autostart_layout.addWidget(self.tweaks_autostart_fix_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.tweaks_autostart_fix_disabled_note = QLabel("Autostart must first be enabled before the fix can be applied")
        self.tweaks_autostart_fix_disabled_note.setWordWrap(True)
        self.tweaks_autostart_fix_disabled_note.hide()
        autostart_layout.addWidget(self.tweaks_autostart_fix_disabled_note)

        self.tweaks_autostart_fix_installed_note = QLabel("The fix has been installed")
        self.tweaks_autostart_fix_installed_note.setWordWrap(True)
        self.tweaks_autostart_fix_installed_note.hide()
        autostart_layout.addWidget(self.tweaks_autostart_fix_installed_note)

        self.tweaks_autostart_fix_pending_note = QLabel(
            "OnesaUCE must first be started once with Autostart Enabled.\n"
            "If OnesaUCE starts up successfully, there is no need to install the fix."
        )
        self.tweaks_autostart_fix_pending_note.setWordWrap(True)
        self.tweaks_autostart_fix_pending_note.hide()
        autostart_layout.addWidget(self.tweaks_autostart_fix_pending_note)

        layout.addWidget(autostart_group)

        settings_tweaks_group = QGroupBox("Settings Tweaks")
        settings_tweaks_layout = QVBoxLayout(settings_tweaks_group)
        settings_tweaks_layout.setSpacing(12)
        self.tweaks_legends_micro_fix_checkbox = QCheckBox()
        self.tweaks_legends_micro_fix_checkbox.stateChanged.connect(self._handle_legends_micro_fix_toggled)
        self.tweaks_legends_micro_fix_row = QWidget()
        legends_micro_fix_layout = QHBoxLayout(self.tweaks_legends_micro_fix_row)
        legends_micro_fix_layout.setContentsMargins(0, 0, 0, 0)
        legends_micro_fix_layout.setSpacing(10)
        legends_micro_fix_layout.addWidget(self.tweaks_legends_micro_fix_checkbox)
        legends_micro_fix_layout.addWidget(QLabel("Enable Legends Pinball Micro Rotation Fix"))
        legends_micro_fix_layout.addStretch(1)
        settings_tweaks_layout.addWidget(self.tweaks_legends_micro_fix_row)
        layout.addWidget(settings_tweaks_group)

        onesauce_settings_group = QGroupBox("OnesaUCE Settings")
        onesauce_settings_layout = QGridLayout(onesauce_settings_group)
        onesauce_settings_layout.setHorizontalSpacing(12)
        onesauce_settings_layout.setVerticalSpacing(10)
        onesauce_settings_layout.setColumnStretch(1, 1)

        self.tweaks_onesauce_settings_warning = self._build_target_warning(
            "The appdata and base_assets Base Components must first be installed before settings can be modified."
        )
        onesauce_settings_layout.addWidget(self.tweaks_onesauce_settings_warning, 0, 0, 1, 2)

        self.tweaks_remember_menu_row = QWidget()
        remember_menu_layout = QHBoxLayout(self.tweaks_remember_menu_row)
        remember_menu_layout.setContentsMargins(0, 0, 0, 0)
        remember_menu_layout.setSpacing(10)
        self.tweaks_remember_menu_checkbox = QCheckBox()
        self.tweaks_remember_menu_checkbox.stateChanged.connect(self._handle_remember_menu_toggled)
        remember_menu_layout.addWidget(self.tweaks_remember_menu_checkbox)
        remember_menu_layout.addWidget(QLabel("Remember the last highlighted menu when re-entering a menu"))
        remember_menu_layout.addStretch(1)
        onesauce_settings_layout.addWidget(self.tweaks_remember_menu_row, 1, 0, 1, 2)

        self.tweaks_write_launcher_log_row = QWidget()
        write_launcher_log_layout = QHBoxLayout(self.tweaks_write_launcher_log_row)
        write_launcher_log_layout.setContentsMargins(0, 0, 0, 0)
        write_launcher_log_layout.setSpacing(10)
        self.tweaks_write_launcher_log_checkbox = QCheckBox()
        self.tweaks_write_launcher_log_checkbox.stateChanged.connect(self._handle_write_launcher_log_toggled)
        write_launcher_log_layout.addWidget(self.tweaks_write_launcher_log_checkbox)
        write_launcher_log_layout.addWidget(QLabel("Log output from game launcher"))
        write_launcher_log_layout.addStretch(1)
        onesauce_settings_layout.addWidget(self.tweaks_write_launcher_log_row, 2, 0, 1, 2)

        self.tweaks_video_enable_row = QWidget()
        video_enable_layout = QHBoxLayout(self.tweaks_video_enable_row)
        video_enable_layout.setContentsMargins(0, 0, 0, 0)
        video_enable_layout.setSpacing(10)
        self.tweaks_video_enable_checkbox = QCheckBox()
        self.tweaks_video_enable_checkbox.stateChanged.connect(self._handle_video_enable_toggled)
        video_enable_layout.addWidget(self.tweaks_video_enable_checkbox)
        video_enable_layout.addWidget(QLabel("Enable Video Playback"))
        video_enable_layout.addStretch(1)
        onesauce_settings_layout.addWidget(self.tweaks_video_enable_row, 3, 0, 1, 2)

        self.tweaks_auto_scan_collections_row = QWidget()
        auto_scan_collections_layout = QHBoxLayout(self.tweaks_auto_scan_collections_row)
        auto_scan_collections_layout.setContentsMargins(0, 0, 0, 0)
        auto_scan_collections_layout.setSpacing(10)
        self.tweaks_auto_scan_collections_checkbox = QCheckBox()
        self.tweaks_auto_scan_collections_checkbox.stateChanged.connect(self._handle_auto_scan_collections_toggled)
        auto_scan_collections_layout.addWidget(self.tweaks_auto_scan_collections_checkbox)
        auto_scan_collections_layout.addWidget(QLabel("Auto Scan Collections on Startup (longer startup time)"))
        auto_scan_collections_layout.addStretch(1)
        onesauce_settings_layout.addWidget(self.tweaks_auto_scan_collections_row, 4, 0, 1, 2)

        self.tweaks_default_theme_label = QLabel("Default Theme")
        self.tweaks_default_theme_combo = QComboBox()
        self.tweaks_default_theme_combo.currentIndexChanged.connect(self._handle_default_theme_changed)
        onesauce_settings_layout.addWidget(self.tweaks_default_theme_label, 5, 0)
        onesauce_settings_layout.addWidget(self.tweaks_default_theme_combo, 5, 1)

        self.tweaks_video_loop_label = QLabel("Number of video loops (0 = continuous)")
        self.tweaks_video_loop_edit = QLineEdit()
        self.tweaks_video_loop_edit.setMaxLength(3)
        self.tweaks_video_loop_edit.setFixedWidth(72)
        self.tweaks_video_loop_edit.setValidator(QIntValidator(0, 999, self))
        self.tweaks_video_loop_edit.editingFinished.connect(self._handle_video_loop_changed)
        onesauce_settings_layout.addWidget(self.tweaks_video_loop_label, 6, 0)
        onesauce_settings_layout.addWidget(self.tweaks_video_loop_edit, 6, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)

        self.tweaks_attract_mode_time_label = QLabel("Seconds before entering Attract Mode (0 to disable)")
        self.tweaks_attract_mode_time_edit = QLineEdit()
        self.tweaks_attract_mode_time_edit.setMaxLength(3)
        self.tweaks_attract_mode_time_edit.setFixedWidth(72)
        self.tweaks_attract_mode_time_edit.setValidator(QIntValidator(0, 999, self))
        self.tweaks_attract_mode_time_edit.editingFinished.connect(self._handle_attract_mode_time_changed)
        onesauce_settings_layout.addWidget(self.tweaks_attract_mode_time_label, 7, 0)
        onesauce_settings_layout.addWidget(self.tweaks_attract_mode_time_edit, 7, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)

        self.tweaks_attract_mode_next_time_label = QLabel("Seconds between items in Attract Mode")
        self.tweaks_attract_mode_next_time_edit = QLineEdit()
        self.tweaks_attract_mode_next_time_edit.setMaxLength(3)
        self.tweaks_attract_mode_next_time_edit.setFixedWidth(72)
        self.tweaks_attract_mode_next_time_edit.setValidator(QIntValidator(0, 999, self))
        self.tweaks_attract_mode_next_time_edit.editingFinished.connect(self._handle_attract_mode_next_time_changed)
        onesauce_settings_layout.addWidget(self.tweaks_attract_mode_next_time_label, 8, 0)
        onesauce_settings_layout.addWidget(self.tweaks_attract_mode_next_time_edit, 8, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)

        self.tweaks_default_video_value_label = QLabel("Default Video Volume")
        self.tweaks_default_video_value_row = QWidget()
        default_video_value_layout = QHBoxLayout(self.tweaks_default_video_value_row)
        default_video_value_layout.setContentsMargins(0, 0, 0, 0)
        default_video_value_layout.setSpacing(10)
        self.tweaks_default_video_value_slider = QSlider(Qt.Orientation.Horizontal)
        self.tweaks_default_video_value_slider.setRange(0, 100)
        self.tweaks_default_video_value_slider.valueChanged.connect(self._handle_default_video_value_changed)
        self.tweaks_default_video_value_percent_label = QLabel("0%")
        self.tweaks_default_video_value_percent_label.setMinimumWidth(48)
        default_video_value_layout.addWidget(self.tweaks_default_video_value_slider, stretch=1)
        default_video_value_layout.addWidget(self.tweaks_default_video_value_percent_label)
        onesauce_settings_layout.addWidget(self.tweaks_default_video_value_label, 9, 0)
        onesauce_settings_layout.addWidget(self.tweaks_default_video_value_row, 9, 1)

        layout.addWidget(onesauce_settings_group)
        layout.addStretch(1)
        return container

    def _build_base_components_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
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
        self.base_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.base_summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.base_summary_warning_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.base_summary_label, 1)
        actions_row.addWidget(self.refresh_button)
        actions_row.addWidget(self.install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("Required Components")
        status_layout = QVBoxLayout(status_group)

        self.table = QTableWidget(len(self._required_specs), 6)
        self.table.setObjectName("ComponentsTable")
        self.base_header = CheckBoxHeader()
        self.base_header.toggled.connect(lambda checked: self._toggle_all_component_rows(BASE_COMPONENTS_SCREEN, checked))
        self.table.setHorizontalHeader(self.base_header)
        self.table.setHorizontalHeaderLabels(["", "Component", "Installed", "Available", "Size", "Status"])
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
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(4, 110)
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

    def _build_game_packs_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
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
        self.game_packs_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.game_packs_summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.game_packs_summary_warning_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.game_packs_summary_label, 1)
        actions_row.addWidget(self.game_packs_refresh_button)
        actions_row.addWidget(self.game_packs_install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("System Packs")
        status_layout = QVBoxLayout(status_group)

        self.game_packs_table = QTableWidget(len(self._game_pack_specs), 6)
        self.game_packs_table.setObjectName("ComponentsTable")
        self.game_packs_header = CheckBoxHeader()
        self.game_packs_header.toggled.connect(lambda checked: self._toggle_all_component_rows(GAME_PACKS_SCREEN, checked))
        self.game_packs_table.setHorizontalHeader(self.game_packs_header)
        self.game_packs_table.setHorizontalHeaderLabels(["", "Pack", "Installed", "Available", "Size", "Status"])
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
        self.game_packs_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.game_packs_table.setColumnWidth(0, 42)
        self.game_packs_table.setColumnWidth(1, 260)
        self.game_packs_table.setColumnWidth(4, 110)
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

    def _build_bitlcd_marquees_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
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
        self.bitlcd_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.bitlcd_summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.bitlcd_summary_warning_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.bitlcd_summary_label, 1)
        actions_row.addWidget(self.bitlcd_refresh_button)
        actions_row.addWidget(self.bitlcd_install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("BitLCD Marquees")
        status_layout = QVBoxLayout(status_group)

        self.bitlcd_table = QTableWidget(len(self._bitlcd_specs), 6)
        self.bitlcd_table.setObjectName("ComponentsTable")
        self.bitlcd_header = CheckBoxHeader()
        self.bitlcd_header.toggled.connect(lambda checked: self._toggle_all_component_rows(BITLCD_MARQUEES_SCREEN, checked))
        self.bitlcd_table.setHorizontalHeader(self.bitlcd_header)
        self.bitlcd_table.setHorizontalHeaderLabels(["", "Marquee", "Installed", "Available", "Size", "Status"])
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
        self.bitlcd_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.bitlcd_table.setColumnWidth(0, 42)
        self.bitlcd_table.setColumnWidth(1, 260)
        self.bitlcd_table.setColumnWidth(4, 110)
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

    def _build_optional_components_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
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
        self.optional_components_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.optional_components_summary_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.optional_components_summary_warning_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        actions_row.addWidget(self.optional_components_summary_label, 1)
        actions_row.addWidget(self.optional_components_refresh_button)
        actions_row.addWidget(self.optional_components_install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("Optional Components")
        status_layout = QVBoxLayout(status_group)

        self.optional_components_table = QTableWidget(len(self._optional_specs), 7)
        self.optional_components_table.setObjectName("ComponentsTable")
        self.optional_components_header = CheckBoxHeader()
        self.optional_components_header.toggled.connect(lambda checked: self._toggle_all_component_rows(OPTIONAL_COMPONENTS_SCREEN, checked))
        self.optional_components_table.setHorizontalHeader(self.optional_components_header)
        self.optional_components_table.setHorizontalHeaderLabels(["", "Component", "Type", "Installed", "Available", "Size", "Status"])
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
        self.optional_components_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.optional_components_table.setColumnWidth(0, 42)
        self.optional_components_table.setColumnWidth(1, 280)
        self.optional_components_table.setColumnWidth(5, 110)
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
        self.queue_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
        self.queue_table.setColumnWidth(5, 320)
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

    def _build_collections_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

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

    def _build_themes_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        list_group = QGroupBox("Themes")
        list_layout = QVBoxLayout(list_group)
        list_layout.setSpacing(10)
        self.themes_results_label = QLabel("0 themes")
        self.themes_results_label.setObjectName("themesMetaLabel")
        self.themes_list = QListWidget()
        self.themes_list.setObjectName("ThemeList")
        self.themes_list.itemSelectionChanged.connect(self._handle_theme_selection_changed)
        list_layout.addWidget(self.themes_results_label)
        list_layout.addWidget(self.themes_list, stretch=1)

        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(18)

        details_group = QGroupBox("Theme Details")
        details_group_layout = QVBoxLayout(details_group)
        details_group_layout.setSpacing(12)
        self.themes_name_label = QLabel("Theme: None")
        self.themes_name_label.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.themes_canvas_label = QLabel("Canvas Size: Unknown")
        self.themes_canvas_label.setObjectName("themesMetaLabel")
        details_group_layout.addWidget(self.themes_name_label)
        details_group_layout.addWidget(self.themes_canvas_label)
        details_layout.addWidget(details_group)

        preview_group = QGroupBox("Layout Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(10)
        preview_header = QHBoxLayout()
        preview_header.setSpacing(12)
        self.themes_collection_filter = QComboBox()
        self.themes_collection_filter.currentIndexChanged.connect(self._handle_theme_collection_changed)
        preview_header.addWidget(self.themes_collection_filter, stretch=1)
        self.themes_game_filter = QComboBox()
        self.themes_game_filter.currentIndexChanged.connect(self._handle_theme_game_changed)
        preview_header.addWidget(self.themes_game_filter, stretch=1)
        self.themes_preview_caption = QLabel("Color-coded boxes show the active root or collection override layout.")
        self.themes_preview_caption.setObjectName("themesMetaLabel")
        self.themes_preview = ThemeLayoutPreviewWidget()
        self.themes_preview.elementSelected.connect(self._handle_theme_preview_selection_changed)
        self.themes_preview.previousRequested.connect(self._handle_theme_preview_previous_requested)
        self.themes_preview.playPauseRequested.connect(self._toggle_theme_preview_animation)
        self.themes_preview.nextRequested.connect(self._handle_theme_preview_next_requested)
        self.themes_preview.muteRequested.connect(self._toggle_theme_preview_mute)
        self.themes_preview.wheelAnimationIndexChanged.connect(self._handle_theme_preview_scroll_index_changed)
        self.themes_preview.wheelAnimationFinished.connect(self._on_wheel_animation_finished)
        self.themes_element_selector = QComboBox()
        self.themes_element_selector.currentIndexChanged.connect(self._handle_theme_element_selector_changed)
        self.themes_show_wireframes_checkbox = QCheckBox("Show Wireframes")
        self.themes_show_wireframes_checkbox.setChecked(True)
        self.themes_show_wireframes_checkbox.stateChanged.connect(self._handle_theme_wireframe_toggled)
        self.themes_show_media_checkbox = QCheckBox("Show Media")
        self.themes_show_media_checkbox.setChecked(True)
        self.themes_show_media_checkbox.stateChanged.connect(self._handle_theme_media_toggled)
        self.themes_show_text_checkbox = QCheckBox("Show Text")
        self.themes_show_text_checkbox.setChecked(True)
        self.themes_show_text_checkbox.stateChanged.connect(self._handle_theme_text_toggled)
        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)
        left_controls = QWidget()
        left_controls_layout = QHBoxLayout(left_controls)
        left_controls_layout.setContentsMargins(0, 0, 0, 0)
        left_controls_layout.setSpacing(12)
        left_controls_layout.addWidget(self.themes_show_wireframes_checkbox)
        left_controls_layout.addWidget(self.themes_show_media_checkbox)
        left_controls_layout.addWidget(self.themes_show_text_checkbox)
        left_controls_layout.addStretch(1)
        controls_row.addWidget(left_controls, stretch=2)
        controls_row.addWidget(self.themes_element_selector, stretch=1)
        self.themes_element_details = QPlainTextEdit()
        self.themes_element_details.setReadOnly(True)
        self.themes_element_details.setFont(QFont("Consolas", 10))
        self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
        element_details_panel = QWidget()
        element_details_layout = QVBoxLayout(element_details_panel)
        element_details_layout.setContentsMargins(0, 0, 0, 0)
        element_details_layout.setSpacing(10)
        element_details_layout.addWidget(self.themes_element_details, stretch=1)
        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_splitter.setChildrenCollapsible(False)
        preview_splitter.addWidget(self.themes_preview)
        preview_splitter.addWidget(element_details_panel)
        preview_splitter.setStretchFactor(0, 2)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setSizes([760, 360])
        preview_layout.addLayout(preview_header)
        preview_layout.addWidget(self.themes_preview_caption)
        preview_layout.addLayout(controls_row)
        preview_layout.addWidget(preview_splitter, stretch=1)
        details_layout.addWidget(preview_group, stretch=1)

        splitter.addWidget(list_group)
        splitter.addWidget(details_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 950])

        layout.addWidget(splitter, stretch=1)
        return screen

    def _build_logs_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        logs_group = QGroupBox("Logs")
        logs_layout = QVBoxLayout(logs_group)

        selector_panel = QWidget()
        selector_layout = QVBoxLayout(selector_panel)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(8)
        selector_panel.setMinimumWidth(180)
        selector_panel.setMaximumWidth(220)

        self.log_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("retrofe", "RetroFE"),
            ("scripter", "Scripter"),
            ("sunshine", "Sunshine"),
            ("retroarch", "Retroarch"),
            ("companion", "Companion"),
        ):
            button = QPushButton(label)
            button.setObjectName("logSelectorButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, log_key=key: self._select_log(log_key))
            selector_layout.addWidget(button)
            self.log_buttons[key] = button
        selector_layout.addStretch(1)

        viewer_panel = QFrame()
        viewer_panel.setObjectName("logsViewerFrame")
        viewer_layout = QVBoxLayout(viewer_panel)
        viewer_layout.setContentsMargins(12, 12, 12, 12)
        viewer_layout.setSpacing(12)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(14)
        self.log_filter_checkboxes: dict[str, QCheckBox] = {}
        for key, label in (
            ("info", "Info"),
            ("debug", "Debug"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("critical", "Critical"),
            ("fatal", "Fatal"),
            ("other", "Other"),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(lambda _state, _key=key: self._refresh_logs_screen())
            filters_row.addWidget(checkbox)
            self.log_filter_checkboxes[key] = checkbox
        filters_row.addStretch(1)
        self.log_wrap_checkbox = QCheckBox("Wrap Lines")
        self.log_wrap_checkbox.setChecked(False)
        self.log_wrap_checkbox.stateChanged.connect(self._handle_log_wrap_toggled)
        filters_row.addWidget(self.log_wrap_checkbox)
        self.log_change_colors_button = QPushButton("Change Colors")
        self.log_change_colors_button.clicked.connect(self._change_log_colors)
        filters_row.addWidget(self.log_change_colors_button)
        viewer_layout.addLayout(filters_row)

        self.logs_content_stack = QStackedWidget()
        self.logs_empty_label = QLabel("Select a log file from the left to view its contents")
        self.logs_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logs_missing_label = QLabel("Log file is not present")
        self.logs_missing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logs_viewer = QPlainTextEdit()
        self.logs_viewer.setReadOnly(True)
        self.logs_viewer.setFont(QFont("Consolas", 10))
        self.logs_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.logs_highlighter = LogSyntaxHighlighter(self.logs_viewer.document(), self._log_highlight_colors)
        self.logs_content_stack.addWidget(self.logs_empty_label)
        self.logs_content_stack.addWidget(self.logs_missing_label)
        self.logs_content_stack.addWidget(self.logs_viewer)
        self.logs_content_stack.setCurrentWidget(self.logs_empty_label)
        viewer_layout.addWidget(self.logs_content_stack, stretch=1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(selector_panel)
        splitter.addWidget(viewer_panel)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 900])
        logs_layout.addWidget(splitter, stretch=1)

        layout.addWidget(logs_group, stretch=1)
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
            QWidget#navSectionContainer {{
                background: #222222;
            }}
            QLabel#navSectionLabel {{
                color: #8f8f8f;
                font-size: 9.5pt;
                font-weight: 700;
                background: #222222;
                padding: 0px 6px;
            }}
            QLabel#collectionLinks {{
                color: #69b8ff;
                padding: 0;
            }}
            QLabel#collectionLinks a {{
                color: #69b8ff;
                text-decoration: none;
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
            QListWidget#ThemeList {{
                background: #242424;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 6px;
                outline: none;
            }}
            QListWidget#ThemeList::item {{
                padding: 10px 12px;
                border-radius: 6px;
            }}
            QListWidget#ThemeList::item:selected {{
                background: #e2cf5a;
                color: #1f1f1f;
            }}
            QLabel#themesMetaLabel {{
                color: #a9a9a9;
                font-size: 10pt;
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
                background: #c9b548;
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
                background: #e2cf5a;
                color: #1f1f1f;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #edd96e;
            }}
            QPushButton:pressed {{
                background: #0066cc;
            }}
            QPushButton:disabled {{
                background: #4a4a4a;
                color: #8f8f8f;
            }}
            QPushButton#videoControlButton {{
                background: transparent;
                border: none;
                border-radius: 0px;
                padding: 0px;
                min-width: 0px;
                min-height: 0px;
            }}
            QPushButton#videoControlButton:hover {{
                background: transparent;
            }}
            QPushButton#videoControlButton:pressed {{
                background: transparent;
            }}
            QPushButton#videoControlButton:disabled {{
                background: transparent;
            }}
            QSlider#videoSeekSlider {{
                background: transparent;
                padding: 0px;
            }}
            QSlider#videoSeekSlider::groove:horizontal {{
                background: rgba(255, 255, 255, 0.18);
                height: 6px;
                border-radius: 3px;
            }}
            QSlider#videoSeekSlider::sub-page:horizontal {{
                background: #2ea3ff;
                border-radius: 3px;
            }}
            QSlider#videoSeekSlider::add-page:horizontal {{
                background: rgba(255, 255, 255, 0.18);
                border-radius: 3px;
            }}
            QSlider#videoSeekSlider::handle:horizontal {{
                background: #ffffff;
                width: 12px;
                margin: -4px 0px;
                border-radius: 6px;
            }}
            QSlider#videoSeekSlider::handle:horizontal:hover {{
                background: #d8e6f2;
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
                background: #e2cf5a;
                color: #1f1f1f;
                border-color: #e2cf5a;
            }}
            QPushButton#logSelectorButton {{
                background: transparent;
                color: #c8c8c8;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 10px 12px;
                text-align: left;
                font-weight: 600;
            }}
            QPushButton#logSelectorButton:hover {{
                background: #343434;
                border-color: #555555;
                color: #ffffff;
            }}
            QPushButton#logSelectorButton:checked {{
                background: #2f2f2f;
                border-color: #6a6a6a;
                color: #ffffff;
            }}
            QFrame#logsViewerFrame {{
                background: #242424;
                border: 1px solid #555555;
                border-radius: 8px;
            }}
            QLabel#sidebarVersion {{
                color: #8f8f8f;
                font-size: 10pt;
                font-weight: 600;
                padding-top: 4px;
            }}
            QLabel#sidebarVersionNote {{
                color: #9a9a9a;
                font-size: 8.5pt;
                padding-top: 0px;
            }}
            QLabel#sidebarVersionNote a {{
                color: #00c4f4;
                text-decoration: underline;
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
                padding: 10px 44px 10px 10px;
                font-weight: 700;
            }}
            QHeaderView::up-arrow {{
                image: url("{spin_up_icon}");
                width: 10px;
                height: 10px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
                right: 10px;
            }}
            QHeaderView::down-arrow {{
                image: url("{spin_down_icon}");
                width: 10px;
                height: 10px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
                right: 10px;
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
        self.target_edit.editingFinished.connect(self._commit_install_target_settings)
        self.bitlcd_target_edit.editingFinished.connect(self._commit_bitlcd_target_settings)
        self.downloads_path_edit.editingFinished.connect(self._commit_downloads_path_settings)
        self.downloads_retention_combo.currentIndexChanged.connect(self._sync_download_retention_controls)
        self.downloads_retention_combo.currentIndexChanged.connect(self._save_settings)
        self.downloads_retention_days_spin.editingFinished.connect(self._save_settings)
        self.downloads_retention_max_gb_spin.editingFinished.connect(self._save_settings)
        self.parallel_downloads_spin.editingFinished.connect(self._save_settings)

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
            self.archive_email_edit.setText(settings.archive_email)
            self.archive_password_edit.setText(settings.archive_password)
            self.parallel_downloads_spin.setValue(settings.parallel_downloads)
            self.log_wrap_checkbox.setChecked(settings.log_wrap_lines)
            self._log_highlight_colors = dict(DEFAULT_LOG_HIGHLIGHT_COLORS)
            self._log_highlight_colors.update(settings.log_highlight_colors)
            if getattr(self, "logs_highlighter", None) is not None:
                self.logs_highlighter.set_color_map(self._log_highlight_colors)
            self._apply_download_settings_to_installers(settings)
            self.resize(settings.window_width, settings.window_height)
            if settings.window_x is not None and settings.window_y is not None:
                self.move(settings.window_x, settings.window_y)
            self._load_saved_queue_entries(settings)
            self._selected_theme_name = settings.theme_selected_theme or None
            self._selected_theme_collection_name = settings.theme_selected_collection or None
            key_parts = settings.theme_selected_game_key
            self._selected_theme_game_key = (key_parts[0], key_parts[1]) if len(key_parts) == 2 else None
            self.themes_show_wireframes_checkbox.setChecked(settings.theme_show_wireframes)
            self.themes_show_media_checkbox.setChecked(settings.theme_show_media)
            self.themes_show_text_checkbox.setChecked(settings.theme_show_text)
        finally:
            self._loading_settings = False
        self._refresh_target_validation()
        self._refresh_tweaks_screen()
        self._sync_download_retention_controls()
        self._update_component_summary_labels()
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
            auto_resume_downloads_on_start=self.auto_resume_downloads_checkbox.isChecked(),
            archive_email=self.archive_email_edit.text().strip(),
            archive_password=self.archive_password_edit.text(),
            parallel_downloads=self.parallel_downloads_spin.value(),
            window_width=self.width(),
            window_height=self.height(),
            window_x=self.x(),
            window_y=self.y(),
            log_wrap_lines=self.log_wrap_checkbox.isChecked(),
            log_highlight_colors=self._log_highlight_colors,
            queue_entries=self._serialized_queue_entries(),
            theme_selected_theme=self._selected_theme_name or "",
            theme_selected_collection=self._selected_theme_collection_name or "",
            theme_selected_game_key=list(self._selected_theme_game_key) if self._selected_theme_game_key else [],
            theme_show_wireframes=self.themes_show_wireframes_checkbox.isChecked(),
            theme_show_media=self.themes_show_media_checkbox.isChecked(),
            theme_show_text=self.themes_show_text_checkbox.isChecked(),
        )
        self.settings_store.save(settings)
        self._apply_download_settings_to_installers(settings)
        self._update_component_summary_labels()

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
        self._change_screen(BASE_COMPONENTS_SCREEN)

    def _begin_startup_refresh(self) -> None:
        self._defer_screen_refresh = False
        self.startup_loading_label.show()
        self._startup_refresh_queue.clear()
        initial_screen = self.stack.currentIndex()
        if initial_screen in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            self._startup_refresh_queue.append(initial_screen)
        self._run_next_startup_refresh()

    def _run_next_startup_refresh(self) -> None:
        if not self._startup_refresh_queue:
            self.startup_loading_label.hide()
            QTimer.singleShot(0, self._resume_saved_queue_if_possible)
            return
        screen_index = self._startup_refresh_queue.popleft()
        if screen_index == GAMES_SCREEN:
            self._refresh_games_table()
        elif screen_index == COLLECTIONS_SCREEN:
            self._refresh_collections_table()
        elif screen_index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            self._refresh_screen_table(screen_index)
            self._initialized_component_screens.add(screen_index)
        self._startup_refresh_timer.start(40)

    def _resume_saved_queue_if_possible(self) -> None:
        if self._controller is not None or not self._queue_entries:
            self._update_queue_buttons()
            return
        if not self.auto_resume_downloads_checkbox.isChecked():
            self._push_status_message("Saved queue loaded. Automatic resume is disabled in Settings.")
            self._update_queue_buttons()
            return
        pending_entries = [entry for entry in self._queue_entries if entry.status != "Installed"]
        if not pending_entries:
            self._update_queue_buttons()
            return
        if self._archive_credentials() is None:
            self._push_status_message("Saved queue loaded. Enter Archive.org credentials to resume.")
            self._update_queue_buttons()
            return
        if not pending_entries[0].target_path.strip():
            self._push_status_message("Saved queue loaded. Choose a target folder to resume.")
            self._update_queue_buttons()
            return
        self.queue_log_output.appendPlainText(f"Resuming saved queue with {len(pending_entries)} item(s).")
        self._start_queue_install()

    def _change_screen(self, index: int) -> None:
        if index < 0:
            return
        previous_index = self.stack.currentIndex()
        if previous_index == THEMES_SCREEN and index != THEMES_SCREEN:
            self._stop_theme_preview_animation()
            self._dispose_all_theme_preview_video_sessions()
        self.stack.setCurrentIndex(index)
        self.settings_nav_button.setChecked(index == SETTINGS_SCREEN)
        self.tweaks_nav_button.setChecked(index == TWEAKS_SCREEN)
        self.base_components_nav_button.setChecked(index == BASE_COMPONENTS_SCREEN)
        self.game_packs_nav_button.setChecked(index == GAME_PACKS_SCREEN)
        self.bitlcd_nav_button.setChecked(index == BITLCD_MARQUEES_SCREEN)
        self.optional_components_nav_button.setChecked(index == OPTIONAL_COMPONENTS_SCREEN)
        self.queue_nav_button.setChecked(index == QUEUE_SCREEN)
        self.games_nav_button.setChecked(index == GAMES_SCREEN)
        self.collections_nav_button.setChecked(index == COLLECTIONS_SCREEN)
        self.themes_nav_button.setChecked(index == THEMES_SCREEN)
        self.logs_nav_button.setChecked(index == LOGS_SCREEN)
        if self._defer_screen_refresh:
            return
        if index == TWEAKS_SCREEN:
            self._refresh_tweaks_screen()
        elif index == QUEUE_SCREEN:
            self._refresh_queue_table()
        elif index == GAMES_SCREEN:
            self._refresh_games_table()
        elif index == COLLECTIONS_SCREEN:
            self._refresh_collections_table()
        elif index == THEMES_SCREEN:
            self._refresh_themes_screen()
        elif index == LOGS_SCREEN:
            self._refresh_logs_screen()
        elif index in {BASE_COMPONENTS_SCREEN, GAME_PACKS_SCREEN, BITLCD_MARQUEES_SCREEN, OPTIONAL_COMPONENTS_SCREEN}:
            if index not in self._initialized_component_screens:
                self._refresh_screen_table(index)

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
        self.base_installer.cache_dir = downloads_dir
        self.game_packs_installer.cache_dir = downloads_dir
        self.bitlcd_installer.cache_dir = downloads_dir
        self.optional_components_installer.cache_dir = downloads_dir
        self.base_installer.max_parallel_downloads = settings.parallel_downloads
        self.game_packs_installer.max_parallel_downloads = settings.parallel_downloads
        self.bitlcd_installer.max_parallel_downloads = settings.parallel_downloads
        self.optional_components_installer.max_parallel_downloads = settings.parallel_downloads

    def _clear_downloads_now(self) -> None:
        result = clear_downloads_dir(self._downloads_dir())
        self._push_status_message(f"Cleared {result.deleted_files} download file(s).")
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
        target_height = 150
        scaled = self._logo_pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
        self._title_logo.setPixmap(scaled)
        self._title_logo.setFixedSize(scaled.size())

    def _schedule_scan(self) -> None:
        if self._loading_settings:
            return
        self._scan_timer.start()

    def _refresh_all_tables(self) -> None:
        self._games_catalog_target = None
        self._games_installed_target = None
        self._games_excluded_target = None
        self._collections_catalog_target = None
        self._themes_catalog_target = None
        self._refresh_tweaks_screen()
        self._refresh_screen_table(BASE_COMPONENTS_SCREEN)
        self._refresh_screen_table(GAME_PACKS_SCREEN)
        self._refresh_screen_table(BITLCD_MARQUEES_SCREEN)
        self._refresh_screen_table(OPTIONAL_COMPONENTS_SCREEN)
        self._refresh_games_table()
        self._refresh_collections_table()
        self._refresh_themes_screen()

    def _handle_refresh_requested(self) -> None:
        button = self.sender()
        if isinstance(button, QPushButton):
            if button is self.refresh_button:
                self._force_required_catalog_refresh = True
            elif button is self.game_packs_refresh_button:
                self._force_system_pack_catalog_refresh = True
            elif button is self.bitlcd_refresh_button:
                self._force_bitlcd_catalog_refresh = True
            elif button is self.optional_components_refresh_button:
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
            self._set_checkbox_widget(table, row, status.spec.key, screen_index)
            if screen_index == OPTIONAL_COMPONENTS_SCREEN:
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["component"], status.spec.display_name)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["type"], self._component_type_display(status.spec))
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["installed"], status.installed_version or "Not installed")
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["available"], status.spec.available_display)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["size"], self._component_size_display(status.spec))
                self._set_status_cell(table, row, status.spec.key, OPTIONAL_TABLE_COLUMNS["status"])
            else:
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
            self._push_status_message(f"Scanned {target}")

    def _populate_missing_table(self, table: QTableWidget, components: list[ComponentSpec]) -> None:
        screen_index = self._screen_for_table(table)
        self._disabled_component_keys[screen_index] = set()
        self._selection_sync = True
        table.setUpdatesEnabled(False)
        table.setRowCount(len(components))
        for row, spec in enumerate(components):
            self._set_checkbox_widget(table, row, spec.key, screen_index)
            if screen_index == OPTIONAL_COMPONENTS_SCREEN:
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["component"], spec.display_name)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["type"], self._component_type_display(spec))
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["installed"], "Not scanned")
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["available"], spec.available_display)
                self._set_item(table, row, OPTIONAL_TABLE_COLUMNS["size"], self._component_size_display(spec))
                self._set_status_cell(table, row, spec.key, OPTIONAL_TABLE_COLUMNS["status"])
            else:
                self._set_item(table, row, BASE_TABLE_COLUMNS["component"], spec.display_name)
                self._set_item(table, row, BASE_TABLE_COLUMNS["installed"], "Not scanned")
                self._set_item(table, row, BASE_TABLE_COLUMNS["available"], spec.available_display)
                self._set_item(table, row, BASE_TABLE_COLUMNS["size"], self._component_size_display(spec))
                self._set_status_cell(table, row, spec.key, BASE_TABLE_COLUMNS["status"])
            self._set_status_widget(spec.key, "Pending", 0)
        self._selection_sync = False
        table.setUpdatesEnabled(True)

    def _refresh_games_table(self) -> None:
        self._refresh_games_catalog()
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
            status = "Installed" if entry.installed_key in installed_games else "Not Installed"
            result_index = start_index + row
            self._set_item(
                self.games_table,
                row,
                GAMES_TABLE_COLUMNS["index"],
                str(result_index + 1),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            self._set_games_name_cell(row, entry, status, filtered_entries, result_index, installed_games)
            self._set_item(self.games_table, row, GAMES_TABLE_COLUMNS["collection"], entry.collection_name)
            self._set_item(self.games_table, row, GAMES_TABLE_COLUMNS["status"], status)
        self.games_table.setUpdatesEnabled(True)
        self.games_table.horizontalHeader().setSortIndicator(self._games_sort_column, self._games_sort_order)
        self.games_table.horizontalHeader().setSortIndicatorShown(True)
        self._update_games_pagination(total_items, total_pages)
        if self.stack.currentIndex() == GAMES_SCREEN:
            target = self._target_dir()
            if target is None:
                self._push_status_message("Select a target folder to scan installed games.")
            else:
                self._push_status_message(f"Loaded {total_items} games for {target}")

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
        collection_filter = str(self.games_collection_filter.currentData() or "")
        status_filter = str(self.games_status_filter.currentData() or "")

        filtered_entries = []
        for entry in self._game_entries:
            if is_excluded_game(entry, excluded_games):
                continue
            status = "Installed" if entry.installed_key in installed_games else "Not Installed"
            if name_filter and name_filter not in entry.game_name.casefold():
                continue
            if collection_filter and entry.collection_name != collection_filter and collection_filter not in entry.subcollections:
                continue
            if status_filter and status != status_filter:
                continue
            filtered_entries.append(entry)

        reverse = self._games_sort_order == Qt.SortOrder.DescendingOrder
        return sorted(filtered_entries, key=lambda entry: self._games_sort_key(entry, installed_games), reverse=reverse)

    def _games_sort_key(self, entry, installed_games: set[tuple[str, str]]) -> Any:
        if self._games_sort_column == GAMES_TABLE_COLUMNS["game_name"]:
            return (entry.game_name.casefold(), entry.collection_name.casefold(), entry.rom_path.casefold())
        if self._games_sort_column == GAMES_TABLE_COLUMNS["collection"]:
            return (entry.collection_name.casefold(), entry.game_name.casefold(), entry.rom_path.casefold())
        if self._games_sort_column == GAMES_TABLE_COLUMNS["status"]:
            installed = entry.installed_key in installed_games
            return (0 if installed else 1, entry.game_name.casefold(), entry.collection_name.casefold())
        return (entry.game_name.casefold(), entry.collection_name.casefold(), entry.rom_path.casefold())

    def _refresh_games_catalog(self) -> None:
        target = self._target_dir()
        target_key = str(target) if target is not None else ""
        if self._games_catalog_target == target_key:
            return
        self._games_catalog_target = target_key
        self._game_entries = build_collection_game_catalog(target, self._base_game_entries)
        self._theme_games_cache.clear()
        self._media_root_cache.clear()
        if target is not None:
            self._media_root_cache.update(self._build_collection_media_roots(target))
        self._collection_options = available_collections(target)
        self._sync_games_collection_filter()

    def _sync_games_collection_filter(self) -> None:
        selected = str(self.games_collection_filter.currentData() or "")
        self.games_collection_filter.blockSignals(True)
        self.games_collection_filter.clear()
        self.games_collection_filter.addItem("All Collections", "")
        for collection_name in self._collection_options:
            self.games_collection_filter.addItem(collection_name, collection_name)
        index = max(0, self.games_collection_filter.findData(selected))
        self.games_collection_filter.setCurrentIndex(index)
        self.games_collection_filter.blockSignals(False)

    def _refresh_collections_catalog(self) -> None:
        target = self._target_dir()
        target_key = str(target) if target is not None else ""
        if self._collections_catalog_target == target_key:
            return
        self._collections_catalog_target = target_key
        self._collection_entries = build_collection_catalog(target)

    def _refresh_collections_table(self) -> None:
        self._refresh_collections_catalog()
        filtered_entries = self._sorted_filtered_collections()
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
            self._set_collection_name_cell(row, entry, filtered_entries, result_index)
            self._set_collection_parent_cell(row, entry)
            self._set_collection_game_count_cell(row, entry)
        self.collections_table.setUpdatesEnabled(True)
        self.collections_table.horizontalHeader().setSortIndicator(self._collections_sort_column, self._collections_sort_order)
        self.collections_table.horizontalHeader().setSortIndicatorShown(True)
        self._update_collections_pagination(total_items, total_pages)
        if self.stack.currentIndex() == COLLECTIONS_SCREEN:
            target = self._target_dir()
            if target is None:
                self._push_status_message("Select a target folder to scan collections.")
            else:
                self._push_status_message(f"Loaded {total_items} collections for {target}")

    def _refresh_themes_catalog(self) -> None:
        target = self._target_dir()
        target_key = str(target) if target is not None else ""
        if self._themes_catalog_target == target_key:
            return
        self._themes_catalog_target = target_key
        self._theme_entries = scan_theme_catalog(target)

    def _refresh_themes_screen(self) -> None:
        self._refresh_themes_catalog()
        self._refresh_games_catalog()
        self._refresh_collections_catalog()

        target = self._target_dir()
        selected_name = self._selected_theme_name
        if selected_name is None and self.themes_list.currentItem() is not None:
            selected_name = self.themes_list.currentItem().text()

        self.themes_list.blockSignals(True)
        self.themes_list.clear()
        for entry in self._theme_entries:
            self.themes_list.addItem(entry.name)
        self.themes_results_label.setText(f"{len(self._theme_entries)} theme{'s' if len(self._theme_entries) != 1 else ''}")

        selected_row = -1
        if self._theme_entries:
            if selected_name:
                for index, entry in enumerate(self._theme_entries):
                    if entry.name == selected_name:
                        selected_row = index
                        break
            if selected_row < 0:
                selected_row = 0
            self.themes_list.setCurrentRow(selected_row)
            self._selected_theme_name = self._theme_entries[selected_row].name
        else:
            self._selected_theme_name = None
        self.themes_list.blockSignals(False)
        self._sync_themes_collection_filter()
        self._sync_themes_game_filter()

        if not self._theme_entries:
            if target is None:
                self.themes_name_label.setText("Theme: None")
                self.themes_canvas_label.setText("Canvas Size: Unknown")
            else:
                self.themes_name_label.setText("Theme: None")
                self.themes_canvas_label.setText("Canvas Size: Unknown")
            self.themes_preview_caption.setText("The preview updates after a theme is selected.")
            self.themes_preview.set_preview(None)
            self._set_theme_preview_render_data({})
            self._populate_theme_element_selector(None)
            self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
            if self.stack.currentIndex() == THEMES_SCREEN:
                if target is None:
                    self._push_status_message("Select a target folder to scan themes.")
                else:
                    self._push_status_message(f"No themes found for {target}")
            return

        self._refresh_selected_theme_preview()

    def _sync_themes_collection_filter(self) -> None:
        selected = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        options = tuple(entry.name for entry in self._collection_entries)
        self.themes_collection_filter.blockSignals(True)
        self.themes_collection_filter.clear()
        self.themes_collection_filter.addItem("Select a collection...", "")
        for collection_name in options:
            self.themes_collection_filter.addItem(collection_name, collection_name)
        index = max(0, self.themes_collection_filter.findData(selected))
        self.themes_collection_filter.setCurrentIndex(index)
        self._selected_theme_collection_name = str(self.themes_collection_filter.currentData() or "") or None
        self.themes_collection_filter.blockSignals(False)

    def _handle_theme_selection_changed(self) -> None:
        current_item = self.themes_list.currentItem()
        self._selected_theme_name = current_item.text() if current_item is not None else None
        self._sync_themes_game_filter()
        self._refresh_selected_theme_preview()
        self._save_settings()

    def _handle_theme_collection_changed(self) -> None:
        self._selected_theme_collection_name = str(self.themes_collection_filter.currentData() or "") or None
        self._sync_themes_game_filter()
        self._refresh_selected_theme_preview()
        self._save_settings()

    def _sync_themes_game_filter(self) -> None:
        selected_key = self._selected_theme_game_key
        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        game_entries = self._theme_games_for_collection(selected_collection)
        self.themes_game_filter.blockSignals(True)
        self.themes_game_filter.clear()
        self.themes_game_filter.addItem("Select a game....", None)

        duplicate_counts: dict[str, int] = {}
        for entry in game_entries:
            duplicate_counts[entry.game_name.casefold()] = duplicate_counts.get(entry.game_name.casefold(), 0) + 1

        matched_index = 0
        for index, entry in enumerate(game_entries, start=1):
            display_name = entry.game_name
            if duplicate_counts.get(entry.game_name.casefold(), 0) > 1:
                display_name = f"{entry.game_name} [{entry.collection_name}]"
            item_key = entry.key
            self.themes_game_filter.addItem(display_name, entry)
            if selected_key == item_key:
                matched_index = index
        self.themes_game_filter.setCurrentIndex(matched_index)
        current_entry = self.themes_game_filter.currentData()
        self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
        self._theme_preview_previous_stopped_game_key = None
        self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
        self.themes_game_filter.blockSignals(False)

    def _handle_theme_game_changed(self) -> None:
        current_entry = self.themes_game_filter.currentData()
        self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
        if not self._theme_preview_animation_enabled:
            self._theme_preview_previous_stopped_game_key = None
            self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
        if not self.themes_preview._wheel_anim_active:
            self._refresh_theme_preview_render_only()
        self._save_settings()

    def _handle_theme_wireframe_toggled(self, _state: int) -> None:
        self.themes_preview.set_show_wireframes(self.themes_show_wireframes_checkbox.isChecked())
        self._save_settings()

    def _handle_theme_media_toggled(self, _state: int) -> None:
        self.themes_preview.set_show_media(self.themes_show_media_checkbox.isChecked())
        self._save_settings()

    def _handle_theme_text_toggled(self, _state: int) -> None:
        self.themes_preview.set_show_text(self.themes_show_text_checkbox.isChecked())
        self._save_settings()

    def _refresh_selected_theme_preview(self) -> None:
        if not hasattr(self, "themes_name_label"):
            return
        was_animating = self._theme_preview_animation_enabled
        if was_animating:
            self._theme_preview_cycle_timer.stop()
            self._theme_preview_scroll_timer.stop()
            self._theme_preview_pending_indices.clear()
        theme_name = self._selected_theme_name
        if theme_name is None and self.themes_list.currentItem() is not None:
            theme_name = self.themes_list.currentItem().text()
        target = self._target_dir()
        if target is None or not theme_name:
            self._theme_preview = None
            self._selected_theme_element = None
            self.themes_name_label.setText("Theme: None")
            self.themes_canvas_label.setText("Canvas Size: Unknown")
            self.themes_preview_caption.setText("The preview updates after a theme is selected.")
            self.themes_preview.set_preview(None)
            self._set_theme_preview_render_data({})
            self._theme_preview_previous_stopped_game_key = None
            self._theme_preview_last_stopped_game_key = None
            self._populate_theme_element_selector(None)
            self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
            return

        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        theme_entry = next((entry for entry in self._theme_entries if entry.name == theme_name), None)
        effective_layout_collection = self._find_effective_layout_collection(theme_entry, selected_collection) if theme_entry and selected_collection else None
        preview = build_theme_layout_preview(target, theme_name, selected_collection or None, layout_collection_name=effective_layout_collection)
        self._theme_preview = preview
        self._selected_theme_element = None
        self.themes_preview.set_preview(preview)
        self._set_theme_preview_render_data(self._build_theme_render_data(preview))
        self._theme_preview_previous_stopped_game_key = None
        self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
        self.themes_preview.set_show_wireframes(self.themes_show_wireframes_checkbox.isChecked())
        self.themes_preview.set_show_media(self.themes_show_media_checkbox.isChecked())
        self.themes_preview.set_show_text(self.themes_show_text_checkbox.isChecked())
        self._populate_theme_element_selector(preview)
        self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
        if was_animating:
            self._start_theme_preview_animation()

        self._update_theme_summary(theme_entry, preview)
        if preview is None:
            self.themes_preview_caption.setText("The preview could not be built for the selected theme.")
        elif preview.using_collection_override and preview.selected_collection:
            is_inherited = bool(effective_layout_collection and effective_layout_collection.casefold() != (selected_collection or "").casefold())
            if is_inherited:
                self.themes_preview_caption.setText(f"Previewing {effective_layout_collection} collection layout (inherited) for {preview.selected_collection}.")
            else:
                self.themes_preview_caption.setText(f"Previewing collection override layout for {preview.selected_collection}.")
        elif preview.selected_collection:
            self.themes_preview_caption.setText(f"Previewing root layout. No theme override exists for {preview.selected_collection}.")
        else:
            self.themes_preview_caption.setText("Previewing the theme root layout.")

        if self.stack.currentIndex() == THEMES_SCREEN:
            self._push_status_message(f"Loaded theme preview for {theme_name}")

    def _refresh_theme_preview_render_only(self) -> None:
        preview = self._theme_preview
        if preview is None:
            self._set_theme_preview_render_data({})
            return
        self._set_theme_preview_render_data(self._build_theme_render_data(preview))

    def _handle_theme_preview_selection_changed(self, element: object) -> None:
        self._selected_theme_element = element if isinstance(element, ThemePreviewElement) else None
        self._sync_theme_element_selector(self._selected_theme_element)
        self.themes_preview.select_element(self._selected_theme_element)
        self.themes_element_details.setPlainText(self._format_theme_element_details(self._selected_theme_element))

    def _handle_theme_element_selector_changed(self) -> None:
        index = self.themes_element_selector.currentIndex()
        if index < 0 or index >= len(self._theme_element_index_map):
            return
        selected_element = self._theme_element_index_map[index]
        self._selected_theme_element = selected_element
        self.themes_preview.select_element(selected_element)
        self.themes_element_details.setPlainText(self._format_theme_element_details(selected_element))

    def _populate_theme_element_selector(self, preview: ThemeLayoutPreview | None) -> None:
        self._theme_element_index_map = [None]
        self.themes_element_selector.blockSignals(True)
        self.themes_element_selector.clear()
        self.themes_element_selector.addItem("Select a layout element...", None)
        if preview is not None:
            for element in preview.elements:
                label = f"{element.label} [{element.kind}]"
                self.themes_element_selector.addItem(label, None)
                self._theme_element_index_map.append(element)
        self.themes_element_selector.setCurrentIndex(0)
        self.themes_element_selector.blockSignals(False)

    def _sync_theme_element_selector(self, element: ThemePreviewElement | None) -> None:
        self.themes_element_selector.blockSignals(True)
        target_index = 0
        for index, mapped_element in enumerate(self._theme_element_index_map):
            if mapped_element == element:
                target_index = index
                break
        self.themes_element_selector.setCurrentIndex(target_index)
        self.themes_element_selector.blockSignals(False)

    def _theme_games_for_collection(self, collection_name: str) -> tuple[GameManifestEntry, ...]:
        if not collection_name:
            return tuple()
        cached = self._theme_games_cache.get(collection_name)
        if cached is not None:
            return cached
        entries = [
            entry
            for entry in self._game_entries
            if entry.collection_name == collection_name or collection_name in entry.subcollections
        ]
        by_key = {entry.key: entry for entry in entries}
        for entry in self._scan_collection_game_entries(collection_name):
            by_key.setdefault(entry.key, entry)
        excluded_games = self._excluded_games_for_current_target()
        entries = [entry for entry in by_key.values() if not is_excluded_game(entry, excluded_games)]
        entries.sort(key=lambda entry: (entry.game_name.casefold(), entry.collection_name.casefold(), entry.rom_path.casefold()))
        if not entries:
            child_names = self._child_collection_names(collection_name)
            target = self._target_dir()
            definitions = scan_collection_definitions(target) if target else ()
            definition = next((d for d in definitions if d.name.casefold() == collection_name.casefold()), None)
            is_menu = definition is not None and definition.is_menu_collection
            composite: dict[tuple[str, str], GameManifestEntry] = {}
            if not is_menu:
                for child_name in child_names:
                    for entry in self._theme_games_for_collection(child_name):
                        # Only include real game entries (rom_path has a file extension).
                        # Placeholder/navigation entries have rom_path == collection name (no extension).
                        if Path(entry.rom_path).suffix:
                            composite.setdefault(entry.key, entry)
            if composite:
                entries = sorted(
                    composite.values(),
                    key=lambda e: (e.game_name.casefold(), e.collection_name.casefold(), e.rom_path.casefold()),
                )
            else:
                # Collection is a menu collection or has no game children — show sub-collection names as-is.
                entries = [
                    GameManifestEntry(
                        game_name=child_name,
                        collection_name=collection_name,
                        rom_path=child_name,
                    )
                    for child_name in child_names
                ]
        result = tuple(entries)
        self._theme_games_cache[collection_name] = result
        return result

    def _child_collection_names(self, collection_name: str) -> tuple[str, ...]:
        catalog_entry = next((e for e in self._collection_entries if e.name == collection_name), None)
        if catalog_entry is not None and catalog_entry.child_collections:
            return catalog_entry.child_collections
        target = self._target_dir()
        if target is None:
            return tuple()
        for collection_dir in collection_directory_candidates(target, collection_name):
            medium_artwork_dir = collection_dir / "medium_artwork"
            if not medium_artwork_dir.exists():
                continue
            for slot_dir in sorted(medium_artwork_dir.iterdir(), key=lambda p: p.name.casefold()):
                if not slot_dir.is_dir():
                    continue
                children: list[str] = []
                for path in sorted(slot_dir.iterdir(), key=lambda p: p.name.casefold()):
                    if not path.is_file():
                        continue
                    stem = path.stem.strip()
                    if stem and stem.casefold() != "default" and stem not in children:
                        children.append(stem)
                if children:
                    return tuple(children)
        return tuple()

    def _find_effective_layout_collection(self, theme_entry: ThemeCatalogEntry, collection_name: str) -> str | None:
        if not collection_name:
            return None
        if self._collection_has_layout(theme_entry, collection_name):
            return collection_name

        cat = {e.name: e for e in self._collection_entries}
        entry = cat.get(collection_name)
        if entry is None:
            return None

        # Seed the upward walk from direct parents.
        # For orphan collections (no parents, e.g. MAME), also seed from the
        # navigation-aggregate parents of the collection's children — this lets
        # MAME inherit the "1 ARCADES" layout via:
        #   MAME → child "1 Fighting" → parent "2 ARCADE GENRES" → parent "1 ARCADES"
        # We never expand children of visited nodes, so we can't accidentally
        # drift sideways to unrelated collections like Jukebox.
        visited: set[str] = {collection_name.casefold()}
        seeds: list[str] = list(entry.parent_collections)
        if not entry.parent_collections:
            seen_seeds: set[str] = set()
            for child in entry.child_collections:
                child_entry = cat.get(child)
                if child_entry is None:
                    continue
                for p in child_entry.parent_collections:
                    if p.casefold() != collection_name.casefold() and p.casefold() not in seen_seeds:
                        seen_seeds.add(p.casefold())
                        seeds.append(p)

        queue: list[str] = seeds
        while queue:
            candidate = queue.pop(0)
            if candidate.casefold() in visited:
                continue
            visited.add(candidate.casefold())
            if self._collection_has_layout(theme_entry, candidate):
                return candidate
            candidate_entry = cat.get(candidate)
            if candidate_entry is not None:
                queue.extend(n for n in candidate_entry.parent_collections if n.casefold() not in visited)
        return None

    def _collection_has_layout(self, theme_entry: ThemeCatalogEntry, collection_name: str) -> bool:
        layout_dir = theme_entry.root_dir / "collections" / collection_name / "layout"
        return (layout_dir / "layout.xml").exists() or (layout_dir / "layout.lua").exists()

    def _scan_collection_game_entries(self, collection_name: str) -> tuple[GameManifestEntry, ...]:
        target = self._target_dir()
        if target is None:
            return tuple()
        definitions = scan_collection_definitions(target)
        definition = next((d for d in definitions if d.name.casefold() == collection_name.casefold()), None)
        valid_extensions: frozenset[str] | None = frozenset(definition.valid_extensions) if definition and definition.valid_extensions else None
        scanned: list[GameManifestEntry] = []
        seen_paths: set[str] = set()
        for collection_dir in collection_directory_candidates(target, collection_name):
            roms_dir = collection_dir / "roms"
            if not roms_dir.exists() or not roms_dir.is_dir():
                continue
            for path in sorted(roms_dir.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_file():
                    continue
                if valid_extensions is not None and path.suffix.casefold().lstrip('.') not in valid_extensions:
                    continue
                relative_path = path.relative_to(roms_dir).as_posix()
                key = relative_path.casefold()
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                scanned.append(
                    GameManifestEntry(
                        game_name=path.name,
                        collection_name=collection_name,
                        rom_path=relative_path,
                        source_pack=collection_name,
                        install_collection_name=collection_name,
                    )
                )
        return tuple(scanned)

    def _build_theme_render_data(self, preview: ThemeLayoutPreview | None) -> dict[ThemePreviewElement, ThemePreviewRenderData]:
        if preview is None:
            return {}
        selected_collection = preview.selected_collection
        selected_game = self.themes_game_filter.currentData()
        game_entry = selected_game if isinstance(selected_game, GameManifestEntry) else None
        collection_games = self._theme_games_for_collection(selected_collection or "")
        collection_index = 0
        if game_entry is not None:
            for index, entry in enumerate(collection_games, start=1):
                if entry.key == game_entry.key:
                    collection_index = index
                    break
        return self._build_theme_render_data_for_state(
            preview,
            selected_collection,
            game_entry,
            collection_games,
            collection_index,
        )

    def _build_theme_render_data_for_state(
        self,
        preview: ThemeLayoutPreview,
        selected_collection: str | None,
        game_entry: GameManifestEntry | None,
        collection_games: tuple[GameManifestEntry, ...],
        collection_index: int,
        *,
        scroll_only: bool = False,
    ) -> dict[ThemePreviewElement, ThemePreviewRenderData]:
        if self._target_dir() is None:
            return {}
        theme_entry = next((entry for entry in self._theme_entries if entry.name == preview.theme_name), None)
        render_data: dict[ThemePreviewElement, ThemePreviewRenderData] = {}
        layout_collection = preview.layout_collection
        for element in preview.elements:
            if scroll_only and not element.menu_scroll_reload:
                continue
            resolved = self._resolve_theme_preview_element_render(
                element,
                theme_entry,
                selected_collection,
                game_entry,
                collection_games,
                collection_index,
                layout_collection=layout_collection,
            )
            if resolved is not None:
                render_data[element] = resolved
        return render_data

    def _build_theme_scroll_render_data(
        self,
        preview: ThemeLayoutPreview,
        target_zero_index: int,
    ) -> dict[ThemePreviewElement, ThemePreviewRenderData]:
        selected_collection = preview.selected_collection or self._selected_theme_collection_name or ""
        collection_games = self._theme_games_for_collection(selected_collection)
        if not collection_games:
            return {}
        total_games = len(collection_games)
        resolved_zero_index = target_zero_index % total_games
        game_entry = collection_games[resolved_zero_index]
        return self._build_theme_render_data_for_state(
            preview,
            selected_collection or None,
            game_entry,
            collection_games,
            resolved_zero_index + 1,
            scroll_only=True,
        )

    def _set_theme_preview_render_data(self, render_data: dict[ThemePreviewElement, ThemePreviewRenderData], *, transition: bool = True) -> None:
        self._theme_preview_render_data = dict(render_data)
        self.themes_preview.set_render_data(self._theme_preview_render_data, transition=transition)
        self._sync_theme_preview_video_sessions()
        self._sync_theme_preview_animation_controls()

    def _handle_theme_preview_scroll_index_changed(self, target_zero_index: int) -> None:
        preview = self._theme_preview
        if preview is None or not self._theme_preview_wheel_spinning:
            return
        scroll_data = self._build_theme_scroll_render_data(preview, target_zero_index)
        merged = {
            element: data
            for element, data in self._theme_preview_render_data.items()
            if not element.menu_scroll_reload
        }
        merged.update(scroll_data)
        self._set_theme_preview_render_data(merged, transition=False)

    def _sync_theme_preview_video_sessions(self) -> None:
        desired = {
            element: data
            for element, data in self._theme_preview_render_data.items()
            if data.video_path is not None
        }
        stale_elements = [element for element in self._theme_preview_video_sessions if element not in desired]
        for element in stale_elements:
            self._dispose_theme_preview_video_session(element)

        if not (HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QAudioOutput is not None and QVideoSink is not None):
            return

        for element, data in desired.items():
            session = self._theme_preview_video_sessions.get(element)
            if session is not None and session.video_path == data.video_path:
                self._apply_theme_preview_session_state(session)
                continue
            if session is not None:
                self._dispose_theme_preview_video_session(element)
            video_path = data.video_path
            if video_path is None:
                continue
            audio_output = QAudioOutput(self)
            video_sink = QVideoSink(self)
            player = QMediaPlayer(self)
            audio_output.setVolume(1.0)
            player.setAudioOutput(audio_output)
            player.setVideoOutput(video_sink)
            player.setSource(QUrl.fromLocalFile(str(video_path)))
            video_sink.videoFrameChanged.connect(
                lambda frame, current_element=element: self._handle_theme_preview_video_frame(current_element, frame)
            )
            player.mediaStatusChanged.connect(
                lambda status, current_element=element: self._handle_theme_preview_video_status_changed(current_element, status)
            )
            session = ThemePreviewVideoSession(
                element=element,
                video_path=video_path,
                player=player,
                audio_output=audio_output,
                video_sink=video_sink,
            )
            self._theme_preview_video_sessions[element] = session
            self._apply_theme_preview_session_state(session)

    def _dispose_theme_preview_video_session(self, element: ThemePreviewElement) -> None:
        session = self._theme_preview_video_sessions.pop(element, None)
        if session is None:
            return
        try:
            session.player.stop()
        except Exception:
            pass
        session.player.deleteLater()
        session.audio_output.deleteLater()
        session.video_sink.deleteLater()

    def _dispose_all_theme_preview_video_sessions(self) -> None:
        for element in list(self._theme_preview_video_sessions.keys()):
            self._dispose_theme_preview_video_session(element)

    def _apply_theme_preview_session_state(self, session: ThemePreviewVideoSession) -> None:
        session.audio_output.setMuted(self._theme_preview_muted)
        should_play = self._theme_preview_animation_enabled
        if should_play:
            session.player.play()
        else:
            session.player.pause()

    @staticmethod
    def _theme_preview_pixmap_from_frame(frame) -> QPixmap | None:
        if frame is None:
            return None
        try:
            if hasattr(frame, "isValid") and not frame.isValid():
                return None
        except Exception:
            return None

        try:
            width = int(frame.width()) if hasattr(frame, "width") else 0
            height = int(frame.height()) if hasattr(frame, "height") else 0
        except Exception:
            width = 0
            height = 0

        if width > 0 and height > 0 and QVideoFrame is not None and hasattr(frame, "paint"):
            image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0xFF000000)
            painter = QPainter(image)
            painted = False
            try:
                options = QVideoFrame.PaintOptions()
                options.aspectRatioMode = Qt.AspectRatioMode.IgnoreAspectRatio
                options.backgroundColor = QColor("#000000")
                frame.paint(painter, QRectF(0.0, 0.0, float(width), float(height)), options)
                painted = True
            except Exception:
                painted = False
            finally:
                painter.end()
            if painted and not image.isNull():
                pixmap = QPixmap.fromImage(image.copy())
                if not pixmap.isNull():
                    return pixmap

        try:
            image = frame.toImage()
        except Exception:
            return None
        if image is None or image.isNull():
            return None
        image = image.convertToFormat(QImage.Format.Format_ARGB32).copy()
        if image.isNull():
            return None
        pixmap = QPixmap.fromImage(image)
        return None if pixmap.isNull() else pixmap

    def _handle_theme_preview_video_frame(self, element: ThemePreviewElement, frame) -> None:
        if element not in self._theme_preview_render_data:
            return
        pixmap = MainWindow._theme_preview_pixmap_from_frame(frame)
        if pixmap is None or pixmap.isNull():
            return
        current = self._theme_preview_render_data.get(element)
        if current is None:
            return
        self._theme_preview_render_data[element] = replace(current, pixmap=pixmap)
        self._theme_video_dirty = True

    def _flush_theme_video_repaint(self) -> None:
        if self._theme_video_dirty:
            self._theme_video_dirty = False
            self.themes_preview.set_render_data(self._theme_preview_render_data)

    def _handle_theme_preview_video_status_changed(self, element: ThemePreviewElement, status) -> None:
        session = self._theme_preview_video_sessions.get(element)
        if session is None:
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) and not session.initial_seek_done:
            session.initial_seek_done = True
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            session.player.setPosition(0)
            if self._theme_preview_animation_enabled:
                session.player.play()

    def _start_wheel_animation(self, advance_count: int, *, target_offset: int | None = None) -> None:
        preview = self._theme_preview
        if preview is None:
            return
        selected_collection = preview.selected_collection or self._selected_theme_collection_name or ""
        collection_games = self._theme_games_for_collection(selected_collection)
        total_games = len(collection_games)
        if total_games == 0:
            return
        menu_groups: list[list[ThemePreviewElement]] = []
        current_group: list[ThemePreviewElement] = []
        for element in preview.elements:
            if element.kind == "menu":
                current_group.append(element)
                continue
            if current_group:
                menu_groups.append(current_group)
                current_group = []
        if current_group:
            menu_groups.append(current_group)
        if not menu_groups:
            return
        current_combo_index = self.themes_game_filter.currentIndex()
        start_game_0 = max(0, current_combo_index - 1)
        theme_entry = next((entry for entry in self._theme_entries if entry.name == preview.theme_name), None)
        built_groups: list[tuple[list[ThemePreviewElement], dict[int, QPixmap], int]] = []
        for group in menu_groups:
            slot_elements = sorted(
                group,
                key=lambda e: (
                    e.menu_position if e.menu_position is not None else 10_000,
                    e.label.casefold(),
                ),
            )
            if not slot_elements:
                continue
            sel_idx = next((i for i, e in enumerate(slot_elements) if e.selected), 0)
            n = len(slot_elements)
            first_needed_offset = -(sel_idx + 1)
            last_needed_offset = n - sel_idx + advance_count
            ref_element = slot_elements[sel_idx]
            slot_key = (ref_element.slot_name or "").strip().casefold()
            mode_key = (ref_element.mode or "").casefold()
            pixmaps: dict[int, QPixmap] = {}
            for offset in range(first_needed_offset, last_needed_offset + 1):
                game_0 = (start_game_0 + offset) % total_games
                if game_0 in pixmaps:
                    continue
                game_entry = collection_games[game_0]
                base_names = _game_name_candidates(Path(game_entry.rom_path).name)
                media_root = self._resolve_theme_game_media_root(game_entry)
                if mode_key in {"commonlayout", "common"} and theme_entry is not None:
                    common_render = self._resolve_common_theme_render(theme_entry, slot_key, game_entry, selected_collection or None, self._common_root_for_mode(theme_entry, mode_key))
                    if common_render is not None and common_render.pixmap is not None:
                        pixmaps[game_0] = common_render.pixmap
                        continue
                if mode_key == "layout" and theme_entry is not None:
                    child_name = Path(game_entry.rom_path).stem
                    child_sa = theme_entry.root_dir / "collections" / child_name / "system_artwork"
                    for try_slot in (slot_key, "eplogo", "mainlogo"):
                        child_logo = _find_named_collection_media_file(child_sa, try_slot, IMAGE_MEDIA_SUFFIXES)
                        if child_logo is not None:
                            pixmap = QPixmap(str(child_logo))
                            if not pixmap.isNull():
                                pixmaps[game_0] = pixmap
                                break
                    if game_0 in pixmaps:
                        continue
                media_path = self._resolve_game_media_path(media_root, base_names, slot_key)
                if media_path is not None:
                    pixmap = QPixmap(str(media_path))
                    if not pixmap.isNull():
                        pixmaps[game_0] = pixmap
                        continue
                if ref_element.text_fallback and game_0 not in pixmaps:
                    item_text = game_entry.game_name
                    text_fmt = (ref_element.text_format or "").casefold()
                    if text_fmt == "uppercase":
                        item_text = item_text.upper()
                    text_pix = self._make_wheel_text_pixmap(item_text, ref_element)
                    if text_pix is not None and not text_pix.isNull():
                        pixmaps[game_0] = text_pix
            built_groups.append((slot_elements, pixmaps, sel_idx))
        if not built_groups:
            return
        effective_target = target_offset if target_offset is not None else advance_count
        duration_ms = max(250, int(advance_count / 4.0 * 1000))
        self._theme_preview_wheel_spinning = True
        for session in self._theme_preview_video_sessions.values():
            self._apply_theme_preview_session_state(session)
        primary_elements, primary_pixmaps, primary_sel_idx = built_groups[0]
        extra_groups = built_groups[1:]
        self.themes_preview.start_wheel_animation(
            primary_elements, primary_pixmaps, primary_sel_idx, start_game_0, advance_count, total_games, duration_ms,
            target_advance=effective_target,
            extra_groups=extra_groups,
        )

    def _on_wheel_animation_finished(self) -> None:
        self._theme_preview_wheel_spinning = False
        for session in self._theme_preview_video_sessions.values():
            self._apply_theme_preview_session_state(session)
        total_games = self.themes_preview._wheel_anim_total_games
        start_game_0 = self.themes_preview._wheel_anim_start_game_0
        target_advance = self.themes_preview._wheel_anim_target_advance
        target_game_0 = (start_game_0 + target_advance) % total_games
        combo_index = target_game_0 + 1
        if combo_index < self.themes_game_filter.count():
            self.themes_game_filter.blockSignals(True)
            self.themes_game_filter.setCurrentIndex(combo_index)
            self.themes_game_filter.blockSignals(False)
            current_entry = self.themes_game_filter.currentData()
            self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
            self._theme_preview_previous_stopped_game_key = self._theme_preview_last_stopped_game_key
            self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
            self._set_theme_preview_render_data(self._build_theme_render_data(self._theme_preview), transition=False)
        self.themes_preview.stop_wheel_animation()
        self._schedule_theme_preview_cycle()

    def _jump_theme_preview_to_index(self, zero_index: int) -> None:
        combo_index = zero_index + 1
        if combo_index < 1 or combo_index >= self.themes_game_filter.count():
            return
        self._theme_preview_pending_indices.clear()
        self._theme_preview_cycle_timer.stop()
        self._theme_preview_scroll_timer.stop()
        self._theme_preview_wheel_spinning = False
        self.themes_preview.stop_wheel_animation()
        self.themes_game_filter.setCurrentIndex(combo_index)
        current_entry = self.themes_game_filter.currentData()
        self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
        self._theme_preview_previous_stopped_game_key = self._theme_preview_last_stopped_game_key
        self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
        self._refresh_theme_preview_render_only()
        if self._theme_preview_animation_enabled:
            self._schedule_theme_preview_cycle()

    def _trigger_theme_preview_random_advance(self) -> None:
        if self._theme_preview is None or self._theme_preview_wheel_spinning:
            return
        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        game_entries = self._theme_games_for_collection(selected_collection)
        total_games = len(game_entries)
        if total_games <= 1:
            return
        self._theme_preview_cycle_timer.stop()
        advance_count = random.randint(1, min(max(20, total_games // 10), total_games - 1))
        slot_elements = [e for e in self._theme_preview.elements if e.kind == "menu" and (e.slot_name or "").casefold() == "logo"]
        if slot_elements:
            visible_advance = min(advance_count, 20)
            self._start_wheel_animation(visible_advance)
            return
        current_index = max(0, self.themes_game_filter.currentIndex() - 1)
        target_zero_index = (current_index + advance_count) % total_games
        self._jump_theme_preview_to_index(target_zero_index)

    def _handle_theme_preview_previous_requested(self) -> None:
        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        game_entries = self._theme_games_for_collection(selected_collection)
        if not game_entries:
            return
        if self._theme_preview_animation_enabled:
            target_key = self._theme_preview_previous_stopped_game_key
            if target_key is None:
                current_index = max(0, self.themes_game_filter.currentIndex() - 1)
                target_zero_index = (current_index - 1) % len(game_entries)
            else:
                target_zero_index = next((idx for idx, entry in enumerate(game_entries) if entry.key == target_key), 0)
            self._jump_theme_preview_to_index(target_zero_index)
            return
        current_index = max(0, self.themes_game_filter.currentIndex() - 1)
        target_zero_index = (current_index - 1) % len(game_entries)
        self._jump_theme_preview_to_index(target_zero_index)

    def _handle_theme_preview_next_requested(self) -> None:
        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        game_entries = self._theme_games_for_collection(selected_collection)
        if not game_entries:
            return
        if self._theme_preview_animation_enabled:
            self._trigger_theme_preview_random_advance()
            return
        current_index = max(0, self.themes_game_filter.currentIndex() - 1)
        target_zero_index = (current_index + 1) % len(game_entries)
        self._jump_theme_preview_to_index(target_zero_index)

    def _make_wheel_text_pixmap(self, text: str, ref_element: ThemePreviewElement) -> QPixmap | None:
        """Render a collection/item name as a pixmap for the wheel animation text fallback."""
        if not text:
            return None
        pix_w, pix_h = 600, 80
        pixmap = QPixmap(pix_w, pix_h)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        font = QFont(self.font())
        if ref_element.font_path:
            family = self.themes_preview._font_family_for_path(ref_element.font_path)
            if family:
                font.setFamily(family)
        font.setPixelSize(max(16, pix_h - 16))
        font.setBold(True)
        painter.setFont(font)
        color_str = "#" + (ref_element.font_color or "ffffff").lstrip("#")
        painter.setPen(QColor(color_str))
        painter.drawText(QRectF(0, 0, pix_w, pix_h), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return pixmap

    def _toggle_theme_preview_animation(self) -> None:
        self._theme_preview_animation_enabled = not self._theme_preview_animation_enabled
        if self._theme_preview_animation_enabled:
            self._start_theme_preview_animation()
        else:
            self._stop_theme_preview_animation()
        self._sync_theme_preview_animation_controls()

    def _toggle_theme_preview_mute(self) -> None:
        self._theme_preview_muted = not self._theme_preview_muted
        for session in self._theme_preview_video_sessions.values():
            session.audio_output.setMuted(self._theme_preview_muted)
        self._sync_theme_preview_animation_controls()

    def _start_theme_preview_animation(self) -> None:
        self._sync_theme_preview_video_sessions()
        for session in self._theme_preview_video_sessions.values():
            self._apply_theme_preview_session_state(session)
        self._theme_video_repaint_timer.start()
        self._schedule_theme_preview_cycle()

    def _stop_theme_preview_animation(self) -> None:
        self._theme_preview_cycle_timer.stop()
        self._theme_preview_scroll_timer.stop()
        self._theme_video_repaint_timer.stop()
        self._theme_video_dirty = False
        self._theme_preview_wheel_spinning = False
        self._theme_preview_pending_indices.clear()
        self.themes_preview.stop_wheel_animation()
        for session in self._theme_preview_video_sessions.values():
            self._apply_theme_preview_session_state(session)

    def _sync_theme_preview_animation_controls(self) -> None:
        has_preview = self._theme_preview is not None
        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        can_animate_wheel = bool(selected_collection and self._theme_games_for_collection(selected_collection))
        has_video = bool(self._theme_preview_video_sessions) or any(data.video_path is not None for data in self._theme_preview_render_data.values())
        if not has_preview and self._theme_preview_animation_enabled:
            self._theme_preview_animation_enabled = False
            self._stop_theme_preview_animation()
        self.themes_preview.set_animation_controls(
            can_play=has_preview and (can_animate_wheel or has_video),
            can_mute=has_video,
            is_playing=self._theme_preview_animation_enabled,
            is_muted=self._theme_preview_muted,
        )

    def _theme_preview_wait_interval_ms(self) -> int:
        base_wait_ms = 5000
        target = self._target_dir()
        if target is not None:
            settings = _read_settings_conf(target)
            try:
                configured_next_time = int(float((settings.get("attractModeNextTime") or "0").strip() or "0"))
            except ValueError:
                configured_next_time = 0
            if configured_next_time > 0:
                base_wait_ms = max(base_wait_ms, configured_next_time * 1000)
        preview = self._theme_preview
        if preview is None:
            return base_wait_ms
        max_scroll_start = 0.0
        for element in preview.elements:
            if element.kind not in {"scrolling_text", "reloadable_scrolling_text"}:
                continue
            max_scroll_start = max(max_scroll_start, float(element.scroll_start_time or 0.0))
        if max_scroll_start <= 0.0:
            return base_wait_ms
        # Allow long-delay scrolling text such as CoinOPS story panels to actually begin moving
        # before the wheel advances again.
        return max(base_wait_ms, int((max_scroll_start * 1000.0) + 2000.0))

    def _schedule_theme_preview_cycle(self) -> None:
        self._theme_preview_cycle_timer.stop()
        self.themes_preview._transition_duration_ms = 400
        if not self._theme_preview_animation_enabled:
            return
        self._theme_preview_cycle_timer.start(self._theme_preview_wait_interval_ms())

    def _advance_theme_preview_attract_mode(self) -> None:
        if not self._theme_preview_animation_enabled or self._theme_preview is None:
            return
        selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
        game_entries = self._theme_games_for_collection(selected_collection)
        if not game_entries:
            self._schedule_theme_preview_cycle()
            return
        if self.themes_game_filter.currentIndex() <= 0 and self.themes_game_filter.count() > 1:
            self.themes_game_filter.setCurrentIndex(1)
            self._selected_theme_game_key = self.themes_game_filter.currentData().key if isinstance(self.themes_game_filter.currentData(), GameManifestEntry) else None
            game_entries = self._theme_games_for_collection(selected_collection)
        current_index = max(0, self.themes_game_filter.currentIndex() - 1)
        total_games = len(game_entries)
        if total_games <= 1:
            self._schedule_theme_preview_cycle()
            return
        advance_count = random.randint(1, min(max(20, total_games // 10), total_games - 1))
        slot_elements = [e for e in self._theme_preview.elements if e.kind == "menu" and (e.slot_name or "").casefold() == "logo"]
        if slot_elements:
            # Keep the logical destination aligned with the visible destination. If the preview
            # caps the wheel spin for performance, do not jump the selected game farther than
            # the wheel actually stops.
            visible_advance = min(advance_count, 20)
            self._start_wheel_animation(visible_advance)
        else:
            target_index = (current_index + advance_count) % total_games
            combo_index = target_index + 1
            self.themes_preview._transition_duration_ms = max(250, int(advance_count / 4.0 * 1000))
            if combo_index < self.themes_game_filter.count():
                self.themes_game_filter.setCurrentIndex(combo_index)
            self._schedule_theme_preview_cycle()

    def _build_theme_preview_scroll_path(self, current_index: int, advance_count: int, total_games: int) -> list[int]:
        if total_games <= 0 or advance_count <= 0:
            return []
        if advance_count <= 72:
            return [((current_index + offset) % total_games) for offset in range(1, advance_count + 1)]
        max_steps = 72
        step_indices: list[int] = []
        previous_target = current_index
        for frame_index in range(1, max_steps + 1):
            target_offset = max(1, round((advance_count * frame_index) / max_steps))
            target_index = (current_index + target_offset) % total_games
            if frame_index == max_steps or target_index != previous_target:
                step_indices.append(target_index)
                previous_target = target_index
        return step_indices

    def _step_theme_preview_attract_animation(self) -> None:
        if not self._theme_preview_pending_indices:
            self._theme_preview_scroll_timer.stop()
            self._schedule_theme_preview_cycle()
            return
        target_zero_index = self._theme_preview_pending_indices.popleft()
        combo_index = target_zero_index + 1
        if combo_index < self.themes_game_filter.count():
            self.themes_game_filter.setCurrentIndex(combo_index)
        if not self._theme_preview_pending_indices:
            self._theme_preview_scroll_timer.stop()
            self._theme_preview_wheel_spinning = False
            for session in self._theme_preview_video_sessions.values():
                self._apply_theme_preview_session_state(session)
            self._schedule_theme_preview_cycle()

    def _is_theme_menu_highlight_overlay(
        self,
        element: ThemePreviewElement,
        selected_menu_logos: tuple[ThemePreviewElement, ...],
    ) -> bool:
        if element.kind not in {"image", "reloadable_image"}:
            return False
        if (element.slot_name or "").casefold() != "logo":
            return False
        if element.source_path:
            return False
        for selected in selected_menu_logos:
            if abs((element.x + (element.width / 2.0)) - (selected.x + (selected.width / 2.0))) > 4.0:
                continue
            if abs((element.y + (element.height / 2.0)) - (selected.y + (selected.height / 2.0))) > 4.0:
                continue
            if (element.layer or 0) >= (selected.layer or 0):
                continue
            return True
        return False

    def _resolve_theme_preview_element_render(
        self,
        element: ThemePreviewElement,
        theme_entry: ThemeCatalogEntry | None,
        collection_name: str | None,
        game_entry: GameManifestEntry | None,
        collection_games: tuple[GameManifestEntry, ...],
        collection_index: int,
        layout_collection: str | None = None,
    ) -> ThemePreviewRenderData | None:
        mode_key = (element.mode or "").casefold()
        static_render = self._resolve_static_theme_render(element)
        if static_render is not None:
            return static_render

        if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"}:
            text_value = self._resolve_theme_preview_text(element, collection_name, game_entry, collection_games, collection_index)
            if text_value:
                return ThemePreviewRenderData(text=text_value)

        if collection_name and mode_key == "systemlayout":
            collection_render = self._resolve_collection_theme_render(element, collection_name)
            if collection_render is not None:
                return collection_render

        if mode_key == "layout" and theme_entry is not None and layout_collection:
            layout_render = self._resolve_layout_theme_render(element, theme_entry, layout_collection, game_entry)
            if layout_render is not None:
                return layout_render
            # For menu items, fall through to game-specific and text-fallback paths so that
            # sub-collection names can be shown as text when no per-item logo exists.
            if element.kind != "menu":
                return None

        if mode_key == "layout_preferred" and theme_entry is not None and layout_collection:
            layout_preferred_render = self._resolve_layout_preferred_render(
                element,
                theme_entry,
                collection_name,
                layout_collection,
                game_entry,
            )
            if layout_preferred_render is not None:
                return layout_preferred_render

        if game_entry is not None:
            game_render = self._resolve_game_theme_render(element, theme_entry, collection_name, game_entry, collection_games, collection_index)
            if game_render is not None:
                return game_render

        return None

    def _resolve_static_theme_render(self, element: ThemePreviewElement) -> ThemePreviewRenderData | None:
        if element.source_path:
            source_path = Path(element.source_path)
            if element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"} and source_path.suffix.casefold() in IMAGE_MEDIA_SUFFIXES:
                pixmap = QPixmap(str(source_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
            if element.kind in {"video", "reloadable_video"} and source_path.suffix.casefold() in VIDEO_MEDIA_SUFFIXES:
                pixmap = _extract_video_thumbnail(source_path)
                if pixmap is not None and not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap, video_path=source_path)
            if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"} and source_path.suffix.casefold() in STORY_MEDIA_SUFFIXES:
                return ThemePreviewRenderData(text=_read_story_text(source_path))
        if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"} and element.value:
            return ThemePreviewRenderData(text=element.value)
        return None

    def _resolve_collection_theme_render(self, element: ThemePreviewElement, collection_name: str) -> ThemePreviewRenderData | None:
        slot_name = (element.slot_name or "").strip()
        if not slot_name:
            return None
        media_root = _resolve_collection_media_root(self._target_dir(), collection_name)
        if element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
            media_path = _find_named_collection_media_file(media_root, slot_name, IMAGE_MEDIA_SUFFIXES)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if element.kind in {"video", "reloadable_video"}:
            media_path = _find_named_collection_media_file(media_root, slot_name, VIDEO_MEDIA_SUFFIXES)
            if media_path is None:
                media_path = _find_first_collection_video(media_root)
            if media_path is not None:
                pixmap = _extract_video_thumbnail(media_path)
                if pixmap is not None and not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap, video_path=media_path)
        return None

    def _resolve_layout_theme_render(
        self,
        element: ThemePreviewElement,
        theme_entry: ThemeCatalogEntry,
        layout_collection: str,
        game_entry: GameManifestEntry | None,
        *,
        allow_system_fallback: bool = True,
    ) -> ThemePreviewRenderData | None:
        slot_key = (element.slot_name or "").strip().casefold()
        if not slot_key:
            return None
        layout_root = theme_entry.root_dir / "collections" / layout_collection
        system_artwork = layout_root / "system_artwork"
        medium_artwork = layout_root / "medium_artwork"
        if element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
            if game_entry is not None:
                base_names = _game_name_candidates(Path(game_entry.rom_path).name)
                media_path = _find_matching_media_file(medium_artwork / slot_key, base_names, IMAGE_MEDIA_SUFFIXES)
                if media_path is not None:
                    pixmap = QPixmap(str(media_path))
                    if not pixmap.isNull():
                        return ThemePreviewRenderData(pixmap=pixmap)
            # Generic named collection file (e.g. logo.png) is the collection's own branding.
            # Skip it for menu items — each slot needs a per-item image, not the parent's logo.
            if allow_system_fallback and element.kind != "menu" and system_artwork.exists():
                media_path = _find_named_collection_media_file(system_artwork, slot_key, IMAGE_MEDIA_SUFFIXES)
                if media_path is not None:
                    pixmap = QPixmap(str(media_path))
                    if not pixmap.isNull():
                        return ThemePreviewRenderData(pixmap=pixmap)
        if element.kind in {"video", "reloadable_video"}:
            if game_entry is not None:
                base_names = _game_name_candidates(Path(game_entry.rom_path).name)
                video_path = _find_matching_media_file(medium_artwork / slot_key, base_names, VIDEO_MEDIA_SUFFIXES)
                if video_path is not None:
                    pixmap = _extract_video_thumbnail(video_path)
                    if pixmap is not None and not pixmap.isNull():
                        return ThemePreviewRenderData(pixmap=pixmap, video_path=video_path)
        return None

    def _resolve_layout_preferred_render(
        self,
        element: ThemePreviewElement,
        theme_entry: ThemeCatalogEntry,
        collection_name: str | None,
        layout_collection: str,
        game_entry: GameManifestEntry | None,
    ) -> ThemePreviewRenderData | None:
        if game_entry is None:
            return self._resolve_layout_theme_render(element, theme_entry, layout_collection, game_entry)

        if collection_name:
            selected_collection_render = self._resolve_layout_theme_render(
                element,
                theme_entry,
                collection_name,
                game_entry,
                allow_system_fallback=False,
            )
            if selected_collection_render is not None:
                return selected_collection_render

        game_render = self._resolve_game_theme_render(
            element,
            theme_entry,
            collection_name,
            game_entry,
            tuple(),
            0,
        )
        if game_render is not None and game_render.pixmap is not None:
            return game_render

        if collection_name and collection_name.casefold() != layout_collection.casefold():
            inherited_layout_render = self._resolve_layout_theme_render(
                element,
                theme_entry,
                layout_collection,
                game_entry,
                allow_system_fallback=True,
            )
            if inherited_layout_render is not None:
                return inherited_layout_render

        if collection_name and collection_name.casefold() == layout_collection.casefold():
            same_layout_render = self._resolve_layout_theme_render(
                element,
                theme_entry,
                layout_collection,
                game_entry,
                allow_system_fallback=True,
            )
            if same_layout_render is not None:
                return same_layout_render
        return None

    def _resolve_game_theme_render(
        self,
        element: ThemePreviewElement,
        theme_entry: ThemeCatalogEntry | None,
        collection_name: str | None,
        game_entry: GameManifestEntry,
        collection_games: tuple[GameManifestEntry, ...],
        collection_index: int,
    ) -> ThemePreviewRenderData | None:
        slot_key = (element.slot_name or "").strip().casefold()
        mode_key = (element.mode or "").casefold()
        display_entry = self._theme_menu_entry_for_element(element, game_entry, collection_games, collection_index)
        base_names = _game_name_candidates(Path(display_entry.rom_path).name)
        media_root = self._resolve_theme_game_media_root(display_entry)

        if mode_key in {"commonlayout", "common"} and theme_entry is not None:
            common_render = self._resolve_common_theme_render(theme_entry, slot_key, display_entry, collection_name, self._common_root_for_mode(theme_entry, mode_key))
            if common_render is not None:
                return common_render

        if element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
            media_path = self._resolve_game_media_path(media_root, base_names, slot_key)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
            fallback_key = (element.image_type or "").strip().casefold()
            if fallback_key and fallback_key != slot_key:
                media_path = self._resolve_game_media_path(media_root, base_names, fallback_key)
                if media_path is not None:
                    pixmap = QPixmap(str(media_path))
                    if not pixmap.isNull():
                        return ThemePreviewRenderData(pixmap=pixmap)
            if slot_key == "logo":
                child_name = Path(display_entry.rom_path).stem
                child_media_root = _resolve_collection_media_root(self._target_dir(), child_name)
                child_media_path = _find_named_collection_media_file(child_media_root, "logo", IMAGE_MEDIA_SUFFIXES)
                if child_media_path is not None:
                    pixmap = QPixmap(str(child_media_path))
                    if not pixmap.isNull():
                        return ThemePreviewRenderData(pixmap=pixmap)
        if element.kind in {"video", "reloadable_video"} and mode_key in {"commonlayout", "common"} and theme_entry is not None:
            effective_slot = slot_key or (element.image_type or "").strip().casefold()
            common_video = self._resolve_common_layout_video(theme_entry, effective_slot, self._common_root_for_mode(theme_entry, mode_key))
            if common_video is not None:
                pixmap = _extract_video_thumbnail(common_video)
                if pixmap is not None and not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap, video_path=common_video)
        if element.kind in {"video", "reloadable_video"}:
            video_path = self._resolve_game_video_path(media_root, base_names, slot_key)
            if video_path is not None:
                pixmap = _extract_video_thumbnail(video_path)
                if pixmap is not None and not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap, video_path=video_path)
            fallback_key = (element.image_type or "").strip().casefold() or slot_key
            static_path = self._resolve_game_media_path(media_root, base_names, fallback_key)
            if static_path is not None:
                pixmap = QPixmap(str(static_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if element.text_fallback and element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
            text_value = self._resolve_theme_preview_text(element, collection_name, display_entry, collection_games, collection_index)
            if not text_value:
                # RetroFE text fallback: show the item name when no slot-specific text or image exists.
                # This is the primary display mode for menu collections with no logo images.
                text_value = display_entry.game_name or None
            if text_value:
                return ThemePreviewRenderData(text=text_value)
        if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"}:
            text_value = self._resolve_theme_preview_text(element, collection_name, display_entry, collection_games, collection_index)
            if text_value:
                return ThemePreviewRenderData(text=text_value)
        return None

    def _theme_menu_entry_for_element(
        self,
        element: ThemePreviewElement,
        selected_entry: GameManifestEntry,
        collection_games: tuple[GameManifestEntry, ...],
        collection_index: int,
    ) -> GameManifestEntry:
        if element.kind != "menu" or not collection_games:
            return selected_entry
        menu_position = element.menu_position
        selected_position = element.menu_selected_position
        if menu_position is None or selected_position is None:
            return selected_entry
        selected_zero_index = max(0, collection_index - 1)
        offset = menu_position - selected_position
        target_index = (selected_zero_index + offset) % len(collection_games)
        return collection_games[target_index]

    def _resolve_theme_game_media_root(self, game_entry: GameManifestEntry) -> Path | None:
        collection_key = game_entry.collection_name.casefold()
        if collection_key in self._media_root_cache:
            return self._media_root_cache[collection_key]
        # Dynamic fallback for collections not pre-built in cache (e.g. navigation menu collections
        # like "1 COLLECTIONS" which aren't in the game manifest).
        target = self._target_dir()
        if target is not None:
            for collection_dir in collection_directory_candidates(target, game_entry.collection_name):
                candidate = collection_dir / "medium_artwork"
                if candidate.exists() and candidate.is_dir():
                    self._media_root_cache[collection_key] = candidate
                    return candidate
        self._media_root_cache[collection_key] = None
        return None

    def _build_collection_media_roots(self, target: Path) -> dict[str, Path | None]:
        """Check each collection's medium_artwork directory once and return a collection-keyed map."""
        result: dict[str, Path | None] = {}
        seen = {entry.collection_name.casefold() for entry in self._game_entries}
        for collection_name in seen:
            media_root = None
            for collection_dir in collection_directory_candidates(target, collection_name):
                candidate = collection_dir / "medium_artwork"
                if candidate.exists() and candidate.is_dir():
                    media_root = candidate
                    break
            result[collection_name] = media_root
        return result

    def _common_root_for_mode(self, theme_entry: ThemeCatalogEntry, mode_key: str) -> Path:
        """Return the _common collections path for the given mode.

        mode="commonlayout" → layouts/<theme>/collections/_common (theme-scoped)
        mode="common"       → appdata/retrofe/collections/_common  (global)
        """
        if mode_key == "common":
            target = self._target_dir()
            if target is not None:
                return target / "appdata" / "retrofe" / "collections" / "_common"
        return theme_entry.root_dir / "collections" / "_common"

    def _resolve_common_theme_render(
        self,
        theme_entry: ThemeCatalogEntry,
        slot_key: str,
        game_entry: GameManifestEntry,
        collection_name: str | None,
        common_root: Path | None = None,
    ) -> ThemePreviewRenderData | None:
        if not slot_key:
            return None
        effective_common = common_root if common_root is not None else (theme_entry.root_dir / "collections" / "_common")
        slot_dir = effective_common / "medium_artwork" / slot_key
        if not slot_dir.exists() or not slot_dir.is_dir():
            return None
        candidate_names: tuple[str, ...] = tuple()
        if slot_key in {"firstletter", "rightstrip"}:
            letter = Path(game_entry.game_name).stem[:1] or game_entry.game_name[:1]
            candidate_names = (letter.upper(), letter.lower(), letter)
        elif slot_key == "playlist" and collection_name:
            candidate_names = (collection_name,)
        elif slot_key == "isfavorite":
            candidate_names = ("yes",)
        else:
            candidate_names = _game_name_candidates(Path(game_entry.rom_path).name)
        if candidate_names:
            media_path = _find_matching_media_file(slot_dir, tuple(name for name in candidate_names if name), IMAGE_MEDIA_SUFFIXES)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        default_dir = slot_dir / "default"
        if default_dir.exists() and default_dir.is_dir():
            if candidate_names:
                media_path = _find_matching_media_file(default_dir, tuple(name for name in candidate_names if name), IMAGE_MEDIA_SUFFIXES)
                if media_path is not None:
                    pixmap = QPixmap(str(media_path))
                    if not pixmap.isNull():
                        return ThemePreviewRenderData(pixmap=pixmap)
            for path in _preferred_default_common_media_files(slot_key, default_dir, IMAGE_MEDIA_SUFFIXES):
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if not candidate_names:
            return None
        media_path = _find_matching_media_file(slot_dir, tuple(name for name in candidate_names if name), IMAGE_MEDIA_SUFFIXES)
        if media_path is None:
            return None
        pixmap = QPixmap(str(media_path))
        if pixmap.isNull():
            return None
        return ThemePreviewRenderData(pixmap=pixmap)

    def _resolve_common_layout_video(self, theme_entry: ThemeCatalogEntry, slot_key: str, common_root: Path | None = None) -> Path | None:
        effective_common = common_root if common_root is not None else (theme_entry.root_dir / "collections" / "_common")
        common_artwork = effective_common / "medium_artwork"
        candidate_folders: list[Path] = []
        if slot_key and slot_key != "video":
            candidate_folders.append(common_artwork / slot_key / "default")
        candidate_folders.append(common_artwork / "video" / "default")
        for folder in candidate_folders:
            if not folder.exists() or not folder.is_dir():
                continue
            videos = [f for f in sorted(folder.iterdir()) if f.suffix.casefold() in VIDEO_MEDIA_SUFFIXES]
            if videos:
                return random.choice(videos)
        return None

    def _resolve_game_media_path(self, media_root: Path | None, base_names: tuple[str, ...], slot_key: str) -> Path | None:
        if media_root is None or not slot_key:
            return None
        folder_candidates = {
            "logo": ("logo",),
            "artwork_front": ("artwork_front",),
            "artwork_front_s": ("artwork_front_s", "artwork_front"),
            "screenshot": ("screenshot",),
            "screentitle": ("screentitle",),
            "led_marquee": ("led_marquee",),
            "lcd_marquee": ("lcd_marquee",),
            "bezel": ("bezel",),
            "cabinet": ("cabinet", "artwork_3d", "artwork_front"),
        }.get(slot_key, (slot_key,))
        for folder_name in folder_candidates:
            media_path = _find_matching_media_file(media_root / folder_name, base_names, IMAGE_MEDIA_SUFFIXES)
            if media_path is not None:
                return media_path
        return None

    def _resolve_game_video_path(self, media_root: Path | None, base_names: tuple[str, ...], slot_key: str) -> Path | None:
        if media_root is None:
            return None
        if slot_key in {"screenshot", "video", ""}:
            return _find_matching_media_file(media_root / "video", base_names, VIDEO_MEDIA_SUFFIXES)
        return _find_matching_media_file(media_root / "video", base_names, VIDEO_MEDIA_SUFFIXES)

    def _resolve_theme_preview_text(
        self,
        element: ThemePreviewElement,
        collection_name: str | None,
        game_entry: GameManifestEntry | None,
        collection_games: tuple[GameManifestEntry, ...],
        collection_index: int,
    ) -> str | None:
        slot_key = (element.slot_name or "").casefold()
        if element.value:
            return element.value
        if element.source_path and Path(element.source_path).suffix.casefold() in STORY_MEDIA_SUFFIXES:
            return _read_story_text(Path(element.source_path))
        if slot_key == "collectionsize":
            return str(len(collection_games)) if collection_games else None
        if slot_key == "collectionindex":
            return str(collection_index) if collection_index else None
        if slot_key == "collectionindexsize":
            return f"{collection_index} / {len(collection_games)}" if collection_games and collection_index else None
        if slot_key == "playlist":
            return "ALL"
        if slot_key == "time":
            return datetime.now().strftime("%I:%M %p").lstrip("0")
        if game_entry is None:
            return None
        hyperlist_metadata = self._resolve_theme_game_metadata(collection_name, game_entry)
        if slot_key == "title":
            return (hyperlist_metadata.value_for_slot("title") if hyperlist_metadata is not None else None) or Path(game_entry.game_name).stem
        if slot_key == "story":
            base_names = _game_name_candidates(Path(game_entry.rom_path).name)
            media_root = self._resolve_theme_game_media_root(game_entry)
            story_path = _find_matching_media_file(media_root / "story", base_names, STORY_MEDIA_SUFFIXES) if media_root is not None else None
            if story_path is None:
                return None
            return _read_story_text(story_path)
        if slot_key == "firstletter":
            title_text = (hyperlist_metadata.value_for_slot("title") if hyperlist_metadata is not None else None) or Path(game_entry.game_name).stem
            return title_text[:1].upper() if title_text else None
        if hyperlist_metadata is not None:
            return hyperlist_metadata.value_for_slot(slot_key)
        return None

    def _resolve_theme_game_metadata(
        self,
        collection_name: str | None,
        game_entry: GameManifestEntry,
    ):
        collection_candidates: list[str] = []
        for candidate in (
            collection_name,
            game_entry.collection_name,
            game_entry.install_collection_name,
            game_entry.source_pack,
        ):
            normalized = (candidate or "").strip()
            if normalized and normalized not in collection_candidates:
                collection_candidates.append(normalized)
        return lookup_hyperlist_metadata(self._target_dir(), tuple(collection_candidates), game_entry)

    def _update_theme_summary(self, theme_entry: ThemeCatalogEntry | None, preview: ThemeLayoutPreview | None) -> None:
        if theme_entry is None:
            self.themes_name_label.setText("Theme: None")
            self.themes_canvas_label.setText("Canvas Size: Unknown")
            return
        self.themes_name_label.setText(f"Theme: {theme_entry.name}")
        if preview is None:
            self.themes_canvas_label.setText("Canvas Size: Unknown")
            return
        self.themes_canvas_label.setText(f"Canvas Size: {int(preview.canvas_width)} x {int(preview.canvas_height)}")

    def _format_theme_element_details(self, element: ThemePreviewElement | None) -> str:
        if element is None:
            return "Click a preview element to inspect its details."
        lines = [
            f"Label: {element.label}",
            f"Type: {element.kind}",
            f"Layer: {element.layer if element.layer is not None else 'None'}",
            f"Mode: {element.mode or 'None'}",
            f"Position: x={element.x:.1f}, y={element.y:.1f}",
            f"Size: width={element.width:.1f}, height={element.height:.1f}",
            f"Source: {element.source_path or 'None'}",
        ]
        if element.font_path or element.font_size or element.load_font_size:
            lines.append(f"Font: {element.font_path or 'Default'}")
            lines.append(f"Font Size: {element.font_size if element.font_size is not None else 'None'}")
            lines.append(f"Load Font Size: {element.load_font_size if element.load_font_size is not None else 'None'}")
            lines.append(f"Font Color: {element.font_color or 'Default'}")
            lines.append(f"Text Format: {element.text_format or 'None'}")
            lines.append(f"Origins: x={element.x_origin or 'None'}, y={element.y_origin or 'None'}")
        if element.transform_points:
            points = ", ".join(f"({x:.1f}, {y:.1f})" for x, y in element.transform_points)
            lines.append(f"Transform Points: {points}")
        return "\n".join(lines)

    def _refresh_logs_screen(self) -> None:
        if self._selected_log_key is None:
            self.logs_content_stack.setCurrentWidget(self.logs_empty_label)
            return
        self._show_log_contents(self._selected_log_key)

    def _select_log(self, log_key: str) -> None:
        self._selected_log_key = log_key
        for key, button in self.log_buttons.items():
            button.blockSignals(True)
            button.setChecked(key == log_key)
            button.blockSignals(False)
        self._show_log_contents(log_key)

    def _show_log_contents(self, log_key: str) -> None:
        log_path = self._log_file_paths().get(log_key)
        if log_path is None or not log_path.exists():
            self.logs_content_stack.setCurrentWidget(self.logs_missing_label)
            return
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.logs_content_stack.setCurrentWidget(self.logs_missing_label)
            return
        self.logs_viewer.setPlainText(self._filtered_log_content(content))
        self.logs_content_stack.setCurrentWidget(self.logs_viewer)

    def _log_file_paths(self) -> dict[str, Path]:
        target = self._target_dir()
        paths: dict[str, Path] = {
            "companion": SettingsStore().config_dir / LOG_FILE_NAME,
        }
        if target is None:
            return paths
        paths.update(
            {
                "retrofe": target / "retrofe.log",
                "scripter": target / "scripter.log",
                "sunshine": target / "sunshine.log",
                "retroarch": target / "appdata" / "retroarch" / "logs" / "retroarch.log",
            }
        )
        return paths

    def _update_log_wrap_mode(self) -> None:
        self.logs_viewer.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if self.log_wrap_checkbox.isChecked()
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def _handle_log_wrap_toggled(self, _state: int) -> None:
        self._update_log_wrap_mode()
        self._save_settings()

    def _change_log_colors(self) -> None:
        dialog = LogColorDialog(self._log_highlight_colors, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._log_highlight_colors = dialog.color_map()
        self.logs_highlighter.set_color_map(self._log_highlight_colors)
        self._save_settings()
        self._refresh_logs_screen()

    def _filtered_log_content(self, content: str) -> str:
        enabled_filters = {
            key
            for key, checkbox in self.log_filter_checkboxes.items()
            if checkbox.isChecked()
        }
        return "\n".join(
            line
            for line in content.splitlines()
            if self._log_level_for_line(line) in enabled_filters
        )

    def _log_level_for_line(self, line: str) -> str:
        level_patterns = (
            ("critical", r"\bCRITICAL\b|\bCritical\b|\[critical\]|\[CRITICAL\]"),
            ("fatal", r"\bFATAL\b|\bFatal\b|\[fatal\]|\[FATAL\]"),
            ("error", r"\bERROR\b|\bError\b|\[error\]|\[ERROR\]|\bTraceback\b|\bException\b"),
            ("warning", r"\bWARNING\b|\bWARN\b|\bWarning\b|\bWarn\b|\[warning\]|\[warn\]|\[WARNING\]|\[WARN\]"),
            ("info", r"\bINFO\b|\bInfo\b|\[info\]|\[INFO\]"),
            ("debug", r"\bDEBUG\b|\bDebug\b|\[debug\]|\[DEBUG\]"),
        )
        for level, pattern in level_patterns:
            if re.search(pattern, line):
                return level
        return "other"

    def _sorted_filtered_collections(self) -> list[CollectionCatalogEntry]:
        name_filter = self.collections_name_filter.text().strip().casefold()
        filtered_entries = [
            entry
            for entry in self._collection_entries
            if not name_filter or name_filter in entry.name.casefold()
        ]
        reverse = self._collections_sort_order == Qt.SortOrder.DescendingOrder
        return sorted(filtered_entries, key=self._collections_sort_key, reverse=reverse)

    def _collections_sort_key(self, entry: CollectionCatalogEntry) -> Any:
        if self._collections_sort_column == COLLECTIONS_TABLE_COLUMNS["collection_name"]:
            return (entry.name.casefold(),)
        if self._collections_sort_column == COLLECTIONS_TABLE_COLUMNS["parent_collections"]:
            return (len(entry.parent_collections), tuple(parent.casefold() for parent in entry.parent_collections), entry.name.casefold())
        if self._collections_sort_column == COLLECTIONS_TABLE_COLUMNS["game_count"]:
            return (entry.game_count, entry.name.casefold())
        return (entry.name.casefold(),)

    def _set_collection_name_cell(
        self,
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

    def _set_collection_parent_cell(self, row: int, entry: CollectionCatalogEntry) -> None:
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

    def _set_collection_game_count_cell(self, row: int, entry: CollectionCatalogEntry) -> None:
        button = QPushButton(f"{entry.game_count:,}")
        button.setObjectName("gameLink")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, name=entry.name: self._show_games_for_collection(name))
        self.collections_table.setCellWidget(row, COLLECTIONS_TABLE_COLUMNS["game_count"], button)

    def _open_collection_details_by_name(self, collection_name: str) -> None:
        filtered_entries = self._sorted_filtered_collections()
        for index, entry in enumerate(filtered_entries):
            if entry.name == collection_name:
                self._open_collection_details_dialog(entry, filtered_entries, index)
                return

    def _open_collection_details_dialog(
        self,
        entry: CollectionCatalogEntry,
        navigation_entries: list[CollectionCatalogEntry] | None = None,
        navigation_index: int | None = None,
    ) -> None:
        dialog = CollectionDetailsDialog(entry, self._target_dir(), navigation_entries, navigation_index, self)
        dialog.exec()

    def _show_games_for_collection(self, collection_name: str) -> None:
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

    def _handle_collections_header_clicked(self, section: int) -> None:
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

    def _reset_collections_page_and_refresh(self, *_args) -> None:
        self._collections_current_page = 1
        self._refresh_collections_table()

    def _set_collections_page(self, page: int) -> None:
        self._collections_current_page = max(1, page)
        self._refresh_collections_table()

    def _go_to_last_collections_page(self) -> None:
        total_items = len(self._sorted_filtered_collections())
        total_pages = max(1, (total_items + self._collections_page_size - 1) // self._collections_page_size)
        self._collections_current_page = total_pages
        self._refresh_collections_table()

    def _change_collections_page_size(self, *_args) -> None:
        self._collections_page_size = int(self.collections_page_size_combo.currentData() or 100)
        self._collections_current_page = 1
        self._refresh_collections_table()

    def _update_collections_pagination(self, total_items: int, total_pages: int) -> None:
        self.collections_results_label.setText(f"{total_items:,} collections")
        self.collections_page_label.setText(f"Page {self._collections_current_page} of {total_pages}")
        self.collections_first_button.setEnabled(self._collections_current_page > 1)
        self.collections_previous_button.setEnabled(self._collections_current_page > 1)
        self.collections_next_button.setEnabled(self._collections_current_page < total_pages)
        self.collections_last_button.setEnabled(self._collections_current_page < total_pages)

    def _set_games_name_cell(
        self,
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

    def _open_game_details_dialog(
        self,
        entry: GameManifestEntry,
        installed: bool,
        navigation_entries: list[GameManifestEntry],
        navigation_index: int,
        installed_keys: set[tuple[str, str]],
    ) -> None:
        dialog = GameDetailsDialog(
            entry,
            installed,
            self._target_dir(),
            self._bitlcd_target_dir(),
            navigation_entries,
            navigation_index,
            installed_keys,
            self,
        )
        dialog.exec()

    def _handle_games_header_clicked(self, section: int) -> None:
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
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return {
                OPTIONAL_TABLE_COLUMNS["component"],
                OPTIONAL_TABLE_COLUMNS["type"],
                OPTIONAL_TABLE_COLUMNS["installed"],
                OPTIONAL_TABLE_COLUMNS["available"],
                OPTIONAL_TABLE_COLUMNS["size"],
                OPTIONAL_TABLE_COLUMNS["status"],
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
        size_column = OPTIONAL_TABLE_COLUMNS["size"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["size"]
        status_column = OPTIONAL_TABLE_COLUMNS["status"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["status"]
        if column == component_column:
            return spec.display_name.casefold()
        if screen_index == OPTIONAL_COMPONENTS_SCREEN and column == OPTIONAL_TABLE_COLUMNS["type"]:
            return self._component_type_display(spec).casefold()
        if column == installed_column:
            return self._version_sort_key(None)
        if column == available_column:
            return self._version_sort_key(spec.available_version)
        if column == size_column:
            return self._size_sort_key(self._component_size_bytes(spec), self._component_size_display(spec))
        if column == status_column:
            return self._status_sort_key("Pending", 0)
        return spec.display_name.casefold()

    def _component_status_sort_key(self, screen_index: int, column: int, status: Any) -> Any:
        component_column = OPTIONAL_TABLE_COLUMNS["component"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["component"]
        installed_column = OPTIONAL_TABLE_COLUMNS["installed"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["installed"]
        available_column = OPTIONAL_TABLE_COLUMNS["available"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["available"]
        size_column = OPTIONAL_TABLE_COLUMNS["size"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["size"]
        status_column = OPTIONAL_TABLE_COLUMNS["status"] if screen_index == OPTIONAL_COMPONENTS_SCREEN else BASE_TABLE_COLUMNS["status"]
        if column == component_column:
            return status.spec.display_name.casefold()
        if screen_index == OPTIONAL_COMPONENTS_SCREEN and column == OPTIONAL_TABLE_COLUMNS["type"]:
            return self._component_type_display(status.spec).casefold()
        if column == installed_column:
            return self._version_sort_key(status.installed_version)
        if column == available_column:
            return self._version_sort_key(status.available_version)
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
        components = self._components_for_screen(screen_index)
        disabled = self._disabled_component_keys.get(screen_index, set())
        selectable_keys = [spec.key for spec in components if spec.key not in disabled]
        selected = self._selected_component_keys.get(screen_index, set())
        checked = bool(selectable_keys) and all(key in selected for key in selectable_keys)
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
            widget.set_status(self._display_component_status(entry.spec.key, entry.status), entry.percent)
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
        can_reorder = self._controller is None or self._controller.is_paused

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        up_button = QToolButton()
        up_button.setProperty("queueAction", True)
        up_button.setIcon(up_icon)
        up_button.setIconSize(QSize(14, 14))
        up_button.setEnabled(can_reorder and row > 0)
        up_button.clicked.connect(lambda _=False, key=entry.spec.key: self._move_queue_entry(key, -1))

        down_button = QToolButton()
        down_button.setProperty("queueAction", True)
        down_button.setIcon(down_icon)
        down_button.setIconSize(QSize(14, 14))
        down_button.setEnabled(can_reorder and row < len(self._queue_entries) - 1)
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
        if self._controller is not None and not self._controller.is_paused:
            self._push_status_message("Pause the queue before reordering items.")
            return
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
            widget.set_status(self._display_component_status(component_key, status), percent)
        for entry in self._queue_entries:
            if entry.spec.key == component_key:
                entry.status = status
                entry.percent = percent
                break

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
        if self._controller is not None and self._controller.is_paused and component_key in self._active_components:
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
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_install_button
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return self.optional_components_install_button
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_install_button
        return self.install_button

    def _refresh_button_for_screen(self, screen_index: int) -> QPushButton:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return self.bitlcd_refresh_button
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return self.optional_components_refresh_button
        if screen_index == GAME_PACKS_SCREEN:
            return self.game_packs_refresh_button
        return self.refresh_button

    def _log_output_for_screen(self, screen_index: int) -> QPlainTextEdit:
        return self.queue_log_output

    def _screen_label(self, screen_index: int) -> str:
        if screen_index == BITLCD_MARQUEES_SCREEN:
            return "BitLCD marquees"
        if screen_index == OPTIONAL_COMPONENTS_SCREEN:
            return "Optional components"
        if screen_index == GAME_PACKS_SCREEN:
            return "System packs"
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
        disabled_keys = self._disabled_component_keys.get(screen_index, set())
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
            queued_keys.add(status.spec.key)
            added += 1
        if added:
            self._sort_states[QUEUE_SCREEN] = (-1, Qt.SortOrder.AscendingOrder)
            self._refresh_queue_table()
            self._save_settings()
            self._push_status_message(f"Queued {added} {source_label.lower()} item(s).")
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
        if not queue_specs:
            self._refresh_queue_table()
            self._save_settings()
            return

        self._save_settings()
        installer = Installer(queue_specs, max_parallel_downloads=self.parallel_downloads_spin.value())
        installer.cache_dir = self._downloads_dir()
        log_output = self._log_output_for_screen(QUEUE_SCREEN)
        self._controller = OperationController()
        self._active_operation_screen = QUEUE_SCREEN
        self._active_components.clear()
        self._set_action_buttons_enabled(False)
        self._set_queue_controls_enabled(False)
        self.queue_pause_button.setText("Pause")
        self._push_status_message("Preparing install...")
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
            self.queue_pause_button.setText("Pause")
            self._push_status_message("Resuming transfer...")
        else:
            self._controller.pause()
            self.queue_pause_button.setText("Resume")
            self._push_status_message("Paused")
        self._refresh_active_status_widgets()
        self._refresh_queue_table()

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
        operation_label = self._screen_label(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        log_output = self._log_output_for_screen(self._active_operation_screen or BASE_COMPONENTS_SCREEN)
        installed_keys: list[str] = list(getattr(report, "installed_components", []))
        if _install_requires_cache_rebuild(installed_keys):
            self._media_root_cache.clear()
            target = self._target_dir()
            if target is not None:
                self._media_root_cache.update(self._build_collection_media_roots(target))
        continue_queue = (
            self._active_operation_screen == QUEUE_SCREEN
            and any(entry.status != "Installed" for entry in self._queue_entries)
        )
        self._finish_install_ui()
        self._push_status_message("Install complete")
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
        self.queue_pause_button.setText("Pause")
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

    def _clear_worker_refs(self) -> None:
        self._worker = None
        self._worker_thread = None
        self._finalize_close_if_ready()

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

    def _clear_validate_refs(self) -> None:
        self._validate_worker = None
        self._validate_thread = None
        self._finalize_close_if_ready()

    def _start_release_check(self) -> None:
        if self._release_check_thread is not None and self._release_check_thread.isRunning():
            return

        self._release_check_thread = QThread(self)
        self._release_check_worker = ReleaseCheckWorker(APP_VERSION)
        self._release_check_worker.moveToThread(self._release_check_thread)

        self._release_check_thread.started.connect(self._release_check_worker.run)
        self._release_check_worker.finished.connect(self._release_check_finished)
        self._release_check_worker.error.connect(self._release_check_failed)
        self._release_check_worker.finished.connect(self._release_check_thread.quit)
        self._release_check_worker.error.connect(self._release_check_thread.quit)
        self._release_check_thread.finished.connect(self._release_check_thread.deleteLater)
        self._release_check_thread.finished.connect(self._clear_release_check_refs)
        self._release_check_thread.start()

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

    def _clear_release_check_refs(self) -> None:
        self._release_check_worker = None
        self._release_check_thread = None
        self._finalize_close_if_ready()

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
        state = self._autostart_state()
        target_dir = self._target_dir()
        settings_tweaks_state = detect_settings_tweaks_state(target_dir, _conf_dir() / "settings_HA8819.conf")
        onesauce_settings_state = detect_onesauce_settings_state(target_dir)
        available = state.onesauce_installed
        self.tweaks_autostart_warning.setVisible(not available)
        self.tweaks_autostart_status_row.setVisible(available)
        self.tweaks_autostart_action_row.setVisible(available)
        self.tweaks_autostart_fix_intro.setVisible(available)
        self.tweaks_autostart_fix_button.setVisible(available)
        if not available:
            self.tweaks_autostart_fix_disabled_note.hide()
            self.tweaks_autostart_fix_installed_note.hide()
            self.tweaks_autostart_fix_pending_note.hide()
            return

        self.tweaks_autostart_status_value.setText(state.status)
        if state.status == AUTOSTART_STATUS_NOT_ENABLED:
            self.tweaks_autostart_primary_button.setText("Enable Autostart")
            self.tweaks_autostart_primary_button.setEnabled(True)
        elif state.status == AUTOSTART_STATUS_ENABLED:
            self.tweaks_autostart_primary_button.setText("Disable Autostart")
            self.tweaks_autostart_primary_button.setEnabled(True)
        else:
            self.tweaks_autostart_primary_button.setText("Pending...")
            self.tweaks_autostart_primary_button.setEnabled(False)

        fix_button_enabled = state.status == AUTOSTART_STATUS_ENABLED and not state.fix_installed
        self.tweaks_autostart_fix_button.setEnabled(fix_button_enabled)
        self.tweaks_autostart_fix_disabled_note.setVisible(state.status == AUTOSTART_STATUS_NOT_ENABLED)
        self.tweaks_autostart_fix_installed_note.setVisible(state.fix_installed)
        self.tweaks_autostart_fix_pending_note.setVisible(state.status == AUTOSTART_STATUS_PENDING)
        self.tweaks_legends_micro_fix_checkbox.blockSignals(True)
        self.tweaks_legends_micro_fix_checkbox.setChecked(settings_tweaks_state.legends_pinball_micro_rotation_fix_enabled)
        self.tweaks_legends_micro_fix_checkbox.setEnabled(
            target_dir is not None and not settings_tweaks_state.legends_pinball_micro_rotation_fix_enabled
        )
        self.tweaks_legends_micro_fix_checkbox.blockSignals(False)

        self._loading_tweaks_settings = True
        try:
            settings_available = onesauce_settings_state.available
            self.tweaks_onesauce_settings_warning.setVisible(not settings_available)
            self.tweaks_default_theme_label.setVisible(settings_available)
            self.tweaks_default_theme_combo.setVisible(settings_available)
            self.tweaks_remember_menu_row.setVisible(settings_available)
            self.tweaks_write_launcher_log_row.setVisible(settings_available)
            self.tweaks_video_enable_row.setVisible(settings_available)
            self.tweaks_auto_scan_collections_row.setVisible(settings_available)
            self.tweaks_video_loop_label.setVisible(settings_available)
            self.tweaks_video_loop_edit.setVisible(settings_available)
            self.tweaks_attract_mode_time_label.setVisible(settings_available)
            self.tweaks_attract_mode_time_edit.setVisible(settings_available)
            self.tweaks_attract_mode_next_time_label.setVisible(settings_available)
            self.tweaks_attract_mode_next_time_edit.setVisible(settings_available)
            self.tweaks_default_video_value_label.setVisible(settings_available)
            self.tweaks_default_video_value_row.setVisible(settings_available)
            self.tweaks_default_theme_combo.clear()
            if settings_available:
                for theme in onesauce_settings_state.themes:
                    self.tweaks_default_theme_combo.addItem(theme)
                current_theme = onesauce_settings_state.values.get("layout", "")
                if current_theme and self.tweaks_default_theme_combo.findText(current_theme) == -1:
                    self.tweaks_default_theme_combo.addItem(current_theme)
                if current_theme:
                    self.tweaks_default_theme_combo.setCurrentIndex(
                        max(0, self.tweaks_default_theme_combo.findText(current_theme))
                    )

                self.tweaks_remember_menu_checkbox.setChecked(
                    onesauce_settings_state.values.get("rememberMenu", "").strip().casefold() == "yes"
                )
                self.tweaks_write_launcher_log_checkbox.setChecked(
                    onesauce_settings_state.values.get("writeLauncherLog", "").strip().casefold() == "yes"
                )
                self.tweaks_video_enable_checkbox.setChecked(
                    onesauce_settings_state.values.get("videoEnable", "").strip().casefold() == "yes"
                )
                self.tweaks_auto_scan_collections_checkbox.setChecked(
                    onesauce_settings_state.values.get("autoScanCollections", "").strip().casefold() == "true"
                )
                current_video_loop = onesauce_settings_state.values.get("videoLoop", "0").strip() or "0"
                self._last_video_loop_value = current_video_loop
                self.tweaks_video_loop_edit.setText(current_video_loop)
                current_attract_mode_time = onesauce_settings_state.values.get("attractModeTime", "0").strip() or "0"
                self._last_attract_mode_time_value = current_attract_mode_time
                self.tweaks_attract_mode_time_edit.setText(current_attract_mode_time)
                current_attract_mode_next_time = onesauce_settings_state.values.get("attractModeNextTime", "0").strip() or "0"
                self._last_attract_mode_next_time_value = current_attract_mode_next_time
                self.tweaks_attract_mode_next_time_edit.setText(current_attract_mode_next_time)
                slider_value = _default_video_value_to_percent(onesauce_settings_state.values.get("defaultVolume", "0"))
                self.tweaks_default_video_value_slider.setValue(slider_value)
                self.tweaks_default_video_value_percent_label.setText(f"{slider_value}%")
            else:
                self.tweaks_remember_menu_checkbox.setChecked(False)
                self.tweaks_write_launcher_log_checkbox.setChecked(False)
                self.tweaks_video_enable_checkbox.setChecked(False)
                self.tweaks_auto_scan_collections_checkbox.setChecked(False)
                self._last_video_loop_value = "0"
                self._last_attract_mode_time_value = "0"
                self._last_attract_mode_next_time_value = "0"
                self.tweaks_video_loop_edit.clear()
                self.tweaks_attract_mode_time_edit.clear()
                self.tweaks_attract_mode_next_time_edit.clear()
                self.tweaks_default_video_value_slider.setValue(0)
                self.tweaks_default_video_value_percent_label.setText("0%")
        finally:
            self._loading_tweaks_settings = False

    def _handle_autostart_primary_action(self) -> None:
        state = self._autostart_state()
        target_dir = self._target_dir()
        if target_dir is None or not state.onesauce_installed:
            self._refresh_tweaks_screen()
            return

        if state.status == AUTOSTART_STATUS_NOT_ENABLED:
            script_source = _scripts_dir() / "00_install_autostart.sh"
            if not script_source.exists():
                QMessageBox.critical(self, "Autostart unavailable", f"Missing script: {script_source}")
                return
            self.tweaks_autostart_primary_button.setText("Pending...")
            self.tweaks_autostart_primary_button.setEnabled(False)
            QApplication.processEvents()
            enable_autostart(target_dir, script_source)
            self._push_status_message("Autostart will be enabled on next OnesaUCE start")
            self._refresh_tweaks_screen()
            return

        if state.status == AUTOSTART_STATUS_ENABLED:
            confirm = QMessageBox.question(
                self,
                "Disable Autostart",
                "Disable Autostart and remove the current autostart folder? A backup will be created first.",
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            backup_dir = disable_autostart(target_dir)
            if backup_dir is not None:
                self._push_status_message(f"Autostart disabled. Backup stored in {backup_dir}")
            else:
                self._push_status_message("Autostart disabled")
            self._refresh_tweaks_screen()

    def _handle_install_autostart_fix(self) -> None:
        state = self._autostart_state()
        target_dir = self._target_dir()
        if target_dir is None or state.status != AUTOSTART_STATUS_ENABLED or state.fix_installed:
            self._refresh_tweaks_screen()
            return

        script_source = _scripts_dir() / "00_init_menu.sh"
        if not script_source.exists():
            QMessageBox.critical(self, "Fix unavailable", f"Missing script: {script_source}")
            return
        install_autostart_fix(target_dir, script_source)
        self._push_status_message("Autostart fix installed")
        self._refresh_tweaks_screen()

    def _handle_legends_micro_fix_toggled(self, state: int) -> None:
        if not _is_checked_state(state):
            self.tweaks_legends_micro_fix_checkbox.blockSignals(True)
            self.tweaks_legends_micro_fix_checkbox.setChecked(
                detect_settings_tweaks_state(self._target_dir(), _conf_dir() / "settings_HA8819.conf").legends_pinball_micro_rotation_fix_enabled
            )
            self.tweaks_legends_micro_fix_checkbox.blockSignals(False)
            return

        target_dir = self._target_dir()
        if target_dir is None:
            self._refresh_tweaks_screen()
            return

        source_config_path = _conf_dir() / "settings_HA8819.conf"
        if not source_config_path.exists():
            QMessageBox.critical(self, "Settings tweak unavailable", f"Missing config: {source_config_path}")
            self._refresh_tweaks_screen()
            return

        enable_legends_pinball_micro_rotation_fix(target_dir, source_config_path)
        self._push_status_message("Legends Pinball Micro rotation fix enabled")
        self._refresh_tweaks_screen()

    def _handle_default_theme_changed(self, index: int) -> None:
        if self._loading_tweaks_settings or index < 0:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        value = self.tweaks_default_theme_combo.currentText().strip()
        if not value:
            return
        update_onesauce_setting(target_dir, "layout", value)
        self._push_status_message("Default theme updated")

    def _handle_remember_menu_toggled(self, state: int) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        update_onesauce_setting(target_dir, "rememberMenu", "yes" if _is_checked_state(state) else "no")
        self._push_status_message("Remember menu setting updated")

    def _handle_write_launcher_log_toggled(self, state: int) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        update_onesauce_setting(target_dir, "writeLauncherLog", "yes" if _is_checked_state(state) else "no")
        self._push_status_message("Launcher log setting updated")

    def _handle_video_enable_toggled(self, state: int) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        update_onesauce_setting(target_dir, "videoEnable", "yes" if _is_checked_state(state) else "no")
        self._push_status_message("Video playback setting updated")

    def _handle_video_loop_changed(self) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        value = self.tweaks_video_loop_edit.text().strip()
        if not value:
            self.tweaks_video_loop_edit.setText(self._last_video_loop_value)
            return
        update_onesauce_setting(target_dir, "videoLoop", value)
        self._last_video_loop_value = value
        self._push_status_message("Video loop setting updated")

    def _handle_auto_scan_collections_toggled(self, state: int) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        update_onesauce_setting(target_dir, "autoScanCollections", "true" if _is_checked_state(state) else "false")
        self._push_status_message("Auto scan collections setting updated")

    def _handle_attract_mode_time_changed(self) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        value = self.tweaks_attract_mode_time_edit.text().strip()
        if not value:
            self.tweaks_attract_mode_time_edit.setText(self._last_attract_mode_time_value)
            return
        update_onesauce_setting(target_dir, "attractModeTime", value)
        self._last_attract_mode_time_value = value
        self._push_status_message("Attract mode delay updated")

    def _handle_attract_mode_next_time_changed(self) -> None:
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        value = self.tweaks_attract_mode_next_time_edit.text().strip()
        if not value:
            self.tweaks_attract_mode_next_time_edit.setText(self._last_attract_mode_next_time_value)
            return
        update_onesauce_setting(target_dir, "attractModeNextTime", value)
        self._last_attract_mode_next_time_value = value
        self._push_status_message("Attract mode item interval updated")

    def _handle_default_video_value_changed(self, value: int) -> None:
        self.tweaks_default_video_value_percent_label.setText(f"{value}%")
        if self._loading_tweaks_settings:
            return
        target_dir = self._target_dir()
        if target_dir is None:
            return
        update_onesauce_setting(target_dir, "defaultVolume", _percent_to_default_video_value(value))
        self._push_status_message("Default video volume updated")

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

    def _component_type_display(self, spec: ComponentSpec) -> str:
        return spec.component_type or ""

    def _update_component_summary_labels(self) -> None:
        messages = {
            self.base_summary_label: (self.base_summary_warning_icon, "Review required components and install or update them."),
            self.game_packs_summary_label: (self.game_packs_summary_warning_icon, "Browse and update the optional system packs archive."),
            self.bitlcd_summary_label: (self.bitlcd_summary_warning_icon, "Browse and update BitLCD marquee packs to the BitLCD target folder."),
            self.optional_components_summary_label: (self.optional_components_summary_warning_icon, "Browse and update optional components that install into the OnesaUCE drive."),
        }
        credentials_missing = self._archive_credentials() is None
        warning_message = "Add Archive.org credentials in settings to enable downloads"
        for label, (icon_label, default_message) in messages.items():
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
        button = self._install_button_for_screen(screen_index)
        all_installed = bool(statuses) and all(status.status == "Installed" for status in statuses)
        button.setText("Up-to-Date" if all_installed else "Download Selected")
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
            self._push_status_message(f"Loaded {len(self._queue_entries)} queued item(s).")

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
        if entry.source_label in {"Optional Component"}:
            return self.optional_components_installer
        if entry.source_label in {"System Pack", "Game Pack"}:
            return self.game_packs_installer
        return self.base_installer

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._scan_timer.stop()
        self._startup_refresh_timer.stop()
        self._stop_theme_preview_animation()
        self._dispose_all_theme_preview_video_sessions()
        self._save_settings()

        if self._controller is not None:
            self._controller.cancel()

        install_running = self._worker_thread is not None and self._worker_thread.isRunning()
        validation_running = self._validate_thread is not None and self._validate_thread.isRunning()
        release_check_running = self._release_check_thread is not None and self._release_check_thread.isRunning()
        if install_running or validation_running or release_check_running:
            self._close_after_workers = True
            self._push_status_message("Stopping background work...")
            event.ignore()
            return

        event.accept()

    def _finalize_close_if_ready(self) -> None:
        if not self._close_after_workers:
            return
        install_running = self._worker_thread is not None and self._worker_thread.isRunning()
        validation_running = self._validate_thread is not None and self._validate_thread.isRunning()
        release_check_running = self._release_check_thread is not None and self._release_check_thread.isRunning()
        if install_running or validation_running or release_check_running:
            return
        self._close_after_workers = False
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
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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
        paused_suffix = " (Paused)"
        paused = text.endswith(paused_suffix)
        base_text = text[:-len(paused_suffix)] if paused else text
        active = base_text in {"Downloading", "Preparing", "Backing Up", "Installing"}

        self.label.setText(text)
        self.label.setVisible(not active)

        self.progress.setVisible(active)
        self.progress.setValue(int(round(clamped_percent)))
        self.progress.setFormat(f"{base_text} {clamped_percent:.1f}%{' (Paused)' if paused else ''}")

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


def _find_matching_media_file(directory: Path, base_names: tuple[str, ...], allowed_suffixes: set[str] | None = None) -> Path | None:
    if not directory.exists() or not directory.is_dir():
        return None
    candidate_keys = {name.casefold() for name in base_names}
    # Game-specific subfolders take priority: check them before the main directory.
    # This lets `artwork_front/1941/1941.jpg` win over `artwork_front/1941.jpg`.
    nested_dirs: list[Path] = []
    for name in base_names:
        nested_dir = directory / Path(name).stem
        if nested_dir.exists() and nested_dir.is_dir() and nested_dir not in nested_dirs:
            nested_dirs.append(nested_dir)
    search_dirs: list[Path] = nested_dirs + [directory]
    for search_dir in search_dirs:
        # Single O(n) pass: return immediately on an exact stem match; keep the first
        # partial match as a fallback. Avoids sorting the full directory (which in a
        # large collection like MAME can be 1 000+ entries per element per frame).
        fallback: Path | None = None
        for path in search_dir.iterdir():
            if not path.is_file():
                continue
            if allowed_suffixes is not None and path.suffix.casefold() not in allowed_suffixes:
                continue
            if not _media_path_matches(path, candidate_keys):
                continue
            if path.stem.casefold() in candidate_keys:
                return path  # exact stem match — highest priority
            if fallback is None:
                fallback = path  # first partial/variant match
        if fallback is not None:
            return fallback
    # No game-specific match found — check for default.jpg / default.png in the main directory.
    if allowed_suffixes is not None:
        for default_name in ("default.jpg", "default.jpeg", "default.png"):
            if Path(default_name).suffix.casefold() not in allowed_suffixes:
                continue
            default_path = directory / default_name
            if default_path.is_file():
                return default_path
    return None


def _resolve_collection_media_root(target_dir: Path | None, collection_name: str) -> Path | None:
    for collection_dir in collection_directory_candidates(target_dir, collection_name):
        media_root = collection_dir / "system_artwork"
        if media_root.exists() and media_root.is_dir():
            return media_root
    return None


def _find_named_collection_media_file(
    media_root: Path | None,
    stem_name: str,
    allowed_suffixes: set[str],
) -> Path | None:
    if media_root is None or not media_root.exists() or not media_root.is_dir():
        return None
    stem_key = stem_name.casefold()
    for path in sorted(media_root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        if path.suffix.casefold() not in allowed_suffixes:
            continue
        if path.stem.casefold() == stem_key:
            return path
    return None


def _find_first_collection_video(media_root: Path | None) -> Path | None:
    if media_root is None or not media_root.exists() or not media_root.is_dir():
        return None
    video_dir = media_root / "video"
    if not video_dir.exists() or not video_dir.is_dir():
        return None
    for path in sorted(video_dir.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_file() and path.suffix.casefold() in VIDEO_MEDIA_SUFFIXES:
            return path
    return None


def _preferred_default_common_media_files(slot_key: str, directory: Path, allowed_suffixes: set[str]) -> list[Path]:
    files = [
        path
        for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file() and path.suffix.casefold() in allowed_suffixes
    ]
    if slot_key != "cabinet" or len(files) <= 1:
        return files
    marquee_ready = [path for path in files if "marquee" in path.stem.casefold()]
    if marquee_ready:
        # Prefer the most specific marquee-ready cabinet shell over the generic bare cabinet.
        return sorted(marquee_ready, key=lambda item: item.name.casefold(), reverse=True) + files
    return files


def _find_collection_videos(media_root: Path | None) -> tuple[Path, ...]:
    if media_root is None or not media_root.exists() or not media_root.is_dir():
        return tuple()
    video_dir = media_root / "video"
    if not video_dir.exists() or not video_dir.is_dir():
        return tuple()
    return tuple(
        path
        for path in sorted(video_dir.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file() and path.suffix.casefold() in VIDEO_MEDIA_SUFFIXES
    )


def _media_path_matches(path: Path, candidate_keys: set[str]) -> bool:
    current = path.name.casefold()
    current_stem = path.stem.casefold()
    if current in candidate_keys or current_stem in candidate_keys:
        return True
    for candidate in candidate_keys:
        if current_stem.startswith(candidate + " (") or current_stem.startswith(candidate + "["):
            return True
    nested_stem = current_stem
    while True:
        reduced = Path(nested_stem).stem.casefold()
        if reduced == nested_stem:
            break
        if reduced in candidate_keys:
            return True
        for candidate in candidate_keys:
            if reduced.startswith(candidate + " (") or reduced.startswith(candidate + "["):
                return True
        nested_stem = reduced
    return False


def _find_matching_lcd_marquee_file(
    media_root: Path,
    bitlcd_target_dir: Path | None,
    entry: GameManifestEntry,
    base_names: tuple[str, ...],
) -> Path | None:
    match = _find_matching_media_file(media_root / "lcd_marquee", base_names, IMAGE_MEDIA_SUFFIXES)
    if match is not None:
        return match
    return _find_matching_bitlcd_media_file(bitlcd_target_dir, entry, base_names)


def _find_matching_bitlcd_media_file(
    bitlcd_target_dir: Path | None,
    entry: GameManifestEntry,
    base_names: tuple[str, ...],
) -> Path | None:
    if bitlcd_target_dir is None or not bitlcd_target_dir.exists() or not bitlcd_target_dir.is_dir():
        return None
    candidate_dirs = _candidate_bitlcd_roots(bitlcd_target_dir, entry)
    candidate_keys = {name.casefold() for name in base_names}
    for root_dir in candidate_dirs:
        index = _bitlcd_media_index_for_root(root_dir)
        for candidate in candidate_keys:
            match = index.get(candidate)
            if match is not None:
                return match
    return None


def _bitlcd_media_index_for_root(root_dir: Path) -> dict[str, Path]:
    cache_key = str(root_dir)
    cached = _BITLCD_MEDIA_INDEX.get(cache_key)
    if cached is not None:
        return cached
    index: dict[str, Path] = {}
    for path in sorted(root_dir.rglob("*"), key=lambda item: str(item).casefold()):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_MEDIA_SUFFIXES:
            continue
        for token in _media_match_tokens(path):
            index.setdefault(token, path)
    _BITLCD_MEDIA_INDEX[cache_key] = index
    return index


def _invalidate_bitlcd_media_index() -> None:
    _BITLCD_MEDIA_INDEX.clear()


def _media_match_tokens(path: Path) -> set[str]:
    tokens: set[str] = set()
    current = path.name.casefold()
    current_stem = path.stem.casefold()
    tokens.add(current)
    nested_stem = current_stem
    while True:
        tokens.add(nested_stem)
        for delimiter in (" (", "["):
            if delimiter in nested_stem:
                tokens.add(nested_stem.split(delimiter, 1)[0])
        reduced = Path(nested_stem).stem.casefold()
        if reduced == nested_stem:
            break
        nested_stem = reduced
    return tokens


def _candidate_bitlcd_roots(bitlcd_target_dir: Path | None, entry: GameManifestEntry) -> list[Path]:
    if bitlcd_target_dir is None:
        return []
    name_candidates = [entry.collection_name, entry.install_collection_name or "", entry.source_pack or ""]
    normalized_tokens = {_normalize_lookup_name(name) for name in name_candidates if name}
    direct_matches: list[Path] = []
    for child in sorted(bitlcd_target_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not child.is_dir():
            continue
        normalized_child = _normalize_lookup_name(child.name)
        if any(token and token in normalized_child for token in normalized_tokens):
            direct_matches.append(child)
    return direct_matches


def _normalize_lookup_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _media_key_for_title(title: str) -> str:
    return {
        "Front Artwork": "front_art",
        "Bezel": "bezel",
        "Logo": "logo",
        "LED Marquee": "led_marquee",
        "LCD Marquee": "lcd_marquee",
        "Screenshot": "screenshot",
        "Screen Title": "screentitle",
    }[title]


def _resolve_lcd_marquee_target_dir(
    media_root: Path | None,
    bitlcd_target_dir: Path | None,
    entry: GameManifestEntry,
    current_path: Path | None,
) -> Path | None:
    if current_path is not None:
        return current_path.parent
    if media_root is not None:
        return media_root / "lcd_marquee"
    candidate_dirs = _candidate_bitlcd_roots(bitlcd_target_dir, entry)
    return candidate_dirs[0] if candidate_dirs else bitlcd_target_dir


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

    return best_root


def _candidate_game_media_roots(target_dir: Path, entry: GameManifestEntry) -> list[Path]:
    candidate_roots: list[Path] = []
    collections_root = _game_media_search_root(target_dir)
    for collection_name in (entry.collection_name, entry.install_collection_name or entry.collection_name):
        direct_root = collections_root / collection_name / "medium_artwork"
        if direct_root.exists() and direct_root not in candidate_roots:
            candidate_roots.append(direct_root)

    installed_collection = _find_installed_collection_root(target_dir, entry)
    if installed_collection is not None and installed_collection not in candidate_roots:
        candidate_roots.insert(0, installed_collection)

    return candidate_roots


def _game_media_search_root(target_dir: Path) -> Path:
    return target_dir / "content" / "retrofe" / "collections"


def _find_installed_collection_root(target_dir: Path, entry: GameManifestEntry) -> Path | None:
    collections_root = _game_media_search_root(target_dir)
    if not collections_root.exists():
        return None
    for collection_dir in collections_root.iterdir():
        if not collection_dir.is_dir():
            continue
        if (collection_dir / "roms" / entry.rom_path).exists():
            media_root = collection_dir / "medium_artwork"
            if media_root.exists():
                return media_root
    return None


def _score_game_media_root(media_root: Path, base_names: tuple[str, ...]) -> int:
    if not media_root.exists() or not media_root.is_dir():
        return -1
    score = 0
    folder_suffixes = {
        "artwork_front": IMAGE_MEDIA_SUFFIXES,
        "bezel": IMAGE_MEDIA_SUFFIXES,
        "logo": IMAGE_MEDIA_SUFFIXES,
        "story": STORY_MEDIA_SUFFIXES,
        "led_marquee": IMAGE_MEDIA_SUFFIXES,
        "lcd_marquee": IMAGE_MEDIA_SUFFIXES,
        "screenshot": IMAGE_MEDIA_SUFFIXES,
        "screentitle": IMAGE_MEDIA_SUFFIXES,
        "video": VIDEO_MEDIA_SUFFIXES,
    }
    for folder_name, suffixes in folder_suffixes.items():
        if _find_matching_media_file(media_root / folder_name, base_names, suffixes) is not None:
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


_CACHE_AFFECTING_COMPONENT_KEYS: frozenset[str] = frozenset({
    "appdata",
    "base_assets",
    "content",
    "optional_simple_blue",
})


def _install_requires_cache_rebuild(installed_keys: list[str]) -> bool:
    return any(
        key in _CACHE_AFFECTING_COMPONENT_KEYS or key.startswith("gamepack_")
        for key in installed_keys
    )


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


def _scripts_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "scripts"
    return Path(__file__).resolve().parents[3] / "scripts"


def _conf_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "conf"
    return Path(__file__).resolve().parents[3] / "conf"


def _default_video_value_to_percent(value: str) -> int:
    try:
        numeric = float(value.strip())
    except (AttributeError, ValueError):
        return 0
    numeric = max(0.0, min(1.0, numeric))
    return int(round(numeric * 100))


def _percent_to_default_video_value(value: int) -> str:
    numeric = max(0, min(100, value)) / 100.0
    text = f"{numeric:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _is_checked_state(state: int | Qt.CheckState) -> bool:
    return getattr(state, "value", state) == getattr(Qt.CheckState.Checked, "value", Qt.CheckState.Checked)


def _extract_video_thumbnail(video_path: Path) -> QPixmap | None:
    try:
        stat = video_path.stat()
    except OSError:
        return None
    cache_key = (str(video_path.resolve()), stat.st_mtime_ns)
    cached = _VIDEO_THUMBNAIL_CACHE.get(cache_key)
    if cached is not None:
        return QPixmap(cached)

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        return None

    for offset in _video_thumbnail_offsets(video_path):
        pixmap = _run_ffmpeg_thumbnail_extract(ffmpeg_path, video_path, offset)
        if pixmap is None or pixmap.isNull():
            continue
        _VIDEO_THUMBNAIL_CACHE[cache_key] = QPixmap(pixmap)
        return pixmap
    return None


def _video_thumbnail_offsets(video_path: Path) -> tuple[float, ...]:
    ffprobe_path = shutil.which("ffprobe")
    offsets: list[float] = []
    if ffprobe_path is not None:
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                duration = float((result.stdout or "").strip())
                if duration > 0:
                    offsets.append(min(max(duration * 0.15, 1.0), max(duration - 0.25, 0.0)))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    offsets.extend((5.0, 1.0, 0.0))
    unique_offsets: list[float] = []
    for offset in offsets:
        rounded = round(max(0.0, offset), 3)
        if rounded not in unique_offsets:
            unique_offsets.append(rounded)
    return tuple(unique_offsets)


def _run_ffmpeg_thumbnail_extract(ffmpeg_path: str, video_path: Path, offset: float) -> QPixmap | None:
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{offset:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    pixmap = QPixmap()
    if not pixmap.loadFromData(result.stdout):
        return None
    return pixmap


def _cherry_icon_pixmap(size: int = 14) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    red_fill = QColor("#d62f2f")
    red_shadow = QColor("#a81f1f")
    stem = QColor("#7fb03c")
    highlight = QColor("#f7b0b0")

    cherry_diameter = max(4, int(size * 0.42))
    cherry_y = size - cherry_diameter - 1
    left_x = max(0, int(size * 0.12))
    right_x = size - cherry_diameter - max(0, int(size * 0.12))

    pen = QPen(red_shadow)
    pen.setWidth(1)
    painter.setPen(pen)
    painter.setBrush(red_fill)
    painter.drawEllipse(left_x, cherry_y, cherry_diameter, cherry_diameter)
    painter.drawEllipse(right_x, cherry_y, cherry_diameter, cherry_diameter)

    stem_pen = QPen(stem)
    stem_pen.setWidth(max(1, int(size * 0.09)))
    painter.setPen(stem_pen)
    left_center_x = left_x + cherry_diameter / 2
    right_center_x = right_x + cherry_diameter / 2
    cherry_top_y = cherry_y + 1
    joint_x = size * 0.54
    joint_y = size * 0.18
    painter.drawLine(int(left_center_x), int(cherry_top_y), int(joint_x), int(joint_y))
    painter.drawLine(int(right_center_x), int(cherry_top_y), int(joint_x), int(joint_y))
    painter.drawLine(int(joint_x), int(joint_y), int(size * 0.74), int(size * 0.04))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(highlight)
    highlight_size = max(2, int(cherry_diameter * 0.22))
    painter.drawEllipse(left_x + max(1, int(cherry_diameter * 0.18)), cherry_y + max(1, int(cherry_diameter * 0.18)), highlight_size, highlight_size)
    painter.drawEllipse(right_x + max(1, int(cherry_diameter * 0.18)), cherry_y + max(1, int(cherry_diameter * 0.18)), highlight_size, highlight_size)

    painter.end()
    return pixmap


def _strawberry_icon_pixmap(size: int = 14) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        berry_fill = QColor("#de3346")
        berry_shadow = QColor("#aa2030")
        leaf_fill = QColor("#5ea83a")
        seed_fill = QColor("#ffd76a")
        highlight = QColor("#f7a7b2")

        body_rect = QRectF(size * 0.2, size * 0.22, size * 0.6, size * 0.68)
        path = QPainterPath()
        path.moveTo(body_rect.center().x(), body_rect.top())
        path.cubicTo(body_rect.right(), body_rect.top() + body_rect.height() * 0.08, body_rect.right(), body_rect.center().y(), body_rect.center().x(), body_rect.bottom())
        path.cubicTo(body_rect.left(), body_rect.center().y(), body_rect.left(), body_rect.top() + body_rect.height() * 0.08, body_rect.center().x(), body_rect.top())

        painter.setPen(QPen(berry_shadow, 1))
        painter.setBrush(berry_fill)
        painter.drawPath(path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(leaf_fill)
        leaf_center_x = body_rect.center().x()
        leaf_base_y = body_rect.top() + body_rect.height() * 0.14
        leaf_size = max(2.5, size * 0.16)
        for offset in (-leaf_size, 0, leaf_size):
            leaf = QPainterPath()
            leaf.moveTo(leaf_center_x + offset, leaf_base_y - leaf_size * 0.9)
            leaf.lineTo(leaf_center_x + offset + leaf_size * 0.75, leaf_base_y + leaf_size * 0.1)
            leaf.lineTo(leaf_center_x + offset - leaf_size * 0.75, leaf_base_y + leaf_size * 0.1)
            leaf.closeSubpath()
            painter.drawPath(leaf)

        stem_pen = QPen(leaf_fill, max(1, int(size * 0.08)))
        painter.setPen(stem_pen)
        painter.drawLine(int(leaf_center_x), int(body_rect.top() - size * 0.02), int(leaf_center_x + size * 0.12), int(size * 0.03))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(seed_fill)
        seed_w = max(1.2, size * 0.06)
        seed_h = max(1.8, size * 0.1)
        seed_positions = (
            (0.36, 0.34),
            (0.5, 0.3),
            (0.64, 0.34),
            (0.31, 0.48),
            (0.45, 0.44),
            (0.59, 0.44),
            (0.73, 0.48),
            (0.38, 0.62),
            (0.52, 0.58),
            (0.66, 0.62),
        )
        for rel_x, rel_y in seed_positions:
            cx = size * rel_x
            cy = size * rel_y
            painter.drawEllipse(QRectF(cx - seed_w / 2, cy - seed_h / 2, seed_w, seed_h))

        painter.setBrush(highlight)
        painter.drawEllipse(QRectF(size * 0.36, size * 0.32, max(1.5, size * 0.09), max(1.5, size * 0.09)))
    finally:
        painter.end()
    return pixmap

