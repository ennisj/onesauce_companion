"""Collection Details screen: collection metadata, artwork, and video playback."""
from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, QUrl, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.collection_catalog import (
    CollectionCatalogEntry,
    build_collection_catalog,
    read_collection_info_attributes,
)
from onesauce_companion.ui._constants import COLLECTIONS_SCREEN
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
    _extract_video_thumbnail,
    _find_collection_videos,
    _find_named_collection_media_file,
    _read_story_text,
    _resolve_collection_media_root,
)


class CollectionDetailsScreen(QWidget):
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # Screen header with "Back to Collections" button at the top right.
        self._back_to_collections_button = QPushButton("Back to Collections")
        self._back_to_collections_button.clicked.connect(self._handle_back_to_collections)
        root.addWidget(
            build_screen_header_row(
                "Collection Details",
                trailing_widgets=(self._back_to_collections_button,),
            )
        )

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

    def _handle_back_to_collections(self) -> None:
        top = self.window()
        change_screen = getattr(top, "_change_screen", None)
        if callable(change_screen):
            change_screen(COLLECTIONS_SCREEN)

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
        # self.parent() returns the QStackedWidget; use window() to reach MainWindow.
        # No accept() — show_games_for_collection navigates via _change_screen,
        # which automatically calls dispose() on this screen.
        top = self.window()
        show_games = getattr(top, "_show_games_for_collection", None)
        if callable(show_games):
            show_games(collection_name)

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
