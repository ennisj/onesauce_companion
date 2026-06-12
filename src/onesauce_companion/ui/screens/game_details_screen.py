"""Game Details screen: media panels, metadata, story text, and video playback."""
from __future__ import annotations

import random
import shutil
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.games import GameManifestEntry
from onesauce_companion.ui._constants import GAMES_SCREEN
from onesauce_companion.ui._media_widgets import (
    HAS_QT_MULTIMEDIA,
    QAudioOutput,
    QMediaPlayer,
    QVideoWidget,
    ScaledImageLabel,
)
from onesauce_companion.ui._utils import _assets_dir, build_screen_header_row
from onesauce_companion.ui.game_media import (
    IMAGE_MEDIA_SUFFIXES,
    STORY_MEDIA_SUFFIXES,
    VIDEO_MEDIA_SUFFIXES,
    _extract_video_thumbnail,
    _media_key_for_title,
    _resolve_lcd_marquee_target_dir,
    _find_matching_bitlcd_media_file,
    _find_matching_lcd_marquee_file,
    _find_matching_media_file,
    _game_name_candidates,
    _read_story_text,
    _resolve_game_media_root,
)


class GameDetailsScreen(QWidget):
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # Screen header with "Back to Games" button at the top right.
        self._back_to_games_button = QPushButton("Back to Games")
        self._back_to_games_button.clicked.connect(self._handle_back_to_games)
        root.addWidget(
            build_screen_header_row(
                "Game Details",
                trailing_widgets=(self._back_to_games_button,),
            )
        )

        # Outer split: left section (2 cols × 3 rows) + right section
        # (single vertical stack). Decoupling means the right section's row
        # heights are independent of the left's — Logo/LED/LCD can be
        # compact while Video takes the remaining vertical space.
        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        self.front_art_label = ScaledImageLabel(180, minimum_width=220)
        self.bezel_label = ScaledImageLabel(180, minimum_width=220)
        self.screentitle_label = ScaledImageLabel(180, minimum_width=220)
        self.screenshot_label = ScaledImageLabel(180, minimum_width=220)
        self.logo_label = ScaledImageLabel(110, minimum_width=220)
        self.led_marquee_label = ScaledImageLabel(110, minimum_width=220)
        self.lcd_marquee_label = ScaledImageLabel(110, minimum_width=220)

        # Left section: 2 cols × 4 rows.
        #   row 0:  Front Artwork | Screen Title
        #   row 1:  Bezel         | Screenshot
        #   row 2:  Game Details (colspan 2)
        #   row 3:  Game N/M | Previous | Next | Random  (colspan 2, sibling of Game Details)
        left_grid = QGridLayout()
        left_grid.setHorizontalSpacing(16)
        left_grid.setVerticalSpacing(12)
        left_grid.setColumnStretch(0, 1)
        left_grid.setColumnStretch(1, 1)
        left_grid.setRowStretch(0, 0)
        left_grid.setRowStretch(1, 0)
        left_grid.setRowStretch(2, 1)
        left_grid.setRowStretch(3, 0)

        left_grid.addWidget(self._build_media_group("Front Artwork", self.front_art_label), 0, 0)
        left_grid.addWidget(self._build_media_group("Screen Title", self.screentitle_label), 0, 1)
        left_grid.addWidget(self._build_media_group("Bezel", self.bezel_label), 1, 0)
        left_grid.addWidget(self._build_media_group("Screenshot", self.screenshot_label), 1, 1)

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
        self.story_text.setMinimumHeight(280)
        details_layout.addWidget(self.story_text, stretch=1)
        left_grid.addWidget(details_group, 2, 0, 1, 2)

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
        left_grid.addLayout(navigation_row, 3, 0, 1, 2)

        # Right section: vertical stack — Logo, LED, LCD hug their preferred
        # height; Video gets all the vertical slack.
        right_column = QVBoxLayout()
        right_column.setSpacing(12)
        right_column.addWidget(self._build_media_group("Logo", self.logo_label))
        right_column.addWidget(self._build_media_group("LED Marquee", self.led_marquee_label))
        right_column.addWidget(self._build_media_group("LCD Marquee", self.lcd_marquee_label))
        right_column.addWidget(self._build_video_group(), stretch=1)

        content_row.addLayout(left_grid, stretch=2)
        content_row.addLayout(right_column, stretch=1)
        root.addLayout(content_row, stretch=1)

        self._update_navigation_buttons()
        self._refresh_entry_view()

    def dispose(self) -> None:
        """Stop media playback and collapse expanded video.

        Called when the screen is being navigated away from or replaced —
        QWidget doesn't fire ``closeEvent`` for embedded widgets the way
        QDialog did.
        """
        if self._video_expanded:
            self._set_video_expanded(False)
        if self._media_player is not None:
            self._media_player.stop()

    def _handle_back_to_games(self) -> None:
        top = self.window()
        change_screen = getattr(top, "_change_screen", None)
        if callable(change_screen):
            change_screen(GAMES_SCREEN)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._video_expanded:
            self._update_expanded_video_geometry()

    def _refresh_entry_view(self) -> None:
        self._update_metadata_labels()
        self._populate()
        self._update_navigation_buttons()

    def _update_metadata_labels(self) -> None:
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
        # self.parent() now returns the QStackedWidget (embedded screen);
        # use self.window() to reach the MainWindow.
        top = self.window()
        open_collection = getattr(top, "_open_collection_details_by_name", None)
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


