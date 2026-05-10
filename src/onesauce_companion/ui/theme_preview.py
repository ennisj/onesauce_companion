"""Theme layout preview widget and supporting dataclasses.

Ported from the themeplay branch's monolithic main_window.py (lines 219-249
and 2371-4776) into a standalone module for the refactored screen architecture.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRawFont,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from onesauce_companion.ui._utils import _assets_dir

if TYPE_CHECKING:
    from onesauce_companion.services.themes import (
        ThemeLayoutPreview,
        ThemePreviewElement,
    )


# ---------------------------------------------------------------------------
# Supporting dataclasses
# ---------------------------------------------------------------------------

@dataclass
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
    created_at_ms: float = 0.0
    accepted_live_frame: bool = False
    primed_live_frame: QPixmap | None = None


# ---------------------------------------------------------------------------
# ThemeLayoutPreviewWidget
# ---------------------------------------------------------------------------

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
    scrollFadeFinished = Signal()

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
        self._wheel_anim_pending_finish: bool = False
        self._wheel_anim_last_scroll_pos: float = 0.0
        self._wheel_anim_timer = QTimer(self)
        self._wheel_anim_timer.setInterval(16)
        self._wheel_anim_timer.timeout.connect(self._on_wheel_anim_tick)
        self._scroll_anim_opacity: float = 1.0
        self._scroll_fading_out: bool = False
        self._scroll_fade_start_ms: float = 0.0
        self._scroll_fade_duration_ms: int = 1200
        self._pending_highlight_restore: bool = False
        self._scroll_fade_timer = QTimer(self)
        self._scroll_fade_timer.setInterval(16)
        self._scroll_fade_timer.timeout.connect(self._on_scroll_fade_tick)
        self._idle_anim_timer = QTimer(self)
        self._idle_anim_timer.setInterval(16)
        self._idle_anim_timer.timeout.connect(self._on_idle_anim_tick)
        self._idle_anim_start_ms: float = 0.0
        self._idle_anim_alphas: dict[ThemePreviewElement, float] = {}
        self._idle_anim_values: dict[ThemePreviewElement, dict[str, float]] = {}
        self._idle_anim_seed_values: dict[ThemePreviewElement, dict[str, float]] = {}
        self._idle_anim_loop_values: dict[ThemePreviewElement, tuple[int, dict[str, float]]] = {}
        self._event_anim_timer = QTimer(self)
        self._event_anim_timer.setInterval(16)
        self._event_anim_timer.timeout.connect(self._on_event_anim_tick)
        self._event_anim_name: str | None = None
        self._event_anim_start_ms: float = 0.0
        self._event_anim_values: dict[ThemePreviewElement, dict[str, float]] = {}
        self._pending_event_animation: str | None = None
        self._resume_idle_after_transition: bool = False
        self._pulsing_overlay_elements: frozenset[ThemePreviewElement] = frozenset()
        self._covered_selected_menu_elements: frozenset[ThemePreviewElement] = frozenset()
        self._pulsing_overlay_targets: dict[ThemePreviewElement, ThemePreviewElement] = {}
        self._cached_ordered_elements: list[ThemePreviewElement] | None = None
        self._floating_canvas_pixmap: QPixmap | None = None
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        self._cached_ordered_elements = None
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
        self._wheel_anim_pending_finish = False
        self._wheel_anim_last_scroll_pos = 0.0
        self._scroll_fade_timer.stop()
        self._scroll_fading_out = False
        self._scroll_anim_opacity = 1.0
        self._wheel_anim_active = True
        self._start_event_animation("menuscroll")
        self._stop_idle_animation(clear_values=False)
        self._wheel_anim_timer.start()

    def stop_wheel_animation(self, *, preserve_scroll_tail: bool = False) -> None:
        if self._wheel_anim_active:
            self._wheel_anim_active = False
            self._wheel_anim_timer.stop()
        if not preserve_scroll_tail:
            self._scroll_fade_timer.stop()
            self._scroll_fading_out = False
            self._scroll_anim_opacity = 1.0
            self._wheel_anim_extra_groups = []
            self._wheel_anim_last_scroll_pos = 0.0
            self._pending_highlight_restore = False
        else:
            self._pending_highlight_restore = True
        self._wheel_anim_last_emitted_index = None
        self._wheel_anim_pending_finish = False
        self._stop_event_animation()
        # Restart idle animation immediately so authored onMenuIdle fades (for example
        # Fan Art Magazine's firstLetter / shadow / top_grad) can begin while the final
        # scroll tail fades out. highlightenter is still delayed when preserving the tail.
        preview = self._preview
        if preview is not None and self._animation_enabled and any(e.idle_anim_sets for e in preview.elements):
            self._restart_idle_animation()
        if not preserve_scroll_tail:
            if self._has_matching_event_animation("menuexit"):
                if self._has_matching_event_animation("highlightenter"):
                    self._pending_event_animation = "highlightenter"
                self._start_event_animation("menuexit")
            else:
                self._start_event_animation("highlightenter")
        self.update()

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

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Wheel animation
    # ------------------------------------------------------------------

    def _on_wheel_anim_tick(self) -> None:
        elapsed = time.monotonic() * 1000.0 - self._wheel_anim_start_ms
        if elapsed >= self._wheel_anim_duration_ms:
            if not self._wheel_anim_pending_finish:
                self._wheel_anim_pending_finish = True
                self._wheel_anim_start_ms = (time.monotonic() * 1000.0) - self._wheel_anim_duration_ms
                self._wheel_anim_last_scroll_pos = float(self._wheel_anim_advance_count)
                target_index = (
                    self._wheel_anim_start_game_0 + self._wheel_anim_advance_count
                ) % max(1, self._wheel_anim_total_games)
                if target_index != self._wheel_anim_last_emitted_index:
                    self._wheel_anim_last_emitted_index = target_index
                    self.wheelAnimationIndexChanged.emit(target_index)
                if self._expanded:
                    self._request_floating_preview_update(animation=True)
                self.update()
                QTimer.singleShot(0, self._complete_wheel_animation)
            return
        t = min(1.0, elapsed / self._wheel_anim_duration_ms)
        eased = 1.0 - (1.0 - t) ** 1.3
        current_index = (self._wheel_anim_start_game_0 + int(eased * self._wheel_anim_advance_count)) % max(1, self._wheel_anim_total_games)
        self._wheel_anim_last_scroll_pos = eased * self._wheel_anim_advance_count
        # Emit only when the currently highlighted scroll item changes.
        if current_index != self._wheel_anim_last_emitted_index:
            self._wheel_anim_last_emitted_index = current_index
            self.wheelAnimationIndexChanged.emit(current_index)
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    def _complete_wheel_animation(self) -> None:
        if not self._wheel_anim_pending_finish:
            return
        self._wheel_anim_pending_finish = False
        self._wheel_anim_active = False
        self._wheel_anim_timer.stop()
        self._scroll_fading_out = True
        self._scroll_fade_start_ms = time.monotonic() * 1000.0
        self._scroll_fade_timer.start()
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()
        self.wheelAnimationFinished.emit()

    def _on_scroll_fade_tick(self) -> None:
        elapsed = time.monotonic() * 1000.0 - self._scroll_fade_start_ms
        self._scroll_anim_opacity = max(0.0, 1.0 - elapsed / self._scroll_fade_duration_ms)
        if self._scroll_anim_opacity <= 0.0:
            self._scroll_fade_timer.stop()
            self._scroll_fading_out = False
            self._wheel_anim_extra_groups = []
            self._wheel_anim_last_scroll_pos = 0.0
            self.scrollFadeFinished.emit()
            if self._pending_highlight_restore:
                self._pending_highlight_restore = False
                self._start_event_animation("highlightenter")
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    # ------------------------------------------------------------------
    # Idle animation
    # ------------------------------------------------------------------

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
            animated_props = self._animated_props_from_sets(element.idle_anim_sets)
            if not animated_props:
                continue
            total_ms = sum(s[0] for s in element.idle_anim_sets) * 1000.0
            if total_ms <= 0:
                continue
            loop_index = int(elapsed_ms // total_ms) if total_ms > 0 else 0
            t_secs = (elapsed_ms % total_ms) / 1000.0
            cursor = 0.0
            current_values: dict[str, float] = {
                "alpha": element.alpha if element.alpha is not None else 1.0,
                "width": element.width,
                "height": element.height,
                "x": element.x,
                "y": element.y,
            }
            if element.anchor_x is not None:
                current_values["xoffset"] = element.anchor_x
            if element.anchor_y is not None:
                current_values["yoffset"] = element.anchor_y
            if element.max_width is not None:
                current_values["maxwidth"] = element.max_width
            if element.max_height is not None:
                current_values["maxheight"] = element.max_height
            seed_values = self._idle_anim_seed_values.get(element)
            if seed_values:
                current_values.update(seed_values)
            if loop_index > 0:
                cached_loop = self._idle_anim_loop_values.get(element)
                cached_index = 0
                if cached_loop is not None:
                    cached_index, cached_values = cached_loop
                    if cached_index > loop_index:
                        cached_index = 0
                    else:
                        current_values.update(cached_values)
                while cached_index < loop_index:
                    current_values = self._advance_idle_animation_full_cycle(current_values, element.idle_anim_sets)
                    cached_index += 1
                self._idle_anim_loop_values[element] = (cached_index, dict(current_values))
            if self._event_anim_name:
                event_values = self._event_anim_values.get(element)
                if event_values:
                    current_values.update(event_values)
            for duration, steps in element.idle_anim_sets:
                if t_secs < cursor + duration:
                    set_t = (t_secs - cursor) / duration if duration > 0 else 1.0
                    for prop, from_val, to_val, algorithm in steps:
                        start_val = from_val if from_val is not None else current_values.get(prop, to_val)
                        eased_t = self._idle_animation_progress(set_t, algorithm)
                        current_values[prop] = start_val + (to_val - start_val) * eased_t
                    break
                for prop, _, to_val, _ in steps:
                    current_values[prop] = to_val
                cursor += duration
            else:
                # Past all sets: use final value of the last step per property
                last_steps = element.idle_anim_sets[-1][1]
                for prop, _, to_val, _ in last_steps:
                    current_values[prop] = to_val
            new_values[element] = {
                prop: value
                for prop, value in current_values.items()
                if prop in animated_props
            }
            new_alphas[element] = current_values.get("alpha", 1.0)
        self._idle_anim_alphas = new_alphas
        self._idle_anim_values = new_values
        if self._expanded:
            # Idle pulses are slow continuous animations -- 50ms (20fps) is indistinguishable
            # from 33ms at the expanded scale, and halves the number of expensive offscreen
            # renders per second.  Wheel/scroll/event animations still use animation=True
            # (33ms) for smooth motion.
            self._request_floating_preview_update(animation=False)
        self.update()

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
            self._idle_anim_seed_values = {}
            self._idle_anim_loop_values = {}
        self._resume_idle_after_transition = False

    def _restart_idle_animation(self) -> None:
        if not self._animation_enabled or not self._has_idle_animation():
            self._stop_idle_animation()
            return
        preview = self._preview
        seed_values: dict[ThemePreviewElement, dict[str, float]] = {}
        if preview is not None:
            for element in preview.elements:
                if not element.idle_anim_sets:
                    continue
                current_values: dict[str, float] = {
                    "alpha": element.alpha if element.alpha is not None else 1.0,
                    "width": element.width,
                    "height": element.height,
                    "x": element.x,
                    "y": element.y,
                }
                if element.anchor_x is not None:
                    current_values["xoffset"] = element.anchor_x
                if element.anchor_y is not None:
                    current_values["yoffset"] = element.anchor_y
                if element.max_width is not None:
                    current_values["maxwidth"] = element.max_width
                if element.max_height is not None:
                    current_values["maxheight"] = element.max_height
                prior_idle_values = self._idle_anim_values.get(element)
                if prior_idle_values:
                    current_values.update(prior_idle_values)
                prior_event_values = self._event_anim_values.get(element)
                if prior_event_values:
                    current_values.update(prior_event_values)
                seed_values[element] = current_values
        self._idle_anim_seed_values = seed_values
        self._idle_anim_loop_values = {}
        self._idle_anim_alphas = {}
        self._idle_anim_values = {}
        self._idle_anim_start_ms = time.monotonic() * 1000.0
        self._on_idle_anim_tick()
        if not self._idle_anim_timer.isActive():
            self._idle_anim_timer.start()

    # ------------------------------------------------------------------
    # Event animation
    # ------------------------------------------------------------------

    def _start_event_animation(self, event_name: str) -> None:
        preview = self._preview
        if preview is None or not self._animation_enabled:
            self._stop_event_animation()
            return
        normalized = event_name.casefold()
        if not self._has_matching_event_animation(normalized):
            self._stop_event_animation()
            return
        self._event_anim_name = normalized
        self._event_anim_start_ms = time.monotonic() * 1000.0
        self._event_anim_values = {}
        self._on_event_anim_tick()
        if not self._event_anim_timer.isActive():
            self._event_anim_timer.start()

    def _stop_event_animation(self, *, clear_pending: bool = True) -> None:
        self._event_anim_timer.stop()
        self._event_anim_name = None
        self._event_anim_values = {}
        if clear_pending:
            self._pending_event_animation = None

    def _has_matching_event_animation(self, event_name: str) -> bool:
        preview = self._preview
        if preview is None:
            return False
        normalized = event_name.casefold()
        for element in preview.elements:
            for candidate_name, menu_index_expr, sets in element.event_anim_sets:
                if candidate_name != normalized:
                    continue
                if not self._transient_event_matches_preview_state(candidate_name, menu_index_expr, element):
                    continue
                if sets:
                    return True
        return False

    def _transient_event_matches_preview_state(
        self,
        event_name: str,
        expression: str | None,
        element: ThemePreviewElement,
    ) -> bool:
        normalized = event_name.casefold()
        if normalized == "menuexit" and not (expression or "").strip():
            if (
                element.kind == "menu"
                and not element.selected
                and element.menu_position is not None
                and element.menu_selected_position is not None
            ):
                return abs(element.menu_position - element.menu_selected_position) > 1
            return False
        return self._menu_index_matches_preview_state(expression, element)

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
                if not self._transient_event_matches_preview_state(candidate_name, menu_index_expr, element):
                    continue
                matching_sets = sets
                break
            if not matching_sets:
                continue
            animated_props = self._animated_props_from_sets(matching_sets)
            if not animated_props:
                continue
            total_ms = sum(duration for duration, _ in matching_sets) * 1000.0
            current_values: dict[str, float] = {
                "alpha": element.alpha if element.alpha is not None else 1.0,
                "width": element.width,
                "height": element.height,
                "x": element.x,
                "y": element.y,
            }
            if element.anchor_x is not None:
                current_values["xoffset"] = element.anchor_x
            if element.anchor_y is not None:
                current_values["yoffset"] = element.anchor_y
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
            new_values[element] = {
                prop: value
                for prop, value in current_values.items()
                if prop in animated_props
            }
        self._event_anim_values = new_values
        if not any_active:
            self._event_anim_timer.stop()
            self._event_anim_name = None
            next_event = self._pending_event_animation
            self._pending_event_animation = None
            if next_event:
                self._start_event_animation(next_event)
                return
        if self._expanded:
            self._request_floating_preview_update(animation=True)
        self.update()

    # ------------------------------------------------------------------
    # Animation helpers
    # ------------------------------------------------------------------

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

    @staticmethod
    def _advance_idle_animation_full_cycle(
        current_values: dict[str, float],
        idle_anim_sets: tuple[tuple[float, tuple[tuple[str, float | None, float, str], ...]], ...],
    ) -> dict[str, float]:
        advanced = dict(current_values)
        for _, steps in idle_anim_sets:
            for prop, _, to_val, _ in steps:
                advanced[prop] = to_val
        return advanced

    @staticmethod
    def _animated_props_from_sets(
        anim_sets: tuple[tuple[float, tuple[tuple[str, float | None, float | None, str], ...]], ...],
    ) -> set[str]:
        props: set[str] = set()
        for _, steps in anim_sets:
            for prop, _, to_val, _ in steps:
                if prop == "nop" or to_val is None:
                    continue
                props.add(prop)
        return props

    # ------------------------------------------------------------------
    # Preview state / animation value resolution
    # ------------------------------------------------------------------

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

    def _event_matches_preview_state(
        self,
        event_name: str,
        expression: str | None,
        element: ThemePreviewElement,
    ) -> bool:
        normalized_event = event_name.casefold()
        if normalized_event == "menuexit":
            if not expression:
                return False
            expr = expression.strip()
            if not expr:
                return False
            active_index = self._active_preview_menu_index()
            if expr == "i":
                return not (element.kind == "menu" and element.selected)
            if expr.startswith("!"):
                try:
                    return active_index == int(expr[1:])
                except ValueError:
                    return False
            if expr.startswith(">"):
                try:
                    return not (active_index > int(expr[1:]))
                except ValueError:
                    return False
            if expr.startswith("<"):
                try:
                    return not (active_index < int(expr[1:]))
                except ValueError:
                    return False
            try:
                return active_index != int(expr)
            except ValueError:
                return False
        return self._menu_index_matches_preview_state(expression, element)

    def _preview_state_values_for_element(self, element: ThemePreviewElement) -> dict[str, float]:
        if not element.event_anim_targets:
            return {}
        event_order = ("enter", "menuexit", "menuenter", "menuscroll") if self._wheel_anim_active else ("enter", "menuexit", "menuenter", "highlightenter")
        values: dict[str, float] = {}
        for desired_event in event_order:
            for event_name, menu_index_expr, steps in element.event_anim_targets:
                if event_name != desired_event:
                    continue
                if not self._event_matches_preview_state(event_name, menu_index_expr, element):
                    continue
                for prop_name, to_value in steps:
                    values[prop_name] = to_value
        return values

    @staticmethod
    def _idle_terminal_values_for_element(element: ThemePreviewElement) -> dict[str, float]:
        values: dict[str, float] = {}
        for _, steps in element.idle_anim_sets:
            for prop, _, to_val, _ in steps:
                if prop == "nop":
                    continue
                values[prop] = to_val
        return values

    @staticmethod
    def _should_use_idle_terminal_values_in_still_mode(element: ThemePreviewElement) -> bool:
        if element.kind == "menu" or not element.idle_anim_sets:
            return False
        event_names = {event_name for event_name, _, _ in element.event_anim_targets}
        # Still mode should preserve authored visible menu-enter state for elements
        # like LUNA's menubg.png, while still allowing intro overlays without a
        # menu-enter lifecycle to collapse to their idle terminal state.
        if "menuenter" in event_names or "highlightenter" in event_names:
            return False
        return True

    def _effective_preview_animation_values(self, element: ThemePreviewElement) -> dict[str, float]:
        values = self._preview_state_values_for_element(element)
        if not self._animation_enabled and self._should_use_idle_terminal_values_in_still_mode(element):
            values.update(self._idle_terminal_values_for_element(element))
        event_values = self._event_anim_values.get(element)
        if event_values:
            values.update(event_values)
        idle_values = self._idle_anim_values.get(element)
        if idle_values:
            values.update(idle_values)
        return values

    # ------------------------------------------------------------------
    # Drawing: main preview
    # ------------------------------------------------------------------

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
        # Lazy-computed per-element dicts; populated on demand in the draw loop.
        # Pre-populate only for pulsing overlay targets: those are looked up by their
        # TARGET element (a selected menu item with a higher draw-order layer) before
        # that target has been reached in the ordered loop.
        effective_animation_values: dict[ThemePreviewElement, dict[str, float]] = {}
        display_rects: dict[ThemePreviewElement, QRectF] = {}
        for _target in self._pulsing_overlay_targets.values():
            if _target not in effective_animation_values:
                effective_animation_values[_target] = self._effective_preview_animation_values(_target)
            if _target not in display_rects:
                _target_rd = self._render_data.get(_target)
                _target_text = self._formatted_element_text(_target, _target_rd.text) if _target_rd is not None and _target_rd.text else None
                display_rects[_target] = self._element_display_rect(
                    _target, fitted, scale_x, scale_y, _target_text,
                    render_data=_target_rd,
                    animated_values=effective_animation_values[_target],
                )
        id_to_element = {e.elem_id: e for e in preview.elements if e.elem_id}
        if self._cached_ordered_elements is None:
            self._cached_ordered_elements = self._ordered_elements(preview.elements)
        if record_hitboxes:
            self._element_hitboxes = []
        for element in self._cached_ordered_elements:
            if self._wheel_anim_active and element.kind == "menu":
                continue
            if self._scroll_fading_out and element.kind == "menu":
                continue
            if self._wheel_anim_active and element in self._pulsing_overlay_elements:
                continue
            color = QColor(self._COLOR_MAP.get(element.kind, QColor("#9f9f9f")))
            render_data = self._render_data.get(element)
            display_text = self._formatted_element_text(element, render_data.text) if render_data is not None and render_data.text else None
            # Lazy-compute animation values and display rect after cheap culls.
            if element not in effective_animation_values:
                effective_animation_values[element] = self._effective_preview_animation_values(element)
            if element not in display_rects:
                display_rects[element] = self._element_display_rect(
                    element, fitted, scale_x, scale_y, display_text,
                    render_data=render_data,
                    animated_values=effective_animation_values[element],
                )
            scaled_rect = display_rects[element]
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
                    clip_rect = fitted if self._allow_rotated_menu_overflow(element) else visible_rect
                    self._draw_rect_pixmap(painter, render_data.pixmap, element, clip_rect, scaled_rect)
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
        elif self._scroll_fading_out and self._wheel_anim_slot_elements:
            self._draw_animated_wheel(
                painter,
                fitted,
                scale_x,
                scale_y,
                scroll_pos=self._wheel_anim_last_scroll_pos,
                opacity_scale=self._scroll_anim_opacity,
            )

    # ------------------------------------------------------------------
    # Drawing: wheel animation
    # ------------------------------------------------------------------

    def _draw_animated_wheel(
        self,
        painter: QPainter,
        fitted: QRectF,
        scale_x: float,
        scale_y: float,
        *,
        scroll_pos: float | None = None,
        opacity_scale: float = 1.0,
    ) -> None:
        if scroll_pos is None:
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
            for slot_index, current_element in enumerate(elements):
                next_index = (slot_index - 1) % n
                next_element = elements[next_index]
                offset = slot_index - sel_idx
                game_idx = (start_game + int_s + offset) % total
                pixmap = pixmaps.get(game_idx)
                if pixmap is None:
                    continue
                ex = current_element.x + (next_element.x - current_element.x) * frac
                ey = current_element.y + (next_element.y - current_element.y) * frac
                ew = current_element.width + (next_element.width - current_element.width) * frac
                eh = current_element.height + (next_element.height - current_element.height) * frac
                angle_a = current_element.angle or 0.0
                angle_b = next_element.angle or 0.0
                eangle = angle_a + (angle_b - angle_a) * frac
                alpha_a = current_element.alpha if current_element.alpha is not None else 1.0
                alpha_b = next_element.alpha if next_element.alpha is not None else 1.0
                ealpha = (alpha_a + (alpha_b - alpha_a) * frac) * opacity_scale
                draw_rect = QRectF(
                    fitted.x() + ex * scale_x,
                    fitted.y() + ey * scale_y,
                    max(2.0, ew * scale_x),
                    max(2.0, eh * scale_y),
                )
                visible_rect = draw_rect.intersected(fitted)
                if visible_rect.isEmpty():
                    continue
                clip_rect = fitted if self._allow_rotated_menu_overflow(current_element, angle=eangle) else visible_rect
                self._draw_wheel_logo(painter, pixmap, current_element, draw_rect, clip_rect, eangle, ealpha)

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
        if self._allow_rotated_menu_overflow(element, angle=angle):
            scaled = pixmap.scaled(
                image_rect.size().toSize(),
                aspect_mode,
                Qt.TransformationMode.SmoothTransformation,
            )
        elif abs(angle) > 0.1:
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

    # ------------------------------------------------------------------
    # Drawing: pixmap helpers
    # ------------------------------------------------------------------

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
            if element.kind in {"video", "reloadable_video"} and element.max_height is not None:
                # Width-only video slots with a maxHeight cap are authored like RetroFE view boxes:
                # layout sizing resolves the final slot to the capped height, and the video then
                # fills that height, overflowing horizontally as needed.
                scale_size = QSize(32767, int(round(full_rect.height())) + 1)
                aspect_mode = Qt.AspectRatioMode.KeepAspectRatio
            elif self._should_expand_width_constrained_media(element):
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
        allow_rotated_overflow = self._allow_rotated_menu_overflow(element)
        if allow_rotated_overflow:
            scaled_pixmap = pixmap.scaled(
                scale_size,
                aspect_mode,
                Qt.TransformationMode.SmoothTransformation,
            )
        elif element.angle is not None and abs(element.angle) > 0.1:
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

    # ------------------------------------------------------------------
    # Drawing: text
    # ------------------------------------------------------------------

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
            # is hard-cut, not ellipsized. Honor explicit horizontal alignment inside the
            # box so right-anchored numeric slots like Cafe80s' year line up correctly.
            pad = max(4.0, 8.0 * scale_x)
            font_height = QFontMetricsF(text_font).height()
            text_rect = QRectF(draw_rect.left(), draw_rect.top(), max(1.0, draw_rect.width() - pad), draw_rect.height())
            clip = QRectF(visible_rect.left(), visible_rect.top() - font_height, max(1.0, text_rect.width()), font_height * 3)
            painter.setClipRect(clip)
            painter.drawText(text_rect, flags | Qt.TextFlag.TextSingleLine, text)
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

    # ------------------------------------------------------------------
    # Layout geometry
    # ------------------------------------------------------------------

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
        indexed = list(enumerate(elements))
        with_layers = [(index, element) for index, element in indexed if element.layer is not None]
        without_layers = [(index, element) for index, element in indexed if element.layer is None]
        ordered = [element for index, element in sorted(with_layers, key=lambda item: ((item[1].layer or 0), item[0]))]
        ordered.extend(element for index, element in without_layers)
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
        animated_x = animated_values.get("x")
        animated_y = animated_values.get("y")
        animated_xoffset = animated_values.get("xoffset")
        animated_yoffset = animated_values.get("yoffset")
        has_animation_override = not (
            animated_width is None
            and animated_height is None
            and animated_max_width is None
            and animated_max_height is None
            and animated_x is None
            and animated_y is None
            and animated_xoffset is None
            and animated_yoffset is None
        )
        has_static_constraint = any(
            value is not None
            for value in (element.min_width, element.min_height, element.max_width, element.max_height)
        )
        if not has_animation_override and element.explicit_width and element.explicit_height and not has_static_constraint:
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

        max_height_px = (
            (animated_max_height * scale_y)
            if animated_max_height is not None
            else ((element.max_height * scale_y) if element.max_height is not None else None)
        )
        max_width_px = (
            (animated_max_width * scale_x)
            if animated_max_width is not None
            else ((element.max_width * scale_x) if element.max_width is not None else None)
        )
        min_width_px = (element.min_width * scale_x) if element.min_width is not None else None
        min_height_px = (element.min_height * scale_y) if element.min_height is not None else None

        if not explicit_width and not explicit_height:
            if max_width_px is not None or max_height_px is not None:
                # Unsized media with only max constraints should fit their intrinsic
                # aspect into the authored constraint box. Treating source pixels as
                # the layout size makes smaller assets render too small.
                if max_width_px is not None and max_height_px is not None:
                    fit_scale = min(max_width_px / intrinsic_width, max_height_px / intrinsic_height)
                    box_width = intrinsic_width * fit_scale
                    box_height = intrinsic_height * fit_scale
                elif max_width_px is not None:
                    box_width = max_width_px
                    box_height = intrinsic_height * box_width / intrinsic_width
                else:
                    box_height = max_height_px or intrinsic_height
                    box_width = intrinsic_width * box_height / intrinsic_height
            else:
                # Unsized media lives in layout-space pixels, so intrinsic media dimensions
                # still need to be scaled into the current preview canvas. Treating intrinsic
                # pixels as final widget pixels makes the same asset render at different
                # relative sizes in embedded vs expanded preview.
                box_width = intrinsic_width * scale_x
                box_height = intrinsic_height * scale_y
        elif (
            explicit_width
            and not explicit_height
            and element.kind in {"video", "reloadable_video"}
            and max_height_px is not None
        ):
            # RetroFE-style video slots authored with width plus maxHeight behave like
            # height-bound viewports: the capped height defines the visible box and the
            # video fills that height, overflowing horizontally if needed.
            box_height = max(1.0, max_height_px)
            box_width = intrinsic_width * box_height / intrinsic_height
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
            min_width=min_width_px,
            min_height=min_height_px,
            max_width=max_width_px,
            max_height=max_height_px,
        )

        resolved_anchor_x = self._derived_text_anchor(element.x, element.width, element.x_origin)
        resolved_anchor_y = self._derived_text_anchor(element.y, element.height, element.y_origin)
        raw_anchor_x = element.anchor_x if element.anchor_x is not None else resolved_anchor_x
        raw_anchor_y = element.anchor_y if element.anchor_y is not None else resolved_anchor_y
        base_offset_x = (
            (resolved_anchor_x - raw_anchor_x)
            if resolved_anchor_x is not None and raw_anchor_x is not None
            else 0.0
        )
        base_offset_y = (
            (resolved_anchor_y - raw_anchor_y)
            if resolved_anchor_y is not None and raw_anchor_y is not None
            else 0.0
        )
        anchor_layout_x = (
            (animated_x if animated_x is not None else raw_anchor_x)
            if raw_anchor_x is not None
            else element.x
        )
        anchor_layout_y = (
            (animated_y if animated_y is not None else raw_anchor_y)
            if raw_anchor_y is not None
            else element.y
        )
        anchor_layout_x += animated_xoffset if animated_xoffset is not None else base_offset_x
        anchor_layout_y += animated_yoffset if animated_yoffset is not None else base_offset_y
        x = self._anchored_coordinate(fitted.x() + (anchor_layout_x * scale_x), box_width, element.x_origin)
        y = self._anchored_coordinate(fitted.y() + (anchor_layout_y * scale_y), box_height, element.y_origin)
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

    # ------------------------------------------------------------------
    # Hit-testing and element geometry helpers
    # ------------------------------------------------------------------

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

    def _anchored_coordinate(self, anchor: float, size: float, origin: str | None) -> float:
        origin_key = (origin or "").casefold()
        if origin_key in {"center", "middle"}:
            return anchor - (size / 2.0)
        if origin_key in {"right", "bottom"}:
            return anchor - size
        return anchor

    # ------------------------------------------------------------------
    # Media layout helpers
    # ------------------------------------------------------------------

    def _should_fit_media_rect(self, element: ThemePreviewElement) -> bool:
        # Panning images fill (and overflow) their container -- never fit-within.
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

    def _allow_rotated_menu_overflow(
        self,
        element: ThemePreviewElement,
        *,
        angle: float | None = None,
    ) -> bool:
        effective_angle = angle if angle is not None else element.angle
        return element.kind == "menu" and effective_angle is not None and abs(effective_angle) > 0.1

    def _aligned_media_rect(self, bounds: QRectF, pixmap: QPixmap, element: ThemePreviewElement) -> QRectF:
        x_origin = (element.x_origin or "").casefold()
        y_origin = (element.y_origin or "").casefold()
        if x_origin in {"center", "middle"}:
            x_pos = bounds.center().x() - (pixmap.width() / 2.0)
        elif x_origin in {"right", "bottom"}:
            x_pos = bounds.right() - pixmap.width()
        elif pixmap.width() > bounds.width():
            # For cover-style media with no explicit horizontal origin, center any overflow
            # within the authored box instead of pinning it to the left edge.
            x_pos = bounds.center().x() - (pixmap.width() / 2.0)
        else:
            # Default (no xOrigin or "left"/"top"): anchor at the element's left edge.
            x_pos = bounds.left()
        if y_origin in {"center", "middle"}:
            y_pos = bounds.center().y() - (pixmap.height() / 2.0)
        elif y_origin in {"right", "bottom"}:
            y_pos = bounds.bottom() - pixmap.height()
        elif pixmap.height() > bounds.height():
            # For cover-style media with no explicit vertical origin, center any overflow
            # within the authored box instead of pinning it to the top edge.
            y_pos = bounds.center().y() - (pixmap.height() / 2.0)
        else:
            # Default (no yOrigin or "left"/"top"): anchor at the element's top edge.
            y_pos = bounds.top()
        return QRectF(x_pos, y_pos, float(pixmap.width()), float(pixmap.height()))

    # ------------------------------------------------------------------
    # Font and text helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Action buttons
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Expanded / floating preview
    # ------------------------------------------------------------------

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
        desired_interval = 33 if animation else 50
        timer_active = self._floating_preview_update_timer.isActive()
        # Only change the interval when speeding up, or when the timer isn't running.
        # Never slow down a running timer -- setInterval on an active QTimer restarts its
        # countdown in most Qt 6 builds, so alternating between 33 and 50 ms (animation
        # ticks vs video updates) would keep the timer perpetually restarting.
        if self._floating_preview_update_interval_ms != desired_interval:
            if desired_interval < self._floating_preview_update_interval_ms or not timer_active:
                self._floating_preview_update_interval_ms = desired_interval
                self._floating_preview_update_timer.setInterval(desired_interval)
        if immediate:
            self._floating_preview_update_timer.stop()
            self._flush_floating_preview_update()
            return
        if not timer_active:
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
        target_width = max(1, min(self._window_filter_target.width() - 24, max(520, self.width() * 2)))
        target_height = max(1, min(self._window_filter_target.height() - 24, max(360, self.height() * 2)))
        # Reuse the offscreen buffer when the size hasn't changed -- avoids a heap/GPU
        # allocation plus a full-surface transparent clear on every update cycle.
        if (
            self._floating_canvas_pixmap is None
            or self._floating_canvas_pixmap.width() != target_width
            or self._floating_canvas_pixmap.height() != target_height
        ):
            self._floating_canvas_pixmap = QPixmap(target_width, target_height)
        canvas = self._floating_canvas_pixmap
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
