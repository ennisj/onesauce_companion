"""Controller owning the Themes screen's preview and catalog-scan state."""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer

from onesauce_companion.ui._worker_handle import WorkerHandle

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


class ThemesController(QObject):
    """Holds all Themes-screen state and the preview's driving timers.

    The Themes preview is the app's most intricate state machine — catalog
    scanning, layout rendering, attract-mode cycling, wheel animation, and
    video sessions. Its logic lives in the free functions of
    ``ui/screens/themes_screen.py`` (which operate on the MainWindow), so
    this controller is deliberately a *state object* rather than a full
    behavioural controller: it owns the ~30 attributes that previously lived
    directly on MainWindow plus the three preview timers and the catalog
    WorkerHandle, giving them one cohesive home.

    Timers are parented to this controller (itself parented to the window),
    so their lifetime is unchanged. The timer callbacks dispatch into the
    themes_screen free functions, passing the window.
    """

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window

        # Catalog scan (async) state.
        self.catalog_handle = WorkerHandle(window)
        self.catalog_completed = 0
        self.catalog_total = 0
        self.catalog_restart_pending = False
        self.catalog_pending_target: object | None = None
        self.catalog_pending_target_key: str | None = None
        self.catalog_target: str | None = None

        # Render lifecycle flags.
        self.rendering: bool = False
        self.render_pending: bool = False
        self.render_full_requested: bool = False

        # Selection state (persisted to settings).
        self.selected_name: str | None = None
        self.selected_collection_name: str | None = None
        self.selected_game_key: list[str] | None = None
        self.selected_element = None

        # Catalog/preview data.
        self.entries: tuple = tuple()
        self.preview = None
        self.element_index_map: list = [None]
        self.games_cache: dict[str, tuple] = {}
        self.media_root_cache: dict[str, object] = {}

        # Preview render + attract-mode state.
        self.preview_render_data: dict = {}
        self.preview_video_sessions: dict = {}
        self.preview_animation_enabled = False
        self.preview_muted = False
        self.preview_wheel_spinning = False
        self.preview_pending_indices: deque[int] = deque()
        self.preview_pending_settled_render = False
        self.preview_previous_stopped_game_key: list[str] | None = None
        self.preview_last_stopped_game_key: list[str] | None = None
        self.preview_promoted_final_zero_index: int | None = None

        # Driving timers.
        self.preview_cycle_timer = QTimer(self)
        self.preview_cycle_timer.setSingleShot(True)
        self.preview_cycle_timer.timeout.connect(self._advance_attract_mode)
        self.preview_scroll_timer = QTimer(self)
        self.preview_scroll_timer.setSingleShot(True)
        self.preview_scroll_timer.timeout.connect(self._advance_attract_mode)
        self.video_repaint_timer = QTimer(self)
        self.video_repaint_timer.setInterval(33)
        self.video_repaint_timer.timeout.connect(self._flush_video_repaint)
        self.video_dirty = False

    def _advance_attract_mode(self) -> None:
        from onesauce_companion.ui.screens.themes_screen import _advance_theme_preview_attract_mode

        _advance_theme_preview_attract_mode(self._window)

    def _flush_video_repaint(self) -> None:
        from onesauce_companion.ui.screens.themes_screen import flush_theme_video_repaint

        flush_theme_video_repaint(self._window)
