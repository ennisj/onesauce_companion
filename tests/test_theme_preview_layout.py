from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QFontMetricsF, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from onesauce_companion.services.games import GameManifestEntry
from onesauce_companion.services import themes
from onesauce_companion.ui.main_window import GAMES_SCREEN, THEMES_SCREEN, MainWindow, ThemeLayoutPreviewWidget, ThemePreviewRenderData, ThemePreviewVideoSession


def _write_theme_layout(tmp_path: Path, theme_name: str, layout_xml: str) -> Path:
    theme_dir = tmp_path / "base_assets" / "layouts" / theme_name
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "layout.xml").write_text(layout_xml, encoding="utf-8")
    return theme_dir


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_build_theme_layout_preview_preserves_reloadable_video_imagetype(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Test Theme",
        """<layout width="1920" height="1080">
  <reloadableVideo imageType="screenshot" x="200" y="150" width="400" maxHeight="300" />
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Test Theme")

    assert preview is not None
    element = next(item for item in preview.elements if item.kind == "reloadable_video")
    assert element.slot_name == "screenshot"
    assert element.image_type == "screenshot"


def test_build_theme_layout_preview_treats_max_height_as_constraint(monkeypatch, tmp_path: Path) -> None:
    theme_dir = _write_theme_layout(
        tmp_path,
        "Constraint Theme",
        """<layout width="1920" height="1080">
  <reloadableImage type="logo" src="images/logo.png" x="960" y="540" xOrigin="center" yOrigin="center" width="400" maxHeight="200" />
</layout>
""",
    )
    (theme_dir / "images").mkdir(parents=True, exist_ok=True)

    original = themes._intrinsic_media_dimensions

    def fake_intrinsic_media_dimensions(source_path: str | None) -> tuple[float, float] | None:
        if source_path and source_path.endswith("logo.png"):
            return (800.0, 600.0)
        return original(source_path)

    monkeypatch.setattr(themes, "_intrinsic_media_dimensions", fake_intrinsic_media_dimensions)

    preview = themes.build_theme_layout_preview(tmp_path, "Constraint Theme")

    assert preview is not None
    element = next(item for item in preview.elements if item.slot_name == "logo")
    assert element.explicit_width is True
    assert element.explicit_height is False
    assert round(element.width, 2) == 266.67
    assert round(element.height, 2) == 200.00
    assert round(element.x, 2) == 826.67
    assert round(element.y, 2) == 440.00


def test_retrofe_text_layout_scales_glyph_width_from_actual_font_height() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="year",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="year",
        value=None,
        x=20.0,
        y=1040.0,
        width=260.0,
        height=48.0,
        layer=8,
        font_path=r"V:\base_assets\layouts\Amiga Memories\fonts\OpenSans.ttf",
        font_size=36.0,
        load_font_size=36.0,
        x_origin="left",
        y_origin="top",
    )

    layout = widget._retrofe_text_layout(element, "1983", 1.0)

    assert layout is not None
    assert round(float(layout["width"]), 2) == 50.47
    assert float(layout["width"]) < 60.57


def test_preview_font_matches_retrofe_scaled_text_size() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="year",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="year",
        value=None,
        x=20.0,
        y=1040.0,
        width=260.0,
        height=48.0,
        layer=8,
        font_path=r"V:\base_assets\layouts\Amiga Memories\fonts\OpenSans.ttf",
        font_size=36.0,
        load_font_size=36.0,
        x_origin="left",
        y_origin="top",
    )

    font = widget._preview_font_for_element(element, 1.0, 1.0)
    metrics = QFontMetricsF(font)

    assert round(metrics.height(), 2) == 36.00
    assert round(metrics.horizontalAdvance("1983"), 2) == 50.50


def test_build_theme_layout_preview_preserves_idle_width_and_maxheight_animation(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Pulse Theme",
        """<layout width="1920" height="1080">
  <reloadableImage type="logo" x="center" y="center" xOrigin="center" yOrigin="center" width="400" maxHeight="200">
    <onMenuIdle>
      <set duration="0.4">
        <animate type="alpha" to="0"/>
      </set>
      <set duration="0.001">
        <animate type="width" to="400" algorithm="easeinquadratic"/>
        <animate type="maxHeight" to="200" algorithm="easeinquadratic"/>
        <animate type="alpha" to="0.9"/>
      </set>
      <set duration="1.3">
        <animate type="width" to="480" algorithm="easeinquadratic"/>
        <animate type="maxHeight" to="240" algorithm="easeinquadratic"/>
        <animate type="alpha" to="0.0"/>
      </set>
    </onMenuIdle>
  </reloadableImage>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Pulse Theme")

    assert preview is not None
    element = next(item for item in preview.elements if item.kind == "reloadable_image")
    props = [step[0] for _, steps in element.idle_anim_sets for step in steps]
    assert "alpha" in props
    assert "width" in props
    assert "maxheight" in props
    width_steps = [step for _, steps in element.idle_anim_sets for step in steps if step[0] == "width"]
    assert width_steps[-1][3] == "easeinquadratic"


def test_menu_items_inherit_parent_menu_geometry_before_item_defaults_and_item(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Menu Theme",
        """<layout width="1920" height="1080">
  <menu type="custom" imageType="logo" width="500" height="100">
    <itemDefaults y="center" x="900" yOrigin="center" xOrigin="center" width="260" maxHeight="120" />
    <item xOffset="580" yOffset="0" width="400" maxHeight="200" selected="true" />
  </menu>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Menu Theme")

    assert preview is not None
    element = next(item for item in preview.elements if item.kind == "menu" and item.selected)
    assert element.explicit_width is True
    assert element.explicit_height is True
    assert element.height == 100.0
    assert element.max_height == 200.0


def test_animated_media_display_rect_grows_from_center_anchor() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(800, 400)
    pixmap.fill()
    element = themes.ThemePreviewElement(
        label="logo pulse",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="logo",
        value=None,
        x=200.0,
        y=200.0,
        width=400.0,
        height=200.0,
        layer=9,
        x_origin="center",
        y_origin="center",
        anchor_x=400.0,
        anchor_y=300.0,
        explicit_width=True,
        explicit_height=False,
        max_height=200.0,
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        None,
        render_data=ThemePreviewRenderData(pixmap=pixmap),
        animated_values={"width": 480.0, "maxheight": 240.0, "alpha": 0.25},
    )

    assert round(rect.width(), 2) == 480.00
    assert round(rect.height(), 2) == 240.00
    assert round(rect.center().x(), 2) == 400.00
    assert round(rect.center().y(), 2) == 300.00


def test_media_display_rect_uses_intrinsic_size_for_width_only_logo_with_max_height() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(264, 175)
    pixmap.fill()
    element = themes.ThemePreviewElement(
        label="selected logo",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=1280.0,
        y=440.0,
        width=400.0,
        height=220.0,
        layer=19,
        x_origin="center",
        y_origin="center",
        explicit_width=True,
        explicit_height=False,
        max_height=200.0,
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        None,
        render_data=ThemePreviewRenderData(pixmap=pixmap),
    )

    assert round(rect.width(), 2) == 301.71
    assert round(rect.height(), 2) == 200.00


def test_media_display_rect_scales_unsized_intrinsic_media_with_canvas() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(483, 900)
    pixmap.fill()
    element = themes.ThemePreviewElement(
        label="cabinet",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="cabinet",
        value=None,
        x=0.0,
        y=300.0,
        width=220.0,
        height=160.0,
        layer=15,
        explicit_width=False,
        explicit_height=False,
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 384.0, 682.5),
        0.5,
        0.5,
        None,
        render_data=ThemePreviewRenderData(pixmap=pixmap),
        animated_values={},
    )

    assert round(rect.width(), 2) == 241.50
    assert round(rect.height(), 2) == 450.00


def test_idle_animation_progress_supports_ease_in_quadratic() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()

    assert round(widget._idle_animation_progress(0.5, "linear"), 3) == 0.5
    assert round(widget._idle_animation_progress(0.5, "easeinquadratic"), 3) == 0.25
    assert round(widget._idle_animation_progress(0.5, "ease-in-quadratic"), 3) == 0.25


def test_set_render_data_defers_idle_restart_until_transition_finishes() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    preview = themes.ThemeLayoutPreview(
        theme_name="Pulse Theme",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(
            themes.ThemePreviewElement(
                label="pulse",
                kind="reloadable_image",
                tag_name="reloadableImage",
                slot_name="logo",
                value=None,
                x=960.0,
                y=540.0,
                width=400.0,
                height=200.0,
                layer=9,
                idle_anim_sets=((0.4, (("alpha", 0.0, 0.9, "linear"),)),),
            ),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget.set_animation_controls(can_play=True, can_mute=False, is_playing=True, is_muted=False)
    assert widget._idle_anim_timer.isActive()
    element = preview.elements[0]
    widget.set_render_data({element: ThemePreviewRenderData(text="before")}, transition=False)

    widget.set_render_data({element: ThemePreviewRenderData(text="after")}, transition=True)

    assert widget._transition_active is True
    assert widget._resume_idle_after_transition is True
    assert widget._idle_anim_timer.isActive() is False


def test_set_render_data_without_transition_does_not_restart_idle() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    preview = themes.ThemeLayoutPreview(
        theme_name="Pulse Theme",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(
            themes.ThemePreviewElement(
                label="pulse",
                kind="reloadable_image",
                tag_name="reloadableImage",
                slot_name="logo",
                value=None,
                x=960.0,
                y=540.0,
                width=400.0,
                height=200.0,
                layer=9,
                idle_anim_sets=((0.4, (("alpha", 0.0, 0.9, "linear"),)),),
            ),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget.set_animation_controls(can_play=True, can_mute=False, is_playing=True, is_muted=False)
    assert widget._idle_anim_timer.isActive()
    start_ms = widget._idle_anim_start_ms
    element = preview.elements[0]

    widget.set_render_data({element: ThemePreviewRenderData(text="frame")}, transition=False)

    assert widget._transition_active is False
    assert widget._resume_idle_after_transition is False
    assert widget._idle_anim_timer.isActive() is True
    assert widget._idle_anim_start_ms == start_ms


def test_set_render_data_throttles_expanded_floating_preview_updates() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._expanded = True
    widget._floating_preview = object()  # type: ignore[assignment]
    calls: list[str] = []

    def fake_update_floating_preview() -> None:
        calls.append("update")

    widget._update_floating_preview = fake_update_floating_preview  # type: ignore[method-assign]

    widget.set_render_data({})
    widget.set_render_data({})

    assert widget._floating_preview_dirty is True
    assert widget._floating_preview_update_timer.isActive() is True
    assert calls == []

    widget._flush_floating_preview_update()

    assert widget._floating_preview_dirty is False
    assert calls == ["update"]


def test_expanded_animation_updates_use_faster_floating_preview_interval() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._expanded = True
    widget._floating_preview = object()  # type: ignore[assignment]

    widget._request_floating_preview_update(animation=True)

    assert widget._floating_preview_dirty is True
    assert widget._floating_preview_update_timer.interval() == 16


def test_pulse_overlay_is_hidden_until_it_extends_beyond_selected_logo() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    base_rect = QRectF(100.0, 100.0, 400.0, 200.0)

    assert widget._pulse_overlay_is_visually_distinct(QRectF(100.0, 100.0, 400.0, 200.0), base_rect) is False
    assert widget._pulse_overlay_is_visually_distinct(QRectF(97.0, 100.0, 406.0, 200.0), base_rect) is False
    assert widget._pulse_overlay_is_visually_distinct(QRectF(95.5, 100.0, 409.0, 200.0), base_rect) is True


def test_soften_pulse_overlay_pixmap_preserves_output_size() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(120, 60)
    pixmap.fill()

    softened = widget._soften_pulse_overlay_pixmap(pixmap)

    assert softened.isNull() is False
    assert softened.size() == pixmap.size()


def test_restart_idle_animation_seeds_first_idle_state_immediately() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    preview = themes.ThemeLayoutPreview(
        theme_name="Pulse Theme",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(
            themes.ThemePreviewElement(
                label="pulse",
                kind="reloadable_image",
                tag_name="reloadableImage",
                slot_name="logo",
                value=None,
                x=960.0,
                y=540.0,
                width=400.0,
                height=200.0,
                layer=9,
                idle_anim_sets=((0.4, (("alpha", 1.0, 0.0, "linear"),)),),
            ),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget.set_animation_controls(can_play=True, can_mute=False, is_playing=True, is_muted=False)
    element = preview.elements[0]

    assert element in widget._idle_anim_alphas
    assert round(widget._idle_anim_alphas[element], 2) == 1.00


def test_start_wheel_animation_preserves_current_idle_values() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    preview = themes.ThemeLayoutPreview(
        theme_name="Atari Girl",
        selected_collection="ARCADE",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(
            themes.ThemePreviewElement(
                label="game video",
                kind="reloadable_video",
                tag_name="reloadableVideo",
                slot_name="screenshot",
                value=None,
                x=200.0,
                y=0.0,
                width=400.0,
                height=300.0,
                layer=4,
                alpha=0.0,
                idle_anim_sets=((0.5, (("alpha", 0.0, 1.0, "linear"),)),),
            ),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget.set_animation_controls(can_play=True, can_mute=False, is_playing=True, is_muted=False)
    element = preview.elements[0]
    widget._idle_anim_alphas[element] = 1.0
    widget._idle_anim_values[element] = {"alpha": 1.0}

    widget.start_wheel_animation([], {}, 0, 0, 1, 10, 250)

    assert widget._wheel_anim_active is True
    assert widget._idle_anim_timer.isActive() is False
    assert widget._idle_anim_alphas[element] == 1.0
    assert widget._idle_anim_values[element]["alpha"] == 1.0


def test_media_opacity_uses_element_alpha_without_idle_animation() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="overlay",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="logo",
        value=None,
        x=100.0,
        y=100.0,
        width=200.0,
        height=100.0,
        layer=5,
        alpha=0.35,
    )

    widget._render_data = {element: ThemePreviewRenderData(pixmap=QPixmap(200, 100))}

    base_opacity = max(0.0, min(1.0, element.alpha if element.alpha is not None else 1.0))
    effective_opacity = widget._idle_anim_alphas.get(element, base_opacity)

    assert round(effective_opacity, 2) == 0.35


def test_animated_media_anchor_uses_resolved_rect_including_offsets() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(800, 400)
    pixmap.fill()
    element = themes.ThemePreviewElement(
        label="logo pulse",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="logo",
        value=None,
        x=1280.0,
        y=440.0,
        width=400.0,
        height=200.0,
        layer=8,
        x_origin="center",
        y_origin="center",
        anchor_x=900.0,
        anchor_y=540.0,
        explicit_width=True,
        explicit_height=False,
        max_height=200.0,
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        None,
        render_data=ThemePreviewRenderData(pixmap=pixmap),
        animated_values={"width": 480.0, "maxheight": 240.0, "alpha": 0.25},
    )

    assert round(rect.center().x(), 2) == 1480.00
    assert round(rect.center().y(), 2) == 540.00


def test_theme_preview_reloadable_video_keeps_playing_while_wheel_spins() -> None:
    _ensure_app()

    class FakeAudio:
        def __init__(self) -> None:
            self.muted = None

        def setMuted(self, value) -> None:
            self.muted = value

    class FakePlayer:
        def __init__(self) -> None:
            self.play_calls = 0
            self.pause_calls = 0

        def play(self) -> None:
            self.play_calls += 1

        def pause(self) -> None:
            self.pause_calls += 1

    element = themes.ThemePreviewElement(
        label="game video",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=200.0,
        y=0.0,
        width=400.0,
        height=300.0,
        layer=4,
    )
    session = ThemePreviewVideoSession(
        element=element,
        video_path=Path("dummy.mp4"),
        player=FakePlayer(),
        audio_output=FakeAudio(),
        video_sink=object(),
    )

    class FakeMainWindow:
        _theme_preview_animation_enabled = True
        _theme_preview_wheel_spinning = True
        _theme_preview_muted = False

    MainWindow._apply_theme_preview_session_state(FakeMainWindow(), session)

    assert session.player.play_calls == 1
    assert session.player.pause_calls == 0
    assert session.audio_output.muted is False


def test_build_theme_layout_preview_preserves_enter_and_scroll_animation_targets(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "State Theme",
        """<layout width="1920" height="1080">
  <image src="images/panel.png" x="100" y="50" width="550" height="180" alpha="0">
    <onMenuEnter menuIndex="1">
      <set duration="0.01">
        <animate type="alpha" to="1"/>
      </set>
      <set duration="0.3">
        <animate type="width" from="10" to="550"/>
      </set>
    </onMenuEnter>
    <onMenuScroll>
      <set duration="0.01">
        <animate type="alpha" to="0"/>
      </set>
    </onMenuScroll>
  </image>
</layout>
""",
    )
    (tmp_path / "base_assets" / "layouts" / "State Theme" / "images").mkdir(parents=True, exist_ok=True)
    preview = themes.build_theme_layout_preview(tmp_path, "State Theme", "MAME")

    assert preview is not None
    element = preview.elements[0]
    assert ("menuenter", "1", (("alpha", 1.0), ("width", 550.0))) in element.event_anim_targets
    assert ("menuscroll", None, (("alpha", 0.0),)) in element.event_anim_targets


def test_preview_state_values_apply_highlight_enter_when_collection_is_selected() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="title box",
        kind="image",
        tag_name="image",
        slot_name=None,
        value=None,
        x=1215.0,
        y=25.0,
        width=550.0,
        height=180.0,
        layer=18,
        alpha=0.0,
        event_anim_targets=(
            ("menuenter", "1", (("alpha", 1.0), ("width", 550.0))),
            ("highlightenter", "1", (("alpha", 1.0), ("width", 550.0))),
            ("menuscroll", None, (("alpha", 0.0),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="CoinOPS",
        selected_collection="Gaelco",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(element,),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)

    settled_values = widget._effective_preview_animation_values(element)
    assert settled_values["alpha"] == 1.0
    assert settled_values["width"] == 550.0

    widget._wheel_anim_active = True
    scrolling_values = widget._effective_preview_animation_values(element)
    assert scrolling_values["alpha"] == 0.0


def test_layout_preferred_prefers_exact_game_media_before_inherited_fallback(monkeypatch) -> None:
    class FakeMainWindow:
        def _resolve_static_theme_render(self, element):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            return None

        def _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry, *, allow_system_fallback=True):
            if layout_collection == "MAME" and not allow_system_fallback:
                return ThemePreviewRenderData(text="exact-layout")
            if layout_collection == "2 ARCADE GENRES" and allow_system_fallback:
                return ThemePreviewRenderData(text="inherited-fallback")
            return None

        def _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index):
            return ThemePreviewRenderData(text="game-fallback")

        _resolve_layout_preferred_render = MainWindow._resolve_layout_preferred_render

    element = themes.ThemePreviewElement(
        label="marquee",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="marquee",
        value=None,
        x=0.0,
        y=0.0,
        width=835.0,
        height=225.0,
        layer=10,
        mode="layout_preferred",
    )

    result = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry=object(),
        collection_name="MAME",
        game_entry=object(),
        collection_games=tuple(),
        collection_index=1,
        layout_collection="2 ARCADE GENRES",
    )

    assert result is not None
    assert result.text == "exact-layout"


def test_marquee_slot_does_not_use_generic_fit_within_rect() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="marquee",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="marquee",
        value=None,
        x=0.0,
        y=0.0,
        width=835.0,
        height=225.0,
        layer=10,
        explicit_width=True,
        explicit_height=True,
    )

    assert widget._should_fit_media_rect(element) is False


def test_text_max_width_caps_display_rect() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="title",
        kind="reloadable_scrolling_text",
        tag_name="reloadableScrollingText",
        slot_name="title",
        value=None,
        x=965.0,
        y=30.0,
        width=900.0,
        height=60.0,
        layer=19,
        max_width=500.0,
        font_size=50.0,
        load_font_size=50.0,
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        "TOURNAMENT ARKANOID (US) 1987 TAITO AMERICA CORPORATION",
    )

    assert round(rect.width(), 2) == 500.00


def test_text_max_width_uses_authored_box_even_for_shorter_text() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="manufacturer",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="manufacturer",
        value=None,
        x=965.0,
        y=120.0,
        width=260.0,
        height=48.0,
        layer=19,
        max_width=500.0,
        font_size=42.0,
        load_font_size=42.0,
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        "TAITO AMERICA CORP",
    )

    assert round(rect.width(), 2) == 500.00


def test_event_animation_hides_on_scroll_and_restores_after_highlight(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    text_element = themes.ThemePreviewElement(
        label="title",
        kind="reloadable_scrolling_text",
        tag_name="reloadableScrollingText",
        slot_name="title",
        value=None,
        x=965.0,
        y=30.0,
        width=500.0,
        height=60.0,
        layer=19,
        alpha=0.0,
        event_anim_sets=(
            ("menuscroll", None, ((0.01, (("alpha", 1.0, 0.0, "linear"),)),)),
            (
                "highlightenter",
                "1",
                (
                    (0.4, (("nop", None, None, "linear"),)),
                    (0.01, (("alpha", 0.0, 1.0, "linear"),)),
                ),
            ),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="CoinOPS",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(text_element,),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)

    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 10.0)
    widget._start_event_animation("menuscroll")
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 10.02)
    widget._on_event_anim_tick()
    assert widget._effective_preview_animation_values(text_element)["alpha"] == 0.0

    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 11.0)
    widget._start_event_animation("highlightenter")
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 11.2)
    widget._on_event_anim_tick()
    assert widget._effective_preview_animation_values(text_element).get("alpha", 0.0) == 0.0
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 11.45)
    widget._on_event_anim_tick()
    assert widget._effective_preview_animation_values(text_element)["alpha"] == 1.0


def test_stop_wheel_animation_clears_scroll_event_values_before_idle_restart() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    element = themes.ThemePreviewElement(
        label="shadow",
        kind="image",
        tag_name="image",
        slot_name=None,
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
        layer=10,
        alpha=0.8,
        event_anim_sets=(
            ("menuscroll", None, ((0.1, (("alpha", 0.8, 0.8, "linear"),)),)),
            ("highlightenter", None, ((0.1, (("alpha", 0.8, 0.2, "linear"),)),)),
        ),
        idle_anim_sets=(
            (1.0, (("alpha", 0.8, 0.0, "linear"),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Fan Art Magazine",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=768.0,
        canvas_height=1366.0,
        elements=(element,),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget._wheel_anim_active = True
    widget._event_anim_name = "menuscroll"
    widget._event_anim_values = {element: {"alpha": 0.8}}

    widget.stop_wheel_animation()

    assert widget._wheel_anim_active is False
    assert widget._event_anim_name == "highlightenter"
    assert widget._idle_anim_timer.isActive() is True


def test_on_wheel_animation_finished_restarts_widget_highlight_restore() -> None:
    class FakeThemesPreview:
        def __init__(self) -> None:
            self._wheel_anim_total_games = 5
            self._wheel_anim_start_game_0 = 0
            self._wheel_anim_target_advance = 2
            self.stopped = False

        def stop_wheel_animation(self) -> None:
            self.stopped = True

    class FakeCombo:
        def __init__(self) -> None:
            self._index = 0

        def count(self) -> int:
            return 10

        def blockSignals(self, value: bool) -> None:
            return None

        def setCurrentIndex(self, index: int) -> None:
            self._index = index

        def currentData(self):
            return None

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_wheel_spinning = True
            self._theme_preview_video_sessions = {}
            self.themes_preview = FakeThemesPreview()
            self.themes_game_filter = FakeCombo()
            self._selected_theme_game_key = None
            self._theme_preview_previous_stopped_game_key = None
            self._theme_preview_last_stopped_game_key = None
            self._theme_preview = object()
            self.render_data_set = False
            self.scheduled = False

        def _apply_theme_preview_session_state(self, session) -> None:
            return None

        def _build_theme_render_data(self, preview):
            return {}

        def _set_theme_preview_render_data(self, data, transition=False) -> None:
            self.render_data_set = True

        def _schedule_theme_preview_cycle(self) -> None:
            self.scheduled = True

    fake = FakeMainWindow()
    MainWindow._on_wheel_animation_finished(fake)

    assert fake.themes_preview.stopped is True
    assert fake.render_data_set is True
    assert fake.scheduled is True


def test_vertical_scrolling_text_uses_full_wrapped_content_height(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    widget._idle_anim_start_ms = 0.0
    element = themes.ThemePreviewElement(
        label="story",
        kind="reloadable_scrolling_text",
        tag_name="reloadableScrollingText",
        slot_name="story",
        value=None,
        x=1238.0,
        y=670.0,
        width=500.0,
        height=360.0,
        layer=19,
        explicit_width=True,
        explicit_height=True,
        scroll_direction="vertical",
        scroll_speed=15.0,
        scroll_start_time=0.0,
        scroll_end_time=0.0,
        text_alignment="justified",
        font_size=32.0,
        load_font_size=32.0,
    )
    image = QImage(800, 800, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setFont(widget._preview_font_for_element(element, 1.0, 1.0))
    long_text = ("This is a long CoinOPS story paragraph. " * 80).strip()
    captured: dict[str, QRectF] = {}
    original_draw_text = QPainter.drawText

    def fake_draw_text(self, *args):
        if args and isinstance(args[0], QRectF):
            captured["rect"] = QRectF(args[0])
            return None
        return original_draw_text(self, *args)

    monkeypatch.setattr(QPainter, "drawText", fake_draw_text)
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 5.0)
    widget._draw_scrolling_multiline_text(
        painter,
        element,
        QRectF(0.0, 0.0, 500.0, 360.0),
        QRectF(0.0, 0.0, 500.0, 360.0),
        long_text,
        1.0,
        1.0,
    )
    painter.end()

    assert "rect" in captured
    assert captured["rect"].height() > 360.0


def test_theme_preview_wait_interval_uses_configured_attract_next_time(tmp_path: Path) -> None:
    target = tmp_path
    settings_dir = target / "appdata" / "retrofe"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.conf").write_text("attractModeNextTime = 25\n", encoding="utf-8")

    class FakeMainWindow:
        def __init__(self, target_dir: Path) -> None:
            self._theme_preview = None
            self._target_dir_value = target_dir

        def _target_dir(self) -> Path:
            return self._target_dir_value

    fake = FakeMainWindow(target)
    wait_ms = MainWindow._theme_preview_wait_interval_ms(fake)
    assert wait_ms == 25000


def test_theme_preview_video_frame_updates_pixmap_from_valid_frame() -> None:
    _ensure_app()
    element = themes.ThemePreviewElement(
        label="video",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=320.0,
        height=180.0,
        layer=5,
    )

    class FakeFrame:
        def isValid(self) -> bool:
            return True

        def toImage(self) -> QImage:
            image = QImage(8, 8, QImage.Format.Format_RGB32)
            image.fill(0xFF00FF00)
            return image

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_render_data = {element: ThemePreviewRenderData(video_path=Path("video.mp4"))}

    fake = FakeMainWindow()
    MainWindow._handle_theme_preview_video_frame(fake, element, FakeFrame())
    updated = fake._theme_preview_render_data[element]
    assert updated.pixmap is not None
    assert not updated.pixmap.isNull()


def test_theme_preview_loaded_media_does_not_auto_seek() -> None:
    class FakePlayer:
        def __init__(self) -> None:
            self.position_calls: list[int] = []
            self.play_calls = 0

        def setPosition(self, value: int) -> None:
            self.position_calls.append(value)

        def play(self) -> None:
            self.play_calls += 1

    session = ThemePreviewVideoSession(
        element=themes.ThemePreviewElement(
            label="video",
            kind="reloadable_video",
            tag_name="reloadableVideo",
            slot_name="screenshot",
            value=None,
            x=0.0,
            y=0.0,
            width=320.0,
            height=180.0,
            layer=5,
        ),
        video_path=Path("video.mp4"),
        player=FakePlayer(),
        audio_output=object(),
        video_sink=object(),
    )

    class FakeMainWindow:
        _theme_preview_animation_enabled = True

        def __init__(self) -> None:
            self._theme_preview_video_sessions = {session.element: session}

    fake = FakeMainWindow()

    MainWindow._handle_theme_preview_video_status_changed(
        fake,
        session.element,
        MainWindow.__dict__["_handle_theme_preview_video_status_changed"].__globals__["QMediaPlayer"].MediaStatus.LoadedMedia,
    )

    assert session.initial_seek_done is True
    assert session.player.position_calls == []


def test_theme_preview_pixmap_from_frame_prefers_paint_when_available() -> None:
    _ensure_app()

    class FakeFrame:
        def __init__(self) -> None:
            self.painted = False

        def isValid(self) -> bool:
            return True

        def width(self) -> int:
            return 6

        def height(self) -> int:
            return 4

        def paint(self, painter: QPainter, rect: QRectF, options) -> None:
            self.painted = True
            painter.fillRect(rect, 0xFF00FF00)

        def toImage(self) -> QImage:
            image = QImage(6, 4, QImage.Format.Format_RGB32)
            image.fill(0xFFFF0000)
            return image

    frame = FakeFrame()
    pixmap = MainWindow._theme_preview_pixmap_from_frame(frame)

    assert frame.painted is True
    assert pixmap is not None
    assert not pixmap.isNull()
    assert pixmap.size().width() == 6
    assert pixmap.size().height() == 4


def test_change_screen_leaving_themes_stops_and_disposes_preview_sessions() -> None:
    class FakeStack:
        def __init__(self) -> None:
            self._index = THEMES_SCREEN

        def currentIndex(self) -> int:
            return self._index

        def setCurrentIndex(self, index: int) -> None:
            self._index = index

    class FakeButton:
        def __init__(self) -> None:
            self.checked = None

        def setChecked(self, checked: bool) -> None:
            self.checked = checked

    class FakeMainWindow:
        def __init__(self) -> None:
            self.stack = FakeStack()
            self.settings_nav_button = FakeButton()
            self.tweaks_nav_button = FakeButton()
            self.base_components_nav_button = FakeButton()
            self.game_packs_nav_button = FakeButton()
            self.bitlcd_nav_button = FakeButton()
            self.optional_components_nav_button = FakeButton()
            self.queue_nav_button = FakeButton()
            self.games_nav_button = FakeButton()
            self.collections_nav_button = FakeButton()
            self.themes_nav_button = FakeButton()
            self.logs_nav_button = FakeButton()
            self._defer_screen_refresh = True
            self.stopped = False
            self.disposed = False

        def _stop_theme_preview_animation(self) -> None:
            self.stopped = True

        def _dispose_all_theme_preview_video_sessions(self) -> None:
            self.disposed = True

    fake = FakeMainWindow()

    MainWindow._change_screen(fake, GAMES_SCREEN)

    assert fake.stopped is True
    assert fake.disposed is True
    assert fake.stack.currentIndex() == GAMES_SCREEN


def test_preview_content_rect_reserves_bottom_space_for_action_row() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    preview = themes.ThemeLayoutPreview(
        theme_name="Test",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=tuple(),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    rect = widget._preview_content_rect(QRectF(0.0, 0.0, 800.0, 600.0))
    assert rect.height() < (600.0 - 36.0)


def test_theme_preview_next_requested_triggers_random_advance_when_animating() -> None:
    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_animation_enabled = True
            self._theme_preview = object()
            self._selected_theme_collection_name = "MAME"
            self.called = False

        def _theme_games_for_collection(self, collection_name: str):
            return (object(), object())

        def _trigger_theme_preview_random_advance(self) -> None:
            self.called = True

    fake = FakeMainWindow()
    fake.themes_collection_filter = type("Combo", (), {"currentData": lambda self: "MAME"})()
    MainWindow._handle_theme_preview_next_requested(fake)
    assert fake.called is True


def test_trigger_theme_preview_random_advance_aligns_wheel_target_with_visible_spin(monkeypatch) -> None:
    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = type(
                "Preview",
                (),
                {
                    "elements": (
                        themes.ThemePreviewElement(
                            label="logo",
                            kind="menu",
                            tag_name="menu",
                            slot_name="logo",
                            value=None,
                            x=0.0,
                            y=0.0,
                            width=100.0,
                            height=100.0,
                            layer=1,
                        ),
                    )
                },
            )()
            self._theme_preview_wheel_spinning = False
            self._theme_preview_cycle_timer = type("Timer", (), {"stop": lambda self: None})()
            self._selected_theme_collection_name = "MAME"
            self.themes_collection_filter = type("Combo", (), {"currentData": lambda self: "MAME"})()
            self.themes_game_filter = type("Combo", (), {"currentIndex": lambda self: 1})()
            self.called_with: tuple[int, int | None] | None = None

        def _theme_games_for_collection(self, collection_name: str):
            return tuple(
                GameManifestEntry(game_name=f"G{i}", collection_name="MAME", rom_path=f"g{i}.zip")
                for i in range(50)
            )

        def _start_wheel_animation(self, advance_count: int, *, target_offset: int | None = None) -> None:
            self.called_with = (advance_count, target_offset)

        def _jump_theme_preview_to_index(self, zero_index: int) -> None:
            raise AssertionError("wheel path should be used")

    monkeypatch.setattr("onesauce_companion.ui.main_window.random.randint", lambda a, b: 37)
    fake = FakeMainWindow()

    MainWindow._trigger_theme_preview_random_advance(fake)

    assert fake.called_with == (20, None)


def test_resolve_common_theme_render_uses_default_folder_fallback(tmp_path: Path) -> None:
    _ensure_app()
    theme_root = tmp_path / "base_assets" / "layouts" / "Fan Art Magazine"
    default_dir = theme_root / "collections" / "_common" / "medium_artwork" / "cabinet" / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFFFF0000)
    assert image.save(str(default_dir / "Arcade FF Dir Crop.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="Fan Art Magazine",
        root_dir=theme_root,
        layout_path=theme_root / "layout.xml",
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=("cabinet",),
    )
    game_entry = GameManifestEntry(game_name="Body Slam", collection_name="MAME", rom_path="bslam.zip")

    class FakeMainWindow:
        pass

    result = MainWindow._resolve_common_theme_render(FakeMainWindow(), theme_entry, "cabinet", game_entry, "MAME")

    assert result is not None
    assert result.pixmap is not None
    assert not result.pixmap.isNull()


def test_preferred_default_common_media_files_prefers_marquee_ready_cabinet_variants(tmp_path: Path) -> None:
    cabinet_dir = tmp_path / "cabinet"
    cabinet_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "Arcade FF Dir Crop.png",
        "Arcade FF DirCAPCOMVSSNK Crop Marquee.png",
        "Arcade FF DirML Crop Marquee.png",
        "Arcade FF DirSF Crop Marquee.png",
    ):
        image = QImage(4, 4, QImage.Format.Format_ARGB32)
        image.fill(0xFFFFFFFF)
        assert image.save(str(cabinet_dir / name))

    ordered = MainWindow.__dict__["_resolve_common_theme_render"].__globals__["_preferred_default_common_media_files"](
        "cabinet",
        cabinet_dir,
        {".png"},
    )

    assert ordered[0].name == "Arcade FF DirSF Crop Marquee.png"


def test_start_wheel_animation_passes_extra_menu_groups_to_preview() -> None:
    entry_a = GameManifestEntry(game_name="A", collection_name="MAME", rom_path="a.zip")
    entry_b = GameManifestEntry(game_name="B", collection_name="MAME", rom_path="b.zip")

    class FakeThemesPreview:
        def __init__(self) -> None:
            self.called: dict[str, object] | None = None

        def start_wheel_animation(self, slot_elements, logos, sel_idx, start_game_0, advance_count, total_games, duration_ms, target_advance=None, extra_groups=None):
            self.called = {
                "slot_elements": slot_elements,
                "logos": logos,
                "sel_idx": sel_idx,
                "extra_groups": extra_groups,
                "advance_count": advance_count,
            }

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = themes.ThemeLayoutPreview(
                theme_name="Fan Art Magazine",
                selected_collection="MAME",
                root_layout_path=None,
                active_layout_path=None,
                using_collection_override=False,
                canvas_width=768.0,
                canvas_height=1366.0,
                    elements=(
                        themes.ThemePreviewElement("logo 1", "menu", "menu", "logo", None, 100.0, 100.0, 100.0, 100.0, 1, menu_position=1, menu_selected_position=2),
                        themes.ThemePreviewElement("logo sel", "menu", "menu", "logo", None, 100.0, 200.0, 120.0, 120.0, 2, selected=True, menu_position=2, menu_selected_position=2),
                        themes.ThemePreviewElement("separator", "image", "image", None, None, 0.0, 0.0, 10.0, 10.0, 2),
                        themes.ThemePreviewElement("cover 1", "menu", "menu", "artwork_front_s", None, 100.0, 1000.0, 100.0, 150.0, 3, menu_position=1, menu_selected_position=2),
                        themes.ThemePreviewElement("cover sel", "menu", "menu", "artwork_front_s", None, 200.0, 1000.0, 100.0, 150.0, 4, selected=True, menu_position=2, menu_selected_position=2),
                    ),
                collection_override_count=0,
                common_slots=(),
                system_slots=(),
            )
            self._selected_theme_collection_name = "MAME"
            self._theme_entries = []
            self._theme_preview_video_sessions = {}
            self.themes_preview = FakeThemesPreview()
            self.themes_game_filter = type("Combo", (), {"currentIndex": lambda self: 1})()
            self._theme_preview_wheel_spinning = False

        def _theme_games_for_collection(self, collection_name: str):
            return (entry_a, entry_b)

        def _apply_theme_preview_session_state(self, session) -> None:
            return None

        def _resolve_theme_game_media_root(self, game_entry):
            return None

        def _resolve_game_media_path(self, media_root, base_names, slot_key):
            return None

        def _make_wheel_text_pixmap(self, text: str, ref_element):
            pixmap = QPixmap(10, 10)
            pixmap.fill()
            return pixmap

    fake = FakeMainWindow()
    MainWindow._start_wheel_animation(fake, 1)

    assert fake.themes_preview.called is not None
    primary_labels = [element.label for element in fake.themes_preview.called["slot_elements"]]
    assert primary_labels == ["logo 1", "logo sel"]
    extra_groups = fake.themes_preview.called["extra_groups"]
    assert isinstance(extra_groups, list)
    assert len(extra_groups) == 1
    extra_labels = [element.label for element in extra_groups[0][0]]
    assert extra_labels == ["cover 1", "cover sel"]


def test_build_theme_render_data_for_state_scroll_only_filters_to_menu_scroll_reload() -> None:
    reload_element = themes.ThemePreviewElement(
        label="title",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="title",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=30.0,
        layer=1,
        menu_scroll_reload=True,
    )
    static_element = themes.ThemePreviewElement(
        label="cabinet",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="cabinet",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
        layer=2,
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Fan Art Magazine",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=768.0,
        canvas_height=1366.0,
        elements=(reload_element, static_element),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    entry = GameManifestEntry(game_name="Guardian", collection_name="MAME", rom_path="guardian.zip")

    class FakeMainWindow:
        def _target_dir(self):
            return Path("V:/")

        _theme_entries = []

        def _resolve_theme_preview_element_render(self, element, theme_entry, selected_collection, game_entry, collection_games, collection_index, layout_collection=None):
            return ThemePreviewRenderData(text=element.label)

    fake = FakeMainWindow()

    render_data = MainWindow._build_theme_render_data_for_state(
        fake,
        preview,
        "MAME",
        entry,
        (entry,),
        1,
        scroll_only=True,
    )

    assert render_data == {reload_element: ThemePreviewRenderData(text="title")}


def test_handle_theme_preview_scroll_index_changed_updates_only_menu_scroll_reload_elements() -> None:
    reload_element = themes.ThemePreviewElement(
        label="title",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="title",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=30.0,
        layer=1,
        menu_scroll_reload=True,
    )
    static_element = themes.ThemePreviewElement(
        label="cabinet",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="cabinet",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
        layer=2,
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Fan Art Magazine",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=768.0,
        canvas_height=1366.0,
        elements=(reload_element, static_element),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = preview
            self._theme_preview_wheel_spinning = True
            self._theme_preview_render_data = {
                static_element: ThemePreviewRenderData(text="static"),
                reload_element: ThemePreviewRenderData(text="old"),
            }
            self.updated: tuple[dict[themes.ThemePreviewElement, ThemePreviewRenderData], bool] | None = None

        def _build_theme_scroll_render_data(self, active_preview, target_zero_index: int):
            assert active_preview is preview
            assert target_zero_index == 3
            return {reload_element: ThemePreviewRenderData(text="new")}

        def _set_theme_preview_render_data(self, data, *, transition=True) -> None:
            self.updated = (dict(data), transition)

    fake = FakeMainWindow()

    MainWindow._handle_theme_preview_scroll_index_changed(fake, 3)

    assert fake.updated is not None
    merged, transition = fake.updated
    assert transition is False
    assert merged == {
        static_element: ThemePreviewRenderData(text="static"),
        reload_element: ThemePreviewRenderData(text="new"),
    }


def test_artwork_front_with_stretch_width_and_min_height_uses_cover_style_scaling() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="background",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="artwork_front",
        value=None,
        x=0.0,
        y=0.0,
        width=768.0,
        height=200.0,
        layer=2,
        explicit_width=True,
        explicit_height=False,
        min_height=1366.0,
    )

    assert widget._should_expand_width_constrained_media(element) is True


def test_theme_preview_previous_requested_restores_last_stopped_game_when_animating() -> None:
    entry_a = GameManifestEntry(game_name="A", collection_name="MAME", rom_path="a.zip")
    entry_b = GameManifestEntry(game_name="B", collection_name="MAME", rom_path="b.zip")

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_animation_enabled = True
            self._theme_preview_previous_stopped_game_key = entry_a.key
            self._selected_theme_collection_name = "MAME"
            self.themes_collection_filter = type("Combo", (), {"currentData": lambda self: "MAME"})()
            self.jump_target: int | None = None

        def _theme_games_for_collection(self, collection_name: str):
            return (entry_a, entry_b)

        def _jump_theme_preview_to_index(self, zero_index: int) -> None:
            self.jump_target = zero_index

    fake = FakeMainWindow()
    MainWindow._handle_theme_preview_previous_requested(fake)
    assert fake.jump_target == 0


def test_panning_draw_rect_moves_when_animation_is_enabled(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    pixmap = QPixmap(500, 1200)
    pixmap.fill()
    element = themes.ThemePreviewElement(
        label="artwork",
        kind="reloadable_panning_image",
        tag_name="reloadablePanningImage",
        slot_name="artwork_front",
        value=None,
        x=875.0,
        y=0.0,
        width=1050.0,
        height=1100.0,
        layer=2,
        pan_speed=15.0,
        pan_threshold=0.0,
        zoom_scale_to=1.8,
    )
    full_rect = QRectF(875.0, 0.0, 1050.0, 1100.0)

    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 10.0)
    _, rect_a = widget._panning_draw_rect(pixmap, element, full_rect)
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 12.0)
    _, rect_b = widget._panning_draw_rect(pixmap, element, full_rect)

    assert round(rect_a.top(), 2) != round(rect_b.top(), 2)
