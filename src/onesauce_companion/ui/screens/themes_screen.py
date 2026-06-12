"""Themes screen: theme catalog browser with layout preview and render pipeline.

Ported from the themeplay branch's monolithic main_window.py into a free-function
module for the refactored screen architecture.
"""
from __future__ import annotations

import random
import re
import shutil
import subprocess
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.collection_catalog import (
    collection_directory_candidates,
    read_collection_info_attributes,
)
from onesauce_companion.services.collections import scan_collection_definitions
from onesauce_companion.services.games import GameManifestEntry, is_excluded_game, scan_excluded_games
from onesauce_companion.services.hyperlist_metadata import lookup_hyperlist_metadata
from onesauce_companion.services.themes import (
    ThemeCatalogEntry,
    ThemeLayoutPreview,
    ThemePreviewElement,
    _read_settings_conf,
    build_theme_layout_preview,
)
from onesauce_companion.ui._constants import THEMES_SCREEN
from onesauce_companion.ui._utils import build_screen_header_row
from onesauce_companion.ui.theme_preview import (
    ThemeLayoutPreviewWidget,
    ThemePreviewRenderData,
    ThemePreviewVideoSession,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink

    HAS_QT_MULTIMEDIA = True
except ImportError:
    QAudioOutput = None  # type: ignore[assignment,misc]
    QMediaPlayer = None  # type: ignore[assignment,misc]
    QVideoFrame = None  # type: ignore[assignment,misc]
    QVideoSink = None  # type: ignore[assignment,misc]
    HAS_QT_MULTIMEDIA = False

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow

IMAGE_MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_MEDIA_SUFFIXES = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
STORY_MEDIA_SUFFIXES = {".txt"}

_VIDEO_THUMBNAIL_CACHE: dict[tuple[str, int], QPixmap] = {}


# ---------------------------------------------------------------------------
# Build screen
# ---------------------------------------------------------------------------

def build_themes_screen(self: "MainWindow") -> QWidget:
    screen = QWidget()
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("Themes"))

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)

    list_group = QGroupBox("Themes")
    list_layout = QVBoxLayout(list_group)
    list_layout.setSpacing(10)
    self.themes_results_label = QLabel("0 themes")
    self.themes_results_label.setObjectName("themesMetaLabel")
    self.system_themes_label = QLabel("System Themes")
    self.system_themes_label.setObjectName("themesMetaLabel")
    self.system_themes_list = QListWidget()
    self.system_themes_list.setObjectName("ThemeList")
    self.system_themes_list.itemSelectionChanged.connect(lambda: _handle_theme_selection_changed(self))
    self.custom_installed_themes_label = QLabel("Custom Themes")
    self.custom_installed_themes_label.setObjectName("themesMetaLabel")
    self.custom_installed_themes_label.hide()  # Custom theme support disabled in this release
    self.custom_installed_themes_list = QListWidget()
    self.custom_installed_themes_list.setObjectName("ThemeList")
    self.custom_installed_themes_list.itemSelectionChanged.connect(lambda: _handle_theme_selection_changed(self))
    self.custom_installed_themes_list.hide()  # Custom theme support disabled in this release
    list_layout.addWidget(self.themes_results_label)
    list_layout.addWidget(self.system_themes_label)
    list_layout.addWidget(self.system_themes_list, stretch=2)
    list_layout.addWidget(self.custom_installed_themes_label)
    list_layout.addWidget(self.custom_installed_themes_list, stretch=1)

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
    self.themes_collection_filter.currentIndexChanged.connect(lambda: _handle_theme_collection_changed(self))
    preview_header.addWidget(self.themes_collection_filter, stretch=1)
    self.themes_game_filter = QComboBox()
    self.themes_game_filter.currentIndexChanged.connect(lambda: _handle_theme_game_changed(self))
    preview_header.addWidget(self.themes_game_filter, stretch=1)
    self.themes_preview_caption = QLabel("Color-coded boxes show the active root or collection override layout.")
    self.themes_preview_caption.setObjectName("themesMetaLabel")
    self.themes_preview = ThemeLayoutPreviewWidget()
    self.themes_preview.elementSelected.connect(lambda element: _handle_theme_preview_selection_changed(self, element))
    self.themes_preview.previousRequested.connect(lambda: _handle_theme_preview_previous_requested(self))
    self.themes_preview.playPauseRequested.connect(lambda: _toggle_theme_preview_animation(self))
    self.themes_preview.nextRequested.connect(lambda: _handle_theme_preview_next_requested(self))
    self.themes_preview.muteRequested.connect(lambda: _toggle_theme_preview_mute(self))
    self.themes_preview.wheelAnimationIndexChanged.connect(lambda idx: _handle_theme_preview_scroll_index_changed(self, idx))
    self.themes_preview.wheelAnimationFinished.connect(lambda: _on_wheel_animation_finished(self))
    self.themes_preview.scrollFadeFinished.connect(lambda: _on_theme_preview_scroll_fade_finished(self))
    self.themes_element_selector = QComboBox()
    self.themes_element_selector.currentIndexChanged.connect(lambda: _handle_theme_element_selector_changed(self))
    self.themes_show_wireframes_checkbox.stateChanged.connect(lambda _state: _handle_theme_wireframe_toggled(self))
    self.themes_show_media_checkbox.stateChanged.connect(lambda _state: _handle_theme_media_toggled(self))
    self.themes_show_text_checkbox.stateChanged.connect(lambda _state: _handle_theme_text_toggled(self))
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


# ---------------------------------------------------------------------------
# Theme screen refresh / catalog
# ---------------------------------------------------------------------------

def refresh_themes_screen(self: "MainWindow") -> None:
    target = self._target_dir()
    target_key = str(target) if target is not None else ""
    if self._themes_catalog_target == target_key:
        # Cache hit — proceed straight to the population/preview phase.
        _refresh_themes_screen_phase_2(self)
        return
    # Cache miss — kick off the async scan; phase 2 fires from its slot.
    _start_theme_catalog_scan(self, target, target_key)


def _start_theme_catalog_scan(self: "MainWindow", target, target_key: str) -> None:
    if self._theme_catalog_handle.running:
        # Newer target supersedes; queue a restart for when current finishes.
        self._theme_catalog_pending_target = target
        self._theme_catalog_pending_target_key = target_key
        self._theme_catalog_restart_pending = True
        return

    from onesauce_companion.ui.workers import ThemeCatalogWorker

    self._theme_catalog_completed = 0
    self._theme_catalog_total = 0
    self._theme_catalog_pending_target = None
    self._theme_catalog_pending_target_key = None

    worker = ThemeCatalogWorker(target, target_key)
    worker.entry_ready.connect(self._handle_theme_entry_ready)
    worker.finished.connect(self._handle_theme_catalog_finished)
    self._theme_catalog_handle.start(
        worker,
        finish_signals=(worker.finished,),
        on_cleared=lambda: on_theme_catalog_cleared(self),
    )
    self._update_loading_indicator()


def on_theme_entry_ready(self: "MainWindow", completed: int, total: int, _entry: object) -> None:
    self._theme_catalog_completed = completed
    self._theme_catalog_total = total
    self._update_loading_indicator()


def on_theme_catalog_finished(self: "MainWindow", entries: object, target_key: str) -> None:
    if isinstance(entries, tuple):
        self._theme_entries = entries
    self._themes_catalog_target = target_key
    if self.stack.currentIndex() != THEMES_SCREEN:
        return
    # Switch the bar to "Rendering Theme…" before doing the synchronous render
    # work, then defer phase 2 so the bar can repaint before the GUI thread
    # blocks on list population + preview rendering.
    self._theme_rendering = True
    self._update_loading_indicator()
    QTimer.singleShot(50, lambda: _run_theme_render_phase(self))


def _run_theme_render_phase(self: "MainWindow") -> None:
    try:
        _refresh_themes_screen_phase_2(self)
    finally:
        self._theme_rendering = False
        self._update_loading_indicator()


def on_theme_catalog_cleared(self: "MainWindow") -> None:
    self._update_loading_indicator()
    if self._theme_catalog_restart_pending:
        self._theme_catalog_restart_pending = False
        target = self._theme_catalog_pending_target
        target_key = self._theme_catalog_pending_target_key or ""
        self._theme_catalog_pending_target = None
        self._theme_catalog_pending_target_key = None
        _start_theme_catalog_scan(self, target, target_key)
    self._finalize_close_if_ready()


def _refresh_themes_screen_phase_2(self: "MainWindow") -> None:
    self._refresh_games_catalog()
    self._refresh_collections_catalog()

    target = self._target_dir()
    selected_name = self._selected_theme_name
    if selected_name is None:
        current_item = self.system_themes_list.currentItem() or self.custom_installed_themes_list.currentItem()
        if current_item is not None:
            selected_name = current_item.text()

    system_entries = [entry for entry in self._theme_entries if not entry.is_custom]
    # Custom themes hidden in this release. Variable kept for symmetry with
    # the addItem loop below; the underlying widgets are hidden in build_themes_screen.
    custom_entries: list = []

    self.system_themes_list.blockSignals(True)
    self.custom_installed_themes_list.blockSignals(True)
    self.system_themes_list.clear()
    self.custom_installed_themes_list.clear()
    for entry in system_entries:
        self.system_themes_list.addItem(entry.name)
    for entry in custom_entries:
        self.custom_installed_themes_list.addItem(entry.name)
    self.themes_results_label.setText(f"{len(system_entries)} themes")

    selected_row = -1
    if system_entries:
        if selected_name:
            for index, entry in enumerate(system_entries):
                if entry.name == selected_name:
                    selected_row = index
                    break
        if selected_row < 0:
            selected_row = 0
        self._selected_theme_name = system_entries[selected_row].name
        selected_entry = system_entries[selected_row]
        if selected_entry.is_custom:
            custom_row = next((index for index, entry in enumerate(custom_entries) if entry.name == selected_entry.name), -1)
            if custom_row >= 0:
                self.custom_installed_themes_list.setCurrentRow(custom_row)
                self.system_themes_list.clearSelection()
        else:
            system_row = next((index for index, entry in enumerate(system_entries) if entry.name == selected_entry.name), -1)
            if system_row >= 0:
                self.system_themes_list.setCurrentRow(system_row)
                self.custom_installed_themes_list.clearSelection()
    else:
        self._selected_theme_name = None
    self.system_themes_list.blockSignals(False)
    self.custom_installed_themes_list.blockSignals(False)
    _sync_themes_collection_filter(self)
    _sync_themes_game_filter(self)

    if not system_entries:
        if target is None:
            self.themes_name_label.setText("Theme: None")
            self.themes_canvas_label.setText("Canvas Size: Unknown")
        else:
            self.themes_name_label.setText("Theme: None")
            self.themes_canvas_label.setText("Canvas Size: Unknown")
        self.themes_preview_caption.setText("The preview updates after a theme is selected.")
        self.themes_preview.set_preview(None)
        _set_theme_preview_render_data(self, {})
        _populate_theme_element_selector(self, None)
        self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
        if self.stack.currentIndex() == THEMES_SCREEN:
            if target is None:
                self._push_status_message("Select a target folder to scan themes.")
            else:
                self._push_status_message(f"No themes found for {target}")
        return

    _refresh_selected_theme_preview(self)


# ---------------------------------------------------------------------------
# Collection / game filter sync
# ---------------------------------------------------------------------------

def _sync_themes_collection_filter(self: "MainWindow") -> None:
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


def _sync_themes_game_filter(self: "MainWindow") -> None:
    selected_key = self._selected_theme_game_key
    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    game_entries = _theme_games_for_collection(self, selected_collection)
    self.themes_game_filter.blockSignals(True)
    self.themes_game_filter.clear()
    if not game_entries:
        self.themes_game_filter.addItem("No games available", None)

    duplicate_counts: dict[str, int] = {}
    for entry in game_entries:
        duplicate_counts[entry.game_name.casefold()] = duplicate_counts.get(entry.game_name.casefold(), 0) + 1

    matched_index = -1
    for index, entry in enumerate(game_entries):
        display_name = entry.game_name
        if duplicate_counts.get(entry.game_name.casefold(), 0) > 1:
            display_name = f"{entry.game_name} [{entry.collection_name}]"
        item_key = entry.key
        self.themes_game_filter.addItem(display_name, entry)
        if selected_key == item_key:
            matched_index = index
    if game_entries and matched_index < 0:
        matched_index = 0
    if matched_index >= 0:
        self.themes_game_filter.setCurrentIndex(matched_index)
    elif self.themes_game_filter.count() > 0:
        self.themes_game_filter.setCurrentIndex(0)
    current_entry = self.themes_game_filter.currentData()
    self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
    self._theme_preview_previous_stopped_game_key = None
    self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
    self.themes_game_filter.blockSignals(False)


def _themes_game_filter_has_placeholder(self: "MainWindow") -> bool:
    current_data = self.themes_game_filter.itemData(0) if self.themes_game_filter.count() > 0 else None
    return not isinstance(current_data, GameManifestEntry)


def _theme_game_zero_index_from_combo_index(self: "MainWindow", combo_index: int) -> int:
    if combo_index < 0:
        return 0
    if _themes_game_filter_has_placeholder(self):
        return max(0, combo_index - 1)
    return combo_index


def _theme_game_combo_index_from_zero_index(self: "MainWindow", zero_index: int) -> int:
    if _themes_game_filter_has_placeholder(self):
        return zero_index + 1
    return zero_index


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_theme_selection_changed(self: "MainWindow") -> None:
    sender = self.sender()
    if sender is self.system_themes_list and self.system_themes_list.currentItem() is not None:
        self.custom_installed_themes_list.blockSignals(True)
        self.custom_installed_themes_list.clearSelection()
        self.custom_installed_themes_list.blockSignals(False)
        current_item = self.system_themes_list.currentItem()
    elif sender is self.custom_installed_themes_list and self.custom_installed_themes_list.currentItem() is not None:
        self.system_themes_list.blockSignals(True)
        self.system_themes_list.clearSelection()
        self.system_themes_list.blockSignals(False)
        current_item = self.custom_installed_themes_list.currentItem()
    else:
        current_item = self.system_themes_list.currentItem() or self.custom_installed_themes_list.currentItem()
    self._selected_theme_name = current_item.text() if current_item is not None else None
    _sync_themes_game_filter(self)
    # Defer the preview render so the selection highlight paints first.
    _schedule_preview_render(self, full_rebuild=True)
    self._save_settings()


def _schedule_preview_render(self: "MainWindow", full_rebuild: bool) -> None:
    """Defer the theme preview render so click feedback paints first.

    Multiple click events that arrive before the timer fires are coalesced
    into a single render. ``full_rebuild=True`` from any caller upgrades the
    pending render to ``_refresh_selected_theme_preview`` (covers theme/
    collection changes); otherwise the lighter ``_refresh_theme_preview_render_only``
    runs.
    """
    if full_rebuild:
        self._theme_render_full_requested = True
    if self._theme_render_pending:
        return
    self._theme_render_pending = True
    self._theme_rendering = True
    self._update_loading_indicator()
    QTimer.singleShot(50, lambda: _run_preview_render(self))


def _run_preview_render(self: "MainWindow") -> None:
    self._theme_render_pending = False
    full = self._theme_render_full_requested
    self._theme_render_full_requested = False
    try:
        if full:
            _refresh_selected_theme_preview(self)
        else:
            _refresh_theme_preview_render_only(self)
    finally:
        self._theme_rendering = False
        self._update_loading_indicator()


def _handle_theme_collection_changed(self: "MainWindow") -> None:
    self._selected_theme_collection_name = str(self.themes_collection_filter.currentData() or "") or None
    _sync_themes_game_filter(self)
    _schedule_preview_render(self, full_rebuild=True)
    self._save_settings()


def _handle_theme_game_changed(self: "MainWindow") -> None:
    current_entry = self.themes_game_filter.currentData()
    self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
    if not self._theme_preview_animation_enabled:
        self._theme_preview_previous_stopped_game_key = None
        self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
    if not self.themes_preview._wheel_anim_active:
        _schedule_preview_render(self, full_rebuild=False)
    self._save_settings()


def _handle_theme_wireframe_toggled(self: "MainWindow") -> None:
    _apply_shared_theme_visibility_settings(self, wireframes=self.themes_show_wireframes_checkbox.isChecked())
    self._save_settings()


def _handle_theme_media_toggled(self: "MainWindow") -> None:
    _apply_shared_theme_visibility_settings(self, media=self.themes_show_media_checkbox.isChecked())
    self._save_settings()


def _handle_theme_text_toggled(self: "MainWindow") -> None:
    _apply_shared_theme_visibility_settings(self, text=self.themes_show_text_checkbox.isChecked())
    self._save_settings()


def _apply_shared_theme_visibility_settings(
    self: "MainWindow",
    *,
    wireframes: bool | None = None,
    media: bool | None = None,
    text: bool | None = None,
) -> None:
    current_wireframes = self.themes_show_wireframes_checkbox.isChecked()
    current_media = self.themes_show_media_checkbox.isChecked()
    current_text = self.themes_show_text_checkbox.isChecked()
    wireframes_value = current_wireframes if wireframes is None else wireframes
    media_value = current_media if media is None else media
    text_value = current_text if text is None else text
    checkbox_pairs = (
        (self.themes_show_wireframes_checkbox, wireframes_value),
        (self.themes_show_media_checkbox, media_value),
        (self.themes_show_text_checkbox, text_value),
    )
    for checkbox, value in checkbox_pairs:
        checkbox.blockSignals(True)
        checkbox.setChecked(value)
        checkbox.blockSignals(False)
    self.themes_preview.set_show_wireframes(wireframes_value)
    self.themes_preview.set_show_media(media_value)
    self.themes_preview.set_show_text(text_value)


# ---------------------------------------------------------------------------
# Preview lifecycle
# ---------------------------------------------------------------------------

def _refresh_selected_theme_preview(self: "MainWindow") -> None:
    if not hasattr(self, "themes_name_label"):
        return
    was_animating = self._theme_preview_animation_enabled
    if was_animating:
        self._theme_preview_cycle_timer.stop()
        self._theme_preview_scroll_timer.stop()
        self._theme_preview_pending_indices.clear()
    theme_name = self._selected_theme_name
    if theme_name is None:
        current_item = self.system_themes_list.currentItem() or self.custom_installed_themes_list.currentItem()
        if current_item is not None:
            theme_name = current_item.text()
    target = self._target_dir()
    if target is None or not theme_name:
        self._theme_preview = None
        self._selected_theme_element = None
        self.themes_name_label.setText("Theme: None")
        self.themes_canvas_label.setText("Canvas Size: Unknown")
        self.themes_preview_caption.setText("The preview updates after a theme is selected.")
        self.themes_preview.set_preview(None)
        _set_theme_preview_render_data(self, {})
        self._theme_preview_previous_stopped_game_key = None
        self._theme_preview_last_stopped_game_key = None
        _populate_theme_element_selector(self, None)
        self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
        return

    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    theme_entry = next((entry for entry in self._theme_entries if entry.name == theme_name), None)
    effective_layout_collection = _find_effective_layout_collection(self, theme_entry, selected_collection) if theme_entry and selected_collection else None
    preview = build_theme_layout_preview(target, theme_name, selected_collection or None, layout_collection_name=effective_layout_collection)
    self._theme_preview = preview
    self._selected_theme_element = None
    self.themes_preview.set_preview(preview)
    _set_theme_preview_render_data(self, _build_theme_render_data(self, preview))
    self._theme_preview_previous_stopped_game_key = None
    self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
    self.themes_preview.set_show_wireframes(self.themes_show_wireframes_checkbox.isChecked())
    self.themes_preview.set_show_media(self.themes_show_media_checkbox.isChecked())
    self.themes_preview.set_show_text(self.themes_show_text_checkbox.isChecked())
    _populate_theme_element_selector(self, preview)
    self.themes_element_details.setPlainText("Click a preview element to inspect its details.")
    if was_animating:
        _start_theme_preview_animation(self)

    _update_theme_summary(self, theme_entry, preview)
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


def _refresh_theme_preview_render_only(self: "MainWindow") -> None:
    preview = self._theme_preview
    if preview is None:
        _set_theme_preview_render_data(self, {})
        return
    _set_theme_preview_render_data(self, _build_theme_render_data(self, preview))


# ---------------------------------------------------------------------------
# Element selector / details
# ---------------------------------------------------------------------------

def _handle_theme_preview_selection_changed(self: "MainWindow", element: object) -> None:
    self._selected_theme_element = element if isinstance(element, ThemePreviewElement) else None
    _sync_theme_element_selector(self, self._selected_theme_element)
    self.themes_preview.select_element(self._selected_theme_element)
    self.themes_element_details.setPlainText(_format_theme_element_details(self._selected_theme_element))


def _handle_theme_element_selector_changed(self: "MainWindow") -> None:
    index = self.themes_element_selector.currentIndex()
    if index < 0 or index >= len(self._theme_element_index_map):
        return
    selected_element = self._theme_element_index_map[index]
    self._selected_theme_element = selected_element
    self.themes_preview.select_element(selected_element)
    self.themes_element_details.setPlainText(_format_theme_element_details(selected_element))


def _populate_theme_element_selector(self: "MainWindow", preview: ThemeLayoutPreview | None) -> None:
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


def _sync_theme_element_selector(self: "MainWindow", element: ThemePreviewElement | None) -> None:
    self.themes_element_selector.blockSignals(True)
    target_index = 0
    for index, mapped_element in enumerate(self._theme_element_index_map):
        if mapped_element == element:
            target_index = index
            break
    self.themes_element_selector.setCurrentIndex(target_index)
    self.themes_element_selector.blockSignals(False)


def _update_theme_summary(self: "MainWindow", theme_entry: ThemeCatalogEntry | None, preview: ThemeLayoutPreview | None) -> None:
    if theme_entry is None:
        self.themes_name_label.setText("Theme: None")
        self.themes_canvas_label.setText("Canvas Size: Unknown")
        return
    self.themes_name_label.setText(f"Theme: {theme_entry.name}")
    if preview is None:
        self.themes_canvas_label.setText("Canvas Size: Unknown")
        return
    self.themes_canvas_label.setText(f"Canvas Size: {int(preview.canvas_width)} x {int(preview.canvas_height)}")


def _format_theme_element_details(element: ThemePreviewElement | None) -> str:
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


# ---------------------------------------------------------------------------
# Collection layout inheritance
# ---------------------------------------------------------------------------

def _find_effective_layout_collection(self: "MainWindow", theme_entry: ThemeCatalogEntry, collection_name: str) -> str | None:
    if not collection_name:
        return None
    if _collection_has_layout(theme_entry, collection_name):
        return collection_name

    cat = {e.name: e for e in self._collection_entries}
    entry = cat.get(collection_name)
    if entry is None:
        return None

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
        if _collection_has_layout(theme_entry, candidate):
            return candidate
        candidate_entry = cat.get(candidate)
        if candidate_entry is not None:
            queue.extend(n for n in candidate_entry.parent_collections if n.casefold() not in visited)
    return None


def _collection_has_layout(theme_entry: ThemeCatalogEntry, collection_name: str) -> bool:
    layout_dir = theme_entry.root_dir / "collections" / collection_name / "layout"
    return (layout_dir / "layout.xml").exists() or (layout_dir / "layout.lua").exists()


# ---------------------------------------------------------------------------
# Game resolution helpers
# ---------------------------------------------------------------------------

def _excluded_games_for_current_target(self: "MainWindow") -> set[tuple[str, str]]:
    target = self._target_dir()
    target_key = str(target) if target is not None else ""
    if self._games_excluded_target == target_key:
        return self._excluded_games_cache
    self._games_excluded_target = target_key
    self._excluded_games_cache = scan_excluded_games(target)
    return self._excluded_games_cache


def _theme_games_for_collection(self: "MainWindow", collection_name: str) -> tuple[GameManifestEntry, ...]:
    if not collection_name:
        return tuple()
    cached = self._theme_games_cache.get(collection_name)
    if cached is not None:
        return cached
    catalog_entry = next((e for e in self._collection_entries if e.name == collection_name), None)
    if catalog_entry is not None and catalog_entry.child_collections:
        entries = [
            GameManifestEntry(
                game_name=child_name,
                collection_name=child_name,
                rom_path=child_name,
                source_pack=child_name,
                install_collection_name=child_name,
            )
            for child_name in catalog_entry.child_collections
        ]
        result = tuple(entries)
        self._theme_games_cache[collection_name] = result
        return result
    entries = [
        entry
        for entry in self._game_entries
        if entry.collection_name == collection_name
    ]
    by_key = {entry.key: entry for entry in entries}
    for entry in _scan_collection_game_entries(self, collection_name):
        by_key.setdefault(entry.key, entry)
    excluded_games = _excluded_games_for_current_target(self)
    entries = [entry for entry in by_key.values() if not is_excluded_game(entry, excluded_games)]
    entries.sort(key=lambda entry: (entry.game_name.casefold(), entry.collection_name.casefold(), entry.rom_path.casefold()))
    result = tuple(entries)
    self._theme_games_cache[collection_name] = result
    return result


def _scan_collection_game_entries(self: "MainWindow", collection_name: str) -> tuple[GameManifestEntry, ...]:
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


# ---------------------------------------------------------------------------
# Render data pipeline
# ---------------------------------------------------------------------------

def _build_theme_render_data(self: "MainWindow", preview: ThemeLayoutPreview | None) -> dict[ThemePreviewElement, ThemePreviewRenderData]:
    if preview is None:
        return {}
    selected_collection = preview.selected_collection
    selected_game = self.themes_game_filter.currentData()
    game_entry = selected_game if isinstance(selected_game, GameManifestEntry) else None
    collection_games = _theme_games_for_collection(self, selected_collection or "")
    collection_index = 0
    if game_entry is not None:
        for index, entry in enumerate(collection_games, start=1):
            if entry.key == game_entry.key:
                collection_index = index
                break
    return _build_theme_render_data_for_state(
        self,
        preview,
        selected_collection,
        game_entry,
        collection_games,
        collection_index,
    )


def _build_theme_render_data_for_state(
    self: "MainWindow",
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
        resolved = _resolve_theme_preview_element_render(
            self,
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
    self: "MainWindow",
    preview: ThemeLayoutPreview,
    target_zero_index: int,
) -> dict[ThemePreviewElement, ThemePreviewRenderData]:
    selected_collection = preview.selected_collection or self._selected_theme_collection_name or ""
    collection_games = _theme_games_for_collection(self, selected_collection)
    if not collection_games:
        return {}
    total_games = len(collection_games)
    resolved_zero_index = target_zero_index % total_games
    game_entry = collection_games[resolved_zero_index]
    return _build_theme_render_data_for_state(
        self,
        preview,
        selected_collection or None,
        game_entry,
        collection_games,
        resolved_zero_index + 1,
        scroll_only=True,
    )


def _set_theme_preview_render_data(self: "MainWindow", render_data: dict[ThemePreviewElement, ThemePreviewRenderData], *, transition: bool = True) -> None:
    previous_render_data = dict(self._theme_preview_render_data)
    merged_render_data = dict(render_data)
    for element, data in list(merged_render_data.items()):
        if data.video_path is None:
            continue
        previous = previous_render_data.get(element)
        if previous is None or previous.pixmap is None or previous.pixmap.isNull():
            continue
        if previous.video_path is None:
            continue
        merged_render_data[element] = replace(data, pixmap=previous.pixmap)
    self._theme_preview_render_data = merged_render_data
    self._theme_preview_promoted_final_zero_index = None
    self.themes_preview.set_render_data(self._theme_preview_render_data, transition=transition)
    _sync_theme_preview_video_sessions(self)
    _sync_theme_preview_animation_controls(self)


# ---------------------------------------------------------------------------
# Element render resolution
# ---------------------------------------------------------------------------

def _resolve_theme_preview_element_render(
    self: "MainWindow",
    element: ThemePreviewElement,
    theme_entry: ThemeCatalogEntry | None,
    collection_name: str | None,
    game_entry: GameManifestEntry | None,
    collection_games: tuple[GameManifestEntry, ...],
    collection_index: int,
    layout_collection: str | None = None,
) -> ThemePreviewRenderData | None:
    mode_key = (element.mode or "").casefold()
    static_render = _resolve_static_theme_render(element)
    if static_render is not None:
        return static_render

    if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"}:
        text_value = _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index)
        if text_value:
            return ThemePreviewRenderData(text=text_value)

    display_entry = (
        _theme_menu_entry_for_element(element, game_entry, collection_games, collection_index)
        if game_entry is not None
        else None
    )

    if mode_key == "systemlayout" and theme_entry is not None:
        prefer_item_collection = not (display_entry is not None and not Path(display_entry.rom_path).suffix)
        for candidate_collection in _theme_preview_layout_collection_candidates(
            display_entry,
            collection_name,
            layout_collection,
            prefer_item_collection=prefer_item_collection,
        ):
            collection_render = _resolve_layout_theme_render(
                self,
                element,
                theme_entry,
                candidate_collection,
                None,
                allow_system_fallback=True,
            )
            if collection_render is not None:
                return collection_render
        if display_entry is not None and not Path(display_entry.rom_path).suffix:
            return None

    if mode_key == "layout" and theme_entry is not None:
        candidate_collections = _theme_preview_layout_collection_candidates(
            display_entry,
            collection_name,
            layout_collection,
        )
        if (
            str(getattr(theme_entry, "name", "")).casefold() == "luna og"
            and (collection_name or "").casefold() == "main"
            and element.kind == "menu"
            and (element.slot_name or "").strip().casefold() == "logo"
            and display_entry is not None
            and not Path(display_entry.rom_path).suffix
            and element.text_fallback
        ):
            preferred: list[str] = []
            seen: set[str] = set()
            for candidate in (collection_name, layout_collection, display_entry.collection_name):
                name = (candidate or "").strip()
                if not name:
                    continue
                folded = name.casefold()
                if folded in seen:
                    continue
                seen.add(folded)
                preferred.append(name)
            candidate_collections = tuple(preferred)
        for candidate_collection in candidate_collections:
            layout_render = _resolve_layout_theme_render(
                self,
                element,
                theme_entry,
                candidate_collection,
                display_entry,
            )
            if layout_render is not None:
                return layout_render
        if element.kind != "menu":
            return None
        if display_entry is not None and (element.kind == "menu" or element.text_fallback):
            text_value = _resolve_theme_preview_text(self, element, collection_name, display_entry, collection_games, collection_index)
            if not text_value:
                text_value = display_entry.game_name or None
            if text_value:
                return ThemePreviewRenderData(text=text_value)
        return None

    if mode_key == "layout_preferred" and theme_entry is not None and layout_collection:
        layout_preferred_render = _resolve_layout_preferred_render(
            self,
            element,
            theme_entry,
            collection_name,
            layout_collection,
            game_entry,
        )
        if layout_preferred_render is not None:
            return layout_preferred_render

    if game_entry is not None:
        game_render = _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index)
        if game_render is not None:
            return game_render

    return None


def _theme_preview_layout_collection_candidates(
    display_entry: GameManifestEntry | None,
    collection_name: str | None,
    layout_collection: str | None,
    *,
    prefer_item_collection: bool = True,
) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _push(value: str | None) -> None:
        name = (value or "").strip()
        if not name:
            return
        folded = name.casefold()
        if folded in seen:
            return
        seen.add(folded)
        candidates.append(name)

    if display_entry is not None and prefer_item_collection:
        rom_stem = Path(display_entry.rom_path).stem.strip()
        if rom_stem and not Path(display_entry.rom_path).suffix:
            _push(rom_stem)
        _push(display_entry.collection_name)
    _push(collection_name)
    _push(layout_collection)
    return tuple(candidates)


def _resolve_static_theme_render(element: ThemePreviewElement) -> ThemePreviewRenderData | None:
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


def _resolve_collection_theme_render(self: "MainWindow", element: ThemePreviewElement, collection_name: str) -> ThemePreviewRenderData | None:
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


def _resolve_collection_chain_theme_render(
    self: "MainWindow",
    element: ThemePreviewElement,
    *collection_candidates: str | None,
) -> ThemePreviewRenderData | None:
    queue: list[str] = []
    seen: set[str] = set()
    catalog = {entry.name.casefold(): entry for entry in self._collection_entries}

    def _enqueue(name: str | None) -> None:
        normalized = (name or "").strip()
        if not normalized:
            return
        folded = normalized.casefold()
        if folded in seen:
            return
        seen.add(folded)
        queue.append(normalized)

    for candidate in collection_candidates:
        _enqueue(candidate)

    while queue:
        collection_name = queue.pop(0)
        render = _resolve_collection_theme_render(self, element, collection_name)
        if render is not None and render.pixmap is not None:
            return render
        entry = catalog.get(collection_name.casefold())
        if entry is None:
            continue
        for parent_name in entry.parent_collections:
            _enqueue(parent_name)
    return None


def _resolve_layout_theme_render(
    self: "MainWindow",
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
    is_collection_placeholder = game_entry is not None and not Path(game_entry.rom_path).suffix
    if element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
        if game_entry is not None:
            base_names = _game_name_candidates(Path(game_entry.rom_path).name)
            media_path = _find_matching_media_file(medium_artwork / slot_key, base_names, IMAGE_MEDIA_SUFFIXES)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if (
            allow_system_fallback
            and is_collection_placeholder
            and element.kind == "menu"
            and slot_key == "logo"
        ):
            if layout_collection.casefold() != game_entry.collection_name.casefold():
                child_layout_root = theme_entry.root_dir / "collections" / game_entry.collection_name
                child_system_artwork = child_layout_root / "system_artwork"
                if child_system_artwork.exists():
                    media_path = _find_named_collection_media_file(child_system_artwork, slot_key, IMAGE_MEDIA_SUFFIXES)
                    if media_path is not None:
                        pixmap = QPixmap(str(media_path))
                        if not pixmap.isNull():
                            return ThemePreviewRenderData(pixmap=pixmap)
            if not element.text_fallback:
                collection_render = _resolve_collection_theme_render(self, element, game_entry.collection_name)
                if collection_render is not None and collection_render.pixmap is not None:
                    return collection_render
        if allow_system_fallback and (element.kind != "menu" or is_collection_placeholder) and system_artwork.exists():
            media_path = _find_named_collection_media_file(system_artwork, slot_key, IMAGE_MEDIA_SUFFIXES)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if (
            allow_system_fallback
            and is_collection_placeholder
            and element.kind != "menu"
            and slot_key == "device"
            and element.max_width is not None
            and element.max_height is not None
        ):
            collection_render = _resolve_collection_theme_render(self, element, game_entry.collection_name)
            if collection_render is not None and collection_render.pixmap is not None:
                return collection_render
        if allow_system_fallback and is_collection_placeholder and element.kind != "menu":
            child_layout_root = theme_entry.root_dir / "collections" / game_entry.collection_name
            child_system_artwork = child_layout_root / "system_artwork"
            if child_system_artwork.exists():
                media_path = _find_named_collection_media_file(child_system_artwork, slot_key, IMAGE_MEDIA_SUFFIXES)
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
        if allow_system_fallback and is_collection_placeholder:
            collection_render = _resolve_collection_theme_render(self, element, game_entry.collection_name)
            if collection_render is not None and (
                collection_render.video_path is not None or collection_render.pixmap is not None
            ):
                return collection_render
    return None


def _resolve_layout_preferred_render(
    self: "MainWindow",
    element: ThemePreviewElement,
    theme_entry: ThemeCatalogEntry,
    collection_name: str | None,
    layout_collection: str,
    game_entry: GameManifestEntry | None,
) -> ThemePreviewRenderData | None:
    if game_entry is None:
        return _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry)

    if collection_name:
        selected_collection_render = _resolve_layout_theme_render(
            self,
            element,
            theme_entry,
            collection_name,
            game_entry,
            allow_system_fallback=False,
        )
        if selected_collection_render is not None:
            return selected_collection_render

    game_render = _resolve_game_theme_render(
        self,
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
        inherited_layout_render = _resolve_layout_theme_render(
            self,
            element,
            theme_entry,
            layout_collection,
            game_entry,
            allow_system_fallback=True,
        )
        if inherited_layout_render is not None:
            return inherited_layout_render

    if collection_name and collection_name.casefold() == layout_collection.casefold():
        same_layout_render = _resolve_layout_theme_render(
            self,
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
    self: "MainWindow",
    element: ThemePreviewElement,
    theme_entry: ThemeCatalogEntry | None,
    collection_name: str | None,
    game_entry: GameManifestEntry,
    collection_games: tuple[GameManifestEntry, ...],
    collection_index: int,
) -> ThemePreviewRenderData | None:
    slot_key = (element.slot_name or "").strip().casefold()
    mode_key = (element.mode or "").casefold()
    display_entry = _theme_menu_entry_for_element(element, game_entry, collection_games, collection_index)
    base_names = _game_name_candidates(Path(display_entry.rom_path).name)
    media_root = _resolve_theme_game_media_root(self, display_entry)
    is_collection_placeholder = not Path(display_entry.rom_path).suffix

    if mode_key in {"commonlayout", "common"} and theme_entry is not None:
        common_render = _resolve_common_theme_render(self, theme_entry, slot_key, display_entry, collection_name, _common_root_for_mode(self, theme_entry, mode_key))
        if common_render is not None:
            return common_render

    if element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
        media_path = _resolve_game_media_path(media_root, base_names, slot_key)
        if media_path is not None:
            pixmap = QPixmap(str(media_path))
            if not pixmap.isNull():
                return ThemePreviewRenderData(pixmap=pixmap)
        fallback_key = (element.image_type or "").strip().casefold()
        if fallback_key and fallback_key != slot_key:
            media_path = _resolve_game_media_path(media_root, base_names, fallback_key)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if slot_key == "logo" and not element.text_fallback:
            child_name = Path(display_entry.rom_path).stem
            child_media_root = _resolve_collection_media_root(self._target_dir(), child_name)
            child_media_path = _find_named_collection_media_file(child_media_root, "logo", IMAGE_MEDIA_SUFFIXES)
            if child_media_path is not None:
                pixmap = QPixmap(str(child_media_path))
                if not pixmap.isNull():
                    return ThemePreviewRenderData(pixmap=pixmap)
        if slot_key == "cabinet":
            collection_render = _resolve_collection_chain_theme_render(
                self,
                element,
                collection_name,
                display_entry.collection_name,
                display_entry.install_collection_name,
                display_entry.source_pack,
            )
            if collection_render is not None and collection_render.pixmap is not None:
                return collection_render
    if element.kind in {"video", "reloadable_video"} and mode_key in {"commonlayout", "common"} and theme_entry is not None:
        effective_slot = slot_key or (element.image_type or "").strip().casefold()
        common_video = _resolve_common_layout_video(self, theme_entry, effective_slot, _common_root_for_mode(self, theme_entry, mode_key))
        if common_video is not None:
            pixmap = _extract_video_thumbnail(common_video)
            if pixmap is not None and not pixmap.isNull():
                return ThemePreviewRenderData(pixmap=pixmap, video_path=common_video)
    if element.kind in {"video", "reloadable_video"}:
        if is_collection_placeholder:
            collection_video = _resolve_collection_theme_render(self, element, display_entry.collection_name)
            if collection_video is not None:
                return collection_video
        video_path = _resolve_game_video_path(media_root, base_names, slot_key)
        if video_path is not None:
            pixmap = _extract_video_thumbnail(video_path)
            if pixmap is not None and not pixmap.isNull():
                return ThemePreviewRenderData(pixmap=pixmap, video_path=video_path)
        fallback_key = (element.image_type or "").strip().casefold() or slot_key
        static_path = _resolve_game_media_path(media_root, base_names, fallback_key)
        if static_path is not None:
            pixmap = QPixmap(str(static_path))
            if not pixmap.isNull():
                return ThemePreviewRenderData(pixmap=pixmap)
    if (
        element.kind == "menu"
        or element.text_fallback
    ) and element.kind in {"image", "reloadable_image", "reloadable_panning_image", "menu"}:
        text_value = _resolve_theme_preview_text(self, element, collection_name, display_entry, collection_games, collection_index)
        if not text_value:
            text_value = display_entry.game_name or None
        if text_value:
            return ThemePreviewRenderData(text=text_value)
    if element.kind in {"text", "reloadable_text", "scrolling_text", "reloadable_scrolling_text"}:
        text_value = _resolve_theme_preview_text(self, element, collection_name, display_entry, collection_games, collection_index)
        if text_value:
            return ThemePreviewRenderData(text=text_value)
    return None


def _theme_menu_entry_for_element(
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


# ---------------------------------------------------------------------------
# Text resolution
# ---------------------------------------------------------------------------

def _resolve_theme_preview_text(
    self: "MainWindow",
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
    hyperlist_metadata = _resolve_theme_game_metadata(self, collection_name, game_entry)
    if slot_key == "title":
        return (hyperlist_metadata.value_for_slot("title") if hyperlist_metadata is not None else None) or Path(game_entry.game_name).stem
    if slot_key == "story":
        base_names = _game_name_candidates(Path(game_entry.rom_path).name)
        media_root = _resolve_theme_game_media_root(self, game_entry)
        story_path = _find_matching_media_file(media_root / "story", base_names, STORY_MEDIA_SUFFIXES) if media_root is not None else None
        if story_path is None:
            return None
        return _read_story_text(story_path)
    if slot_key == "firstletter":
        title_text = (hyperlist_metadata.value_for_slot("title") if hyperlist_metadata is not None else None) or Path(game_entry.game_name).stem
        return title_text[:1].upper() if title_text else None
    if hyperlist_metadata is not None:
        metadata_value = hyperlist_metadata.value_for_slot(slot_key)
        if metadata_value:
            return metadata_value
    if not Path(game_entry.rom_path).suffix and slot_key in {"manufacturer", "year", "genre"}:
        for key, value in read_collection_info_attributes(self._target_dir(), game_entry.collection_name):
            if key.casefold() == slot_key and value:
                return value
    return None


def _resolve_theme_game_metadata(self: "MainWindow", collection_name: str | None, game_entry: GameManifestEntry):
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


# ---------------------------------------------------------------------------
# Common / media helpers
# ---------------------------------------------------------------------------

def _resolve_theme_game_media_root(self: "MainWindow", game_entry: GameManifestEntry) -> Path | None:
    collection_key = game_entry.collection_name.casefold()
    if collection_key in self._media_root_cache:
        return self._media_root_cache[collection_key]
    target = self._target_dir()
    if target is not None:
        for collection_dir in collection_directory_candidates(target, game_entry.collection_name):
            candidate = collection_dir / "medium_artwork"
            if candidate.exists() and candidate.is_dir():
                self._media_root_cache[collection_key] = candidate
                return candidate
    self._media_root_cache[collection_key] = None
    return None


def _common_root_for_mode(self: "MainWindow", theme_entry: ThemeCatalogEntry, mode_key: str) -> Path:
    if mode_key == "common":
        target = self._target_dir()
        if target is not None:
            appdata_common = target / "appdata" / "retrofe" / "collections" / "_common"
            if appdata_common.exists():
                return appdata_common
            base_assets_common = target / "base_assets" / "collections" / "_common"
            if base_assets_common.exists():
                return base_assets_common
            return appdata_common
    return theme_entry.root_dir / "collections" / "_common"


def _common_slot_candidate_names(
    self: "MainWindow",
    slot_key: str,
    game_entry: GameManifestEntry,
    collection_name: str | None,
) -> tuple[str, ...]:
    slot_key = slot_key.casefold()
    if slot_key in {"firstletter", "rightstrip"}:
        letter = Path(game_entry.game_name).stem[:1] or game_entry.game_name[:1]
        return (letter.upper(), letter.lower(), letter)
    if slot_key == "playlist" and collection_name:
        return ("ALL", "all", collection_name)
    if slot_key == "isfavorite":
        return ("yes",)

    if slot_key in {"genre", "manufacturer", "numberplayers", "score"}:
        metadata = _resolve_theme_game_metadata(self, collection_name, game_entry)
        if metadata is not None:
            raw_value = (metadata.value_for_slot(slot_key) or "").strip()
            if raw_value:
                values: list[str] = [raw_value]
                underscored = raw_value.replace("/", "_")
                if underscored not in values:
                    values.append(underscored)
                if slot_key == "genre":
                    compact = raw_value.replace(" / ", "_").replace("/", "_")
                    if compact not in values:
                        values.append(compact)
                return tuple(values)

    return _game_name_candidates(Path(game_entry.rom_path).name)


def _resolve_common_theme_render(
    self: "MainWindow",
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
    candidate_names = _common_slot_candidate_names(self, slot_key, game_entry, collection_name)
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


def _resolve_common_layout_video(self: "MainWindow", theme_entry: ThemeCatalogEntry, slot_key: str, common_root: Path | None = None) -> Path | None:
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


# ---------------------------------------------------------------------------
# Video session management
# ---------------------------------------------------------------------------

def _sync_theme_preview_video_sessions(self: "MainWindow") -> None:
    desired = {
        element: data
        for element, data in self._theme_preview_render_data.items()
        if data.video_path is not None
    }
    stale_elements = [element for element in self._theme_preview_video_sessions if element not in desired]
    for element in stale_elements:
        _dispose_theme_preview_video_session(self, element)

    if not (HAS_QT_MULTIMEDIA and QMediaPlayer is not None and QAudioOutput is not None and QVideoSink is not None):
        return

    for element, data in desired.items():
        session = self._theme_preview_video_sessions.get(element)
        if session is not None and session.video_path == data.video_path:
            _apply_theme_preview_session_state(self, session)
            continue
        if session is not None:
            _dispose_theme_preview_video_session(self, element)
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
            lambda frame, current_element=element: _handle_theme_preview_video_frame(self, current_element, frame)
        )
        player.mediaStatusChanged.connect(
            lambda status, current_element=element: _handle_theme_preview_video_status_changed(self, current_element, status)
        )
        session = ThemePreviewVideoSession(
            element=element,
            video_path=video_path,
            player=player,
            audio_output=audio_output,
            video_sink=video_sink,
            created_at_ms=time.monotonic() * 1000.0,
        )
        self._theme_preview_video_sessions[element] = session
        _apply_theme_preview_session_state(self, session)


def _dispose_theme_preview_video_session(self: "MainWindow", element: ThemePreviewElement) -> None:
    session = self._theme_preview_video_sessions.pop(element, None)
    if session is None:
        return
    try:
        session.player.stop()
    except Exception:
        pass
    try:
        session.player.setSource(QUrl())
    except Exception:
        pass
    try:
        session.player.setVideoOutput(None)
    except Exception:
        pass
    try:
        session.player.setAudioOutput(None)
    except Exception:
        pass
    session.player.deleteLater()
    session.audio_output.deleteLater()
    session.video_sink.deleteLater()


def dispose_all_theme_preview_video_sessions(self: "MainWindow") -> None:
    for element in list(self._theme_preview_video_sessions.keys()):
        _dispose_theme_preview_video_session(self, element)


def _apply_theme_preview_session_state(self: "MainWindow", session: ThemePreviewVideoSession) -> None:
    session.audio_output.setMuted(self._theme_preview_muted)
    should_play = self._theme_preview_animation_enabled
    if should_play:
        session.player.play()
    else:
        session.player.pause()


def _handle_theme_preview_video_frame(self: "MainWindow", element: ThemePreviewElement, frame) -> None:
    if element not in self._theme_preview_render_data:
        return
    pixmap = _theme_preview_pixmap_from_frame(frame)
    if pixmap is None or pixmap.isNull():
        return
    session = self._theme_preview_video_sessions.get(element)
    if session is not None and not session.accepted_live_frame:
        elapsed_ms = (time.monotonic() * 1000.0) - session.created_at_ms
        position_ms = 0.0
        try:
            if session.player is not None and hasattr(session.player, "position"):
                position_ms = float(session.player.position())
        except Exception:
            position_ms = 0.0
        startup_window_active = elapsed_ms < 1200.0 or position_ms < 500.0
        if startup_window_active and _theme_preview_pixmap_looks_blank(pixmap):
            return
        if session.primed_live_frame is None:
            session.primed_live_frame = pixmap
            return
        session.accepted_live_frame = True
        session.primed_live_frame = None
    current = self._theme_preview_render_data.get(element)
    if current is None:
        return
    self._theme_preview_render_data[element] = replace(current, pixmap=pixmap)
    self._theme_video_dirty = True


def flush_theme_video_repaint(self: "MainWindow") -> None:
    if self._theme_video_dirty:
        self._theme_video_dirty = False
        self.themes_preview.set_render_data(self._theme_preview_render_data)


def _handle_theme_preview_video_status_changed(self: "MainWindow", element: ThemePreviewElement, status) -> None:
    session = self._theme_preview_video_sessions.get(element)
    if session is None:
        return
    if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) and not session.initial_seek_done:
        session.initial_seek_done = True
    elif status == QMediaPlayer.MediaStatus.EndOfMedia:
        session.player.setPosition(0)
        if self._theme_preview_animation_enabled:
            session.player.play()


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


def _theme_preview_pixmap_looks_blank(pixmap: QPixmap) -> bool:
    if pixmap.isNull():
        return True
    image = pixmap.toImage()
    if image.isNull():
        return True
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return True
    sample_cols = min(8, width)
    sample_rows = min(8, height)
    total_luma = 0.0
    max_channel = 0
    sample_count = 0
    for row in range(sample_rows):
        y = min(height - 1, int((row + 0.5) * height / sample_rows))
        for col in range(sample_cols):
            x = min(width - 1, int((col + 0.5) * width / sample_cols))
            color = image.pixelColor(x, y)
            r = color.red()
            g = color.green()
            b = color.blue()
            total_luma += (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
            max_channel = max(max_channel, r, g, b)
            sample_count += 1
    if sample_count <= 0:
        return True
    avg_luma = total_luma / sample_count
    return avg_luma < 10.0 and max_channel < 32


# ---------------------------------------------------------------------------
# Animation / wheel controls
# ---------------------------------------------------------------------------

def _handle_theme_preview_scroll_index_changed(self: "MainWindow", target_zero_index: int) -> None:
    preview = self._theme_preview
    if preview is None or not self._theme_preview_wheel_spinning:
        return
    preview_widget = getattr(self, "themes_preview", None)
    if (
        preview_widget is not None
        and preview_widget._wheel_anim_pending_finish
        and target_zero_index
        == (
            preview_widget._wheel_anim_start_game_0
            + preview_widget._wheel_anim_advance_count
        )
        % max(1, preview_widget._wheel_anim_total_games)
    ):
        selected_collection = preview.selected_collection or self._selected_theme_collection_name or ""
        collection_games = _theme_games_for_collection(self, selected_collection)
        if collection_games:
            resolved_zero_index = target_zero_index % len(collection_games)
            self._theme_preview_promoted_final_zero_index = resolved_zero_index
            return
    scroll_data = _build_theme_scroll_render_data(self, preview, target_zero_index)
    merged = {
        element: data
        for element, data in self._theme_preview_render_data.items()
        if not element.menu_scroll_reload
    }
    merged.update(scroll_data)
    _set_theme_preview_render_data(self, merged, transition=False)


def _start_wheel_animation(self: "MainWindow", advance_count: int, *, target_offset: int | None = None) -> None:
    preview = self._theme_preview
    if preview is None:
        return
    selected_collection = preview.selected_collection or self._selected_theme_collection_name or ""
    collection_games = _theme_games_for_collection(self, selected_collection)
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
    start_game_0 = _theme_game_zero_index_from_combo_index(self, current_combo_index)
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
            media_root = _resolve_theme_game_media_root(self, game_entry)
            if mode_key in {"commonlayout", "common"} and theme_entry is not None:
                common_render = _resolve_common_theme_render(self, theme_entry, slot_key, game_entry, selected_collection or None, _common_root_for_mode(self, theme_entry, mode_key))
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
            media_path = _resolve_game_media_path(media_root, base_names, slot_key)
            if media_path is not None:
                pixmap = QPixmap(str(media_path))
                if not pixmap.isNull():
                    pixmaps[game_0] = pixmap
                    continue
            if slot_key == "logo" and not ref_element.text_fallback and not Path(game_entry.rom_path).suffix:
                child_name = Path(game_entry.rom_path).stem
                child_media_root = _resolve_collection_media_root(self._target_dir(), child_name)
                child_media_path = _find_named_collection_media_file(child_media_root, "logo", IMAGE_MEDIA_SUFFIXES)
                if child_media_path is not None:
                    pixmap = QPixmap(str(child_media_path))
                    if not pixmap.isNull():
                        pixmaps[game_0] = pixmap
                        continue
            if game_0 not in pixmaps and (ref_element.text_fallback or ref_element.kind == "menu"):
                item_text = game_entry.game_name
                text_fmt = (ref_element.text_format or "").casefold()
                if text_fmt == "uppercase":
                    item_text = item_text.upper()
                text_pix = _make_wheel_text_pixmap(self, item_text, ref_element)
                if text_pix is not None and not text_pix.isNull():
                    pixmaps[game_0] = text_pix
        built_groups.append((slot_elements, pixmaps, sel_idx))
    if not built_groups:
        return
    effective_target = target_offset if target_offset is not None else advance_count
    duration_ms = max(250, int(advance_count / 4.0 * 1000))
    self._theme_preview_wheel_spinning = True
    for session in self._theme_preview_video_sessions.values():
        _apply_theme_preview_session_state(self, session)
    primary_elements, primary_pixmaps, primary_sel_idx = built_groups[0]
    extra_groups = built_groups[1:]
    self.themes_preview.start_wheel_animation(
        primary_elements, primary_pixmaps, primary_sel_idx, start_game_0, advance_count, total_games, duration_ms,
        target_advance=effective_target,
        extra_groups=extra_groups,
    )


def _on_wheel_animation_finished(self: "MainWindow") -> None:
    self._theme_preview_wheel_spinning = False
    for session in self._theme_preview_video_sessions.values():
        _apply_theme_preview_session_state(self, session)
    total_games = self.themes_preview._wheel_anim_total_games
    start_game_0 = self.themes_preview._wheel_anim_start_game_0
    target_advance = self.themes_preview._wheel_anim_target_advance
    target_game_0 = (start_game_0 + target_advance) % total_games
    combo_index = _theme_game_combo_index_from_zero_index(self, target_game_0)
    if combo_index < self.themes_game_filter.count():
        self.themes_game_filter.blockSignals(True)
        self.themes_game_filter.setCurrentIndex(combo_index)
        self.themes_game_filter.blockSignals(False)
        current_entry = self.themes_game_filter.currentData()
        self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
        self._theme_preview_previous_stopped_game_key = self._theme_preview_last_stopped_game_key
        self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
        self._theme_preview_promoted_final_zero_index = None
        self._theme_preview_pending_settled_render = _theme_preview_should_preserve_scroll_tail(self)
        if not self._theme_preview_pending_settled_render:
            _set_theme_preview_render_data(self, _build_theme_render_data(self, self._theme_preview), transition=False)
    self.themes_preview.stop_wheel_animation(preserve_scroll_tail=self._theme_preview_pending_settled_render)
    _schedule_theme_preview_cycle(self)


def _on_theme_preview_scroll_fade_finished(self: "MainWindow") -> None:
    if not self._theme_preview_pending_settled_render:
        return
    self._theme_preview_pending_settled_render = False
    if self._theme_preview is None:
        return
    _set_theme_preview_render_data(self, _build_theme_render_data(self, self._theme_preview), transition=False)


def _theme_preview_should_preserve_scroll_tail(self: "MainWindow") -> bool:
    preview = self._theme_preview
    if preview is None:
        return False
    menu_groups = 0
    current_group_open = False
    hidden_selected_slot = False
    for element in preview.elements:
        if element.kind == "menu":
            if not current_group_open:
                menu_groups += 1
                current_group_open = True
            if element.selected and (element.alpha if element.alpha is not None else 1.0) <= 0.0:
                hidden_selected_slot = True
        else:
            current_group_open = False
    return hidden_selected_slot or menu_groups > 1


def _handle_theme_preview_previous_requested(self: "MainWindow") -> None:
    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    game_entries = _theme_games_for_collection(self, selected_collection)
    if not game_entries:
        return
    if self._theme_preview_animation_enabled:
        target_key = self._theme_preview_previous_stopped_game_key
        if target_key is None:
            current_index = _theme_game_zero_index_from_combo_index(self, self.themes_game_filter.currentIndex())
            target_zero_index = (current_index - 1) % len(game_entries)
        else:
            target_zero_index = next((idx for idx, entry in enumerate(game_entries) if entry.key == target_key), 0)
        _jump_theme_preview_to_index(self, target_zero_index)
        return
    current_index = _theme_game_zero_index_from_combo_index(self, self.themes_game_filter.currentIndex())
    target_zero_index = (current_index - 1) % len(game_entries)
    _jump_theme_preview_to_index(self, target_zero_index)


def _handle_theme_preview_next_requested(self: "MainWindow") -> None:
    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    game_entries = _theme_games_for_collection(self, selected_collection)
    if not game_entries:
        return
    if self._theme_preview_animation_enabled:
        _trigger_theme_preview_random_advance(self)
        return
    current_index = _theme_game_zero_index_from_combo_index(self, self.themes_game_filter.currentIndex())
    target_zero_index = (current_index + 1) % len(game_entries)
    _jump_theme_preview_to_index(self, target_zero_index)


def _jump_theme_preview_to_index(self: "MainWindow", zero_index: int) -> None:
    combo_index = _theme_game_combo_index_from_zero_index(self, zero_index)
    if combo_index < 0 or combo_index >= self.themes_game_filter.count():
        return
    self._theme_preview_pending_indices.clear()
    self._theme_preview_cycle_timer.stop()
    self._theme_preview_scroll_timer.stop()
    self._theme_preview_wheel_spinning = False
    self._theme_preview_pending_settled_render = False
    self.themes_preview.stop_wheel_animation()
    self.themes_game_filter.setCurrentIndex(combo_index)
    current_entry = self.themes_game_filter.currentData()
    self._selected_theme_game_key = current_entry.key if isinstance(current_entry, GameManifestEntry) else None
    self._theme_preview_previous_stopped_game_key = self._theme_preview_last_stopped_game_key
    self._theme_preview_last_stopped_game_key = self._selected_theme_game_key
    _refresh_theme_preview_render_only(self)
    if self._theme_preview_animation_enabled:
        _schedule_theme_preview_cycle(self)


def _trigger_theme_preview_random_advance(self: "MainWindow") -> None:
    if self._theme_preview is None or self._theme_preview_wheel_spinning:
        return
    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    game_entries = _theme_games_for_collection(self, selected_collection)
    total_games = len(game_entries)
    if total_games <= 1:
        return
    self._theme_preview_cycle_timer.stop()
    advance_count = random.randint(1, min(max(20, total_games // 10), total_games - 1))
    slot_elements = [e for e in self._theme_preview.elements if e.kind == "menu"]
    if slot_elements:
        visible_advance = min(advance_count, 20)
        _start_wheel_animation(self, visible_advance)
        return
    current_index = _theme_game_zero_index_from_combo_index(self, self.themes_game_filter.currentIndex())
    target_zero_index = (current_index + advance_count) % total_games
    _jump_theme_preview_to_index(self, target_zero_index)


def _toggle_theme_preview_animation(self: "MainWindow") -> None:
    self._theme_preview_animation_enabled = not self._theme_preview_animation_enabled
    if self._theme_preview_animation_enabled:
        _start_theme_preview_animation(self)
    else:
        _stop_theme_preview_animation(self)
    _sync_theme_preview_animation_controls(self)


def _toggle_theme_preview_mute(self: "MainWindow") -> None:
    self._theme_preview_muted = not self._theme_preview_muted
    for session in self._theme_preview_video_sessions.values():
        session.audio_output.setMuted(self._theme_preview_muted)
    _sync_theme_preview_animation_controls(self)


def _start_theme_preview_animation(self: "MainWindow") -> None:
    _sync_theme_preview_video_sessions(self)
    for session in self._theme_preview_video_sessions.values():
        _apply_theme_preview_session_state(self, session)
    self._theme_video_repaint_timer.start()
    _schedule_theme_preview_cycle(self)


def _stop_theme_preview_animation(self: "MainWindow") -> None:
    self._theme_preview_cycle_timer.stop()
    self._theme_preview_scroll_timer.stop()
    self._theme_video_repaint_timer.stop()
    self._theme_video_dirty = False
    self._theme_preview_wheel_spinning = False
    self._theme_preview_pending_indices.clear()
    self.themes_preview.stop_wheel_animation()
    for session in self._theme_preview_video_sessions.values():
        _apply_theme_preview_session_state(self, session)


def _sync_theme_preview_animation_controls(self: "MainWindow") -> None:
    has_preview = self._theme_preview is not None
    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    can_animate_wheel = bool(selected_collection and _theme_games_for_collection(self, selected_collection))
    has_video = bool(self._theme_preview_video_sessions) or any(data.video_path is not None for data in self._theme_preview_render_data.values())
    if not has_preview and self._theme_preview_animation_enabled:
        self._theme_preview_animation_enabled = False
        _stop_theme_preview_animation(self)
    self.themes_preview.set_animation_controls(
        can_play=has_preview and (can_animate_wheel or has_video),
        can_mute=has_video,
        is_playing=self._theme_preview_animation_enabled,
        is_muted=self._theme_preview_muted,
    )


def _theme_preview_wait_interval_ms(self: "MainWindow") -> int:
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
    return max(base_wait_ms, int((max_scroll_start * 1000.0) + 2000.0))


def _schedule_theme_preview_cycle(self: "MainWindow") -> None:
    self._theme_preview_cycle_timer.stop()
    self.themes_preview._transition_duration_ms = 400
    if not self._theme_preview_animation_enabled:
        return
    self._theme_preview_cycle_timer.start(_theme_preview_wait_interval_ms(self))


def _advance_theme_preview_attract_mode(self: "MainWindow") -> None:
    if not self._theme_preview_animation_enabled or self._theme_preview is None:
        return
    selected_collection = self._selected_theme_collection_name or str(self.themes_collection_filter.currentData() or "")
    game_entries = _theme_games_for_collection(self, selected_collection)
    if not game_entries:
        _schedule_theme_preview_cycle(self)
        return
    if _themes_game_filter_has_placeholder(self) and self.themes_game_filter.count() > 1:
        self.themes_game_filter.setCurrentIndex(1)
        self._selected_theme_game_key = self.themes_game_filter.currentData().key if isinstance(self.themes_game_filter.currentData(), GameManifestEntry) else None
        game_entries = _theme_games_for_collection(self, selected_collection)
    current_index = _theme_game_zero_index_from_combo_index(self, self.themes_game_filter.currentIndex())
    total_games = len(game_entries)
    if total_games <= 1:
        _schedule_theme_preview_cycle(self)
        return
    advance_count = random.randint(1, min(max(20, total_games // 10), total_games - 1))
    slot_elements = [e for e in self._theme_preview.elements if e.kind == "menu" and (e.slot_name or "").casefold() == "logo"]
    if slot_elements:
        visible_advance = min(advance_count, 20)
        _start_wheel_animation(self, visible_advance)
    else:
        target_index = (current_index + advance_count) % total_games
        combo_index = _theme_game_combo_index_from_zero_index(self, target_index)
        self.themes_preview._transition_duration_ms = max(250, int(advance_count / 4.0 * 1000))
        if combo_index < self.themes_game_filter.count():
            self.themes_game_filter.setCurrentIndex(combo_index)
        _schedule_theme_preview_cycle(self)


def _make_wheel_text_pixmap(self: "MainWindow", text: str, ref_element: ThemePreviewElement) -> QPixmap | None:
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


# ---------------------------------------------------------------------------
# Standalone media / file helpers
# ---------------------------------------------------------------------------

def _game_name_candidates(rom_name: str) -> tuple[str, ...]:
    path = Path(rom_name)
    candidates: list[str] = []
    pending = [path.name]
    while pending:
        current = pending.pop(0)
        if not current or current in candidates:
            continue
        candidates.append(current)
        stem = Path(current).stem
        if stem != current:
            pending.append(stem)
        stripped = _strip_media_name_suffixes(stem)
        if stripped and stripped not in {current, stem}:
            pending.append(stripped)
    return tuple(candidates)


def _strip_media_name_suffixes(value: str) -> str:
    current = value.strip()
    while True:
        updated = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", current).strip()
        if updated == current:
            return updated
        current = updated


def _find_matching_media_file(directory: Path, base_names: tuple[str, ...], allowed_suffixes: set[str] | None = None) -> Path | None:
    if not directory.exists() or not directory.is_dir():
        return None
    candidate_keys = {name.casefold() for name in base_names}
    nested_dirs: list[Path] = []
    for name in base_names:
        nested_dir = directory / Path(name).stem
        if nested_dir.exists() and nested_dir.is_dir() and nested_dir not in nested_dirs:
            nested_dirs.append(nested_dir)
    search_dirs: list[Path] = nested_dirs + [directory]
    for search_dir in search_dirs:
        fallback: Path | None = None
        for path in search_dir.iterdir():
            if not path.is_file():
                continue
            if allowed_suffixes is not None and path.suffix.casefold() not in allowed_suffixes:
                continue
            if not _media_path_matches(path, candidate_keys):
                continue
            if path.stem.casefold() in candidate_keys:
                return path
            if fallback is None:
                fallback = path
        if fallback is not None:
            return fallback
        if search_dir in nested_dirs:
            for path in sorted(search_dir.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_file():
                    continue
                if allowed_suffixes is not None and path.suffix.casefold() not in allowed_suffixes:
                    continue
                return path
    if allowed_suffixes is not None:
        for default_name in ("default.jpg", "default.jpeg", "default.png"):
            if Path(default_name).suffix.casefold() not in allowed_suffixes:
                continue
            default_path = directory / default_name
            if default_path.is_file():
                return default_path
    return None


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
    for path in sorted(media_root.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_file() and path.suffix.casefold() in VIDEO_MEDIA_SUFFIXES:
            return path
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
        return sorted(marquee_ready, key=lambda item: item.name.casefold(), reverse=True) + files
    return files


def _resolve_game_media_path(media_root: Path | None, base_names: tuple[str, ...], slot_key: str) -> Path | None:
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
        "cabinet": ("cabinet",),
    }.get(slot_key, (slot_key,))
    for folder_name in folder_candidates:
        media_path = _find_matching_media_file(media_root / folder_name, base_names, IMAGE_MEDIA_SUFFIXES)
        if media_path is not None:
            return media_path
    return None


def _resolve_game_video_path(media_root: Path | None, base_names: tuple[str, ...], slot_key: str) -> Path | None:
    if media_root is None:
        return None
    return _find_matching_media_file(media_root / "video", base_names, VIDEO_MEDIA_SUFFIXES)


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


def _video_thumbnail_offsets(video_path: Path) -> list[str]:
    return ["00:00:02", "00:00:01", "00:00:00"]


def _run_ffmpeg_thumbnail_extract(ffmpeg_path: str, video_path: Path, offset: str) -> QPixmap | None:
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-ss", offset,
                "-i", str(video_path),
                "-frames:v", "1",
                "-f", "image2pipe",
                "-vcodec", "png",
                "-",
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        image = QImage()
        if not image.loadFromData(result.stdout):
            return None
        pixmap = QPixmap.fromImage(image)
        return None if pixmap.isNull() else pixmap
    except (subprocess.TimeoutExpired, OSError):
        return None
