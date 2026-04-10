from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFontMetricsF, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from onesauce_companion.services.games import GameManifestEntry
from onesauce_companion.services import themes
from onesauce_companion.ui.main_window import (
    GAMES_SCREEN,
    THEMES_SCREEN,
    IMAGE_MEDIA_SUFFIXES,
    MainWindow,
    ThemeLayoutPreviewWidget,
    ThemePreviewRenderData,
    ThemePreviewVideoSession,
    _find_first_collection_video,
    _find_matching_media_file,
    _game_name_candidates,
)


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


def _amiga_memories_font_path() -> str:
    path = Path(r"V:\base_assets\layouts\Amiga Memories\fonts\OpenSans.ttf")
    if not path.exists():
        pytest.skip("Reference font path is unavailable in this environment")
    return str(path)


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


def test_build_theme_layout_preview_uses_luna_sync_layout_alias_when_override_folder_is_missing(tmp_path: Path) -> None:
    theme_dir = tmp_path / "base_assets" / "layouts" / "LUNA OG"
    (theme_dir / "collections" / "1 Fighting" / "layout").mkdir(parents=True, exist_ok=True)
    (theme_dir / "collections" / "1 Fighting" / "layout" / "layout.xml").write_text(
        """<layout width="1920" height="1080">
  <reloadableImage type="logo" x="0" y="0" width="100" height="100" />
</layout>
""",
        encoding="utf-8",
    )
    (theme_dir / "collections" / "luna_sync_layouts.sh").write_text(
        'rsync -haP "1 Fighting/layout" "02 ARCADE ALL"/\n',
        encoding="utf-8",
    )

    catalog = themes.scan_theme_catalog(tmp_path)
    entry = next(item for item in catalog if item.name == "LUNA OG")
    assert "02 ARCADE ALL" in entry.collection_overrides

    preview = themes.build_theme_layout_preview(tmp_path, "LUNA OG", "02 ARCADE ALL", layout_collection_name="02 ARCADE ALL")

    assert preview is not None
    assert preview.active_layout_path == theme_dir / "collections" / "1 Fighting" / "layout" / "layout.xml"


def test_scan_theme_catalog_uses_explicit_lua_wrapper_xml_before_probe_order(tmp_path: Path) -> None:
    theme_dir = tmp_path / "base_assets" / "layouts" / "LUNA OG"
    theme_dir.mkdir(parents=True, exist_ok=True)
    (theme_dir / "layout.lua").write_text(
        'local luna = require("luna")\n\nfunction build(pageBuilder)\n  luna.build(pageBuilder, "collections/arcade_systems.xml")\nend\n',
        encoding="utf-8",
    )
    for name in ("non_arcade_games.xml", "arcade_games.xml", "arcade_systems.xml", "non_arcade_systems.xml"):
        (theme_dir / "collections").mkdir(parents=True, exist_ok=True)
        (theme_dir / "collections" / name).write_text(
            f'<layout width="1920" height="1080"><image src="{name}" x="0" y="0" width="10" height="10" /></layout>',
            encoding="utf-8",
        )

    catalog = themes.scan_theme_catalog(tmp_path)
    entry = next(item for item in catalog if item.name == "LUNA OG")

    assert entry.layout_path == theme_dir / "collections" / "arcade_systems.xml"


def test_build_theme_layout_preview_materializes_view_refs_from_referenced_media(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "View Ref Theme",
        """<layout width="1920" height="1080">
  <reloadableVideo id="game_video" imageType="screenshot" x="200" y="150" width="400" height="300" alpha="0" />
  <view ref="game_video" id="upper_screen_full" alpha="1"
   transform="quad (209, 365, 0, 0), (546, 273, 1, 0), (316, 654, 0, 1), (646, 532, 1, 1), 50"/>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "View Ref Theme")

    assert preview is not None
    elements = [item for item in preview.elements if item.kind == "reloadable_video"]
    assert len(elements) == 2
    base = next(item for item in elements if item.elem_id == "game_video")
    view = next(item for item in elements if item.label == "upper_screen_full")
    assert base.slot_name == "screenshot"
    assert view.slot_name == "screenshot"
    assert len(view.transform_points) == 4
    assert view.alpha == 1.0


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


def test_build_theme_layout_preview_preserves_transparent_custom_menu_slots(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Transparent Menu Theme",
        """<layout width="768" height="1366">
  <menu type="custom" imageType="artwork_front_s">
    <itemDefaults x="center" y="1100" xOrigin="center" yOrigin="top" width="200" minHeight="266" />
    <item alpha="0" />
    <item xOffset="200" />
    <item alpha="0" selected="true" />
    <item xOffset="-200" alpha="0" />
  </menu>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Transparent Menu Theme")

    assert preview is not None
    menu_elements = [element for element in preview.elements if element.kind == "menu"]
    assert len(menu_elements) == 4
    assert sum(1 for element in menu_elements if element.alpha == 0.0) == 3
    assert any(element.selected for element in menu_elements)


def test_build_theme_layout_preview_preserves_custom_menu_source_order(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Custom Menu Order Theme",
        """<layout width="768" height="1366">
  <menu type="custom" imageType="artwork_front_s">
    <itemDefaults x="center" y="1100" xOrigin="center" yOrigin="top" width="200" minHeight="266" layer="6"/>
    <item alpha="0"/>
    <item layer="7"/>
    <item xOffset="200"/>
    <item alpha="0" selected="true"/>
    <item xOffset="-200"/>
  </menu>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Custom Menu Order Theme")

    assert preview is not None
    menu_elements = [element for element in preview.elements if element.kind == "menu"]
    assert [element.menu_position for element in menu_elements] == [1, 2, 3, 4, 5]


def test_build_theme_layout_preview_uses_visible_overlapping_slot_for_hidden_selected_custom_menu(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Visible Selected Fallback Theme",
        """<layout width="768" height="1366">
  <menu type="custom" imageType="artwork_front_s">
    <itemDefaults x="center" y="1100" xOrigin="center" yOrigin="top" width="200" minHeight="266" layer="6"/>
    <item alpha="0"/>
    <item layer="7"/>
    <item xOffset="200"/>
    <item alpha="0" selected="true"/>
    <item xOffset="-200"/>
  </menu>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Visible Selected Fallback Theme")

    assert preview is not None
    menu_elements = [element for element in preview.elements if element.kind == "menu"]
    selected = [element for element in menu_elements if element.selected]
    assert len(selected) == 1
    assert selected[0].menu_position == 2
    assert all(element.menu_selected_position == 2 for element in menu_elements)


def test_find_matching_media_file_uses_first_variant_from_matched_nested_directory(tmp_path: Path) -> None:
    background_dir = tmp_path / "background"
    variant_dir = background_dir / "1 COLLECTIONS"
    variant_dir.mkdir(parents=True, exist_ok=True)
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(variant_dir / "1.jpg"))
    assert image.save(str(variant_dir / "2.jpg"))

    resolved = _find_matching_media_file(background_dir, ("1 COLLECTIONS",), IMAGE_MEDIA_SUFFIXES)

    assert resolved == variant_dir / "1.jpg"


def test_build_theme_layout_preview_resolves_stretch_min_height_constraint(tmp_path: Path) -> None:
    theme_dir = _write_theme_layout(
        tmp_path,
        "Stretch Constraint Theme",
        """<layout width="768" height="1366">
  <reloadableImage type="artwork_front" src="images/bg.png" xOrigin="center" yOrigin="center" x="center" y="center" width="stretch" minHeight="stretch" />
</layout>
""",
    )
    (theme_dir / "images").mkdir(parents=True, exist_ok=True)
    image = QImage(400, 300, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    assert image.save(str(theme_dir / "images" / "bg.png"))

    preview = themes.build_theme_layout_preview(tmp_path, "Stretch Constraint Theme")

    assert preview is not None
    element = next(item for item in preview.elements if item.slot_name == "artwork_front")
    assert element.min_height == 1366.0


def test_build_theme_layout_preview_width_only_menu_preserves_authored_width_before_media_load(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Width Only Menu Theme",
        """<layout width="768" height="1366">
  <menu type="custom" imageType="artwork_front_s">
    <itemDefaults x="center" y="1100" xOrigin="center" yOrigin="top" width="200" minHeight="266" />
    <item />
    <item selected="true" alpha="0" />
    <item xOffset="-200" />
  </menu>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Width Only Menu Theme")

    assert preview is not None
    elements = [item for item in preview.elements if item.kind == "menu"]
    assert elements
    assert all(element.width == 200.0 for element in elements)
    assert all(element.min_height == 266.0 for element in elements)


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
        font_path=_amiga_memories_font_path(),
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
        font_path=_amiga_memories_font_path(),
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


def test_build_theme_layout_preview_preserves_idle_alpha_without_explicit_from(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Idle Alpha Theme",
        """<layout width="1920" height="1080">
  <image src="images/shadow.png" alpha="0">
    <onMenuIdle>
      <set duration="1.2">
        <animate type="alpha" to="0"/>
      </set>
    </onMenuIdle>
  </image>
</layout>
""",
    )

    preview = themes.build_theme_layout_preview(tmp_path, "Idle Alpha Theme")

    assert preview is not None
    element = preview.elements[0]
    assert element.idle_anim_sets
    duration, steps = element.idle_anim_sets[0]
    assert duration == 1.2
    assert steps[0] == ("alpha", None, 0.0, "linear")


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


def test_media_display_rect_unsized_media_with_max_constraints_fills_constraint_box() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(550, 325)
    pixmap.fill()
    element = themes.ThemePreviewElement(
        label="device",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="device",
        value=None,
        x=770.0,
        y=250.0,
        width=0.0,
        height=0.0,
        layer=7,
        explicit_width=False,
        explicit_height=False,
        max_width=475.0,
        max_height=360.0,
        x_origin="center",
        y_origin="center",
    )

    rect = widget._element_display_rect(
        element,
        QRectF(0.0, 0.0, 960.0, 540.0),
        0.5,
        0.5,
        None,
        render_data=ThemePreviewRenderData(pixmap=pixmap),
        animated_values={},
    )

    assert round(rect.width(), 2) == 237.50
    assert round(rect.height(), 2) == 140.34


def test_build_theme_layout_preview_ignores_lowercase_maxwidth_attribute() -> None:
    xml = """
<layout width="1920" height="1080">
  <reloadableImage type="device" x="770" y="250" xOrigin="center" yOrigin="center" maxwidth="475" maxHeight="360" />
</layout>
""".strip()
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        layout_path = root / "layout.xml"
        layout_path.write_text(xml, encoding="utf-8")
        root_node = themes.ET.fromstring(xml)
        elements: list[themes.ThemePreviewElement] = []
        themes._collect_preview_elements(
            root_node,
            layout_path,
            1920.0,
            1080.0,
            {},
            elements,
        )

    element = next(el for el in elements if (el.slot_name or "").casefold() == "device")
    assert element.max_width is None
    assert element.max_height == 360.0


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
    assert widget._floating_preview_update_timer.interval() == 33


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
    <onEnter>
      <set duration="0.01">
        <animate type="alpha" to="0.8"/>
      </set>
    </onEnter>
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
    assert ("enter", None, (("alpha", 0.8),)) in element.event_anim_targets
    assert ("menuenter", "1", (("alpha", 1.0), ("width", 550.0))) in element.event_anim_targets
    assert ("menuscroll", None, (("alpha", 0.0),)) in element.event_anim_targets


def test_build_theme_layout_preview_preserves_menu_idle_animation_sets(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Idle Menu Theme",
        """<layout width="1920" height="1080">
  <menu type="custom" imageType="artwork_front">
    <itemDefaults x="100" y="200" width="300" height="300" />
    <item selected="true">
      <onIdle>
        <set duration="2.0">
          <animate type="y" to="260" />
        </set>
        <set duration="1.0">
          <animate type="y" to="200" />
        </set>
      </onIdle>
    </item>
  </menu>
</layout>
""",
    )
    preview = themes.build_theme_layout_preview(tmp_path, "Idle Menu Theme", "MAME")

    assert preview is not None
    element = next(item for item in preview.elements if item.kind == "menu")
    assert element.idle_anim_sets == (
        (2.0, (("y", None, 260.0, "linear"),)),
        (1.0, (("y", None, 200.0, "linear"),)),
    )


def test_preview_state_values_apply_on_enter_when_no_menu_event_overrides_exist() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="counter",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="collectionIndex",
        value=None,
        x=1820.0,
        y=1030.0,
        width=100.0,
        height=45.0,
        layer=9,
        alpha=0.0,
        event_anim_targets=(
            ("enter", None, (("alpha", 0.8),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Cyberpunkd",
        selected_collection="Nintendo Game Boy Advance",
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
    assert settled_values["alpha"] == 0.8


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
        _theme_menu_entry_for_element = MainWindow._theme_menu_entry_for_element
        _theme_preview_layout_collection_candidates = MainWindow._theme_preview_layout_collection_candidates

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


def test_layout_mode_prefers_selected_item_collection_before_parent_collection() -> None:
    class FakeMainWindow:
        def _resolve_static_theme_render(self, element):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            return None

        def _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry, *, allow_system_fallback=True):
            if layout_collection == "Neo Geo":
                return ThemePreviewRenderData(text="item-collection")
            if layout_collection == "2 ARCADE GENRES":
                return ThemePreviewRenderData(text="parent-collection")
            return None

        def _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index):
            return None

        _theme_menu_entry_for_element = MainWindow._theme_menu_entry_for_element
        _theme_preview_layout_collection_candidates = MainWindow._theme_preview_layout_collection_candidates

    element = themes.ThemePreviewElement(
        label="eplogo",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="eplogo",
        value=None,
        x=0.0,
        y=0.0,
        width=660.0,
        height=216.0,
        layer=12,
        mode="layout",
    )
    game_entry = GameManifestEntry(game_name="Bang Bang Busters", collection_name="Neo Geo", rom_path="bbbuster.zip")

    result = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry=object(),
        collection_name="2 ARCADE GENRES",
        game_entry=game_entry,
        collection_games=(game_entry,),
        collection_index=1,
        layout_collection="1 ARCADES",
    )

    assert result is not None
    assert result.text == "item-collection"


def test_game_name_candidates_include_plain_title_without_region_suffixes() -> None:
    candidates = _game_name_candidates("Adventure Island (USA).nes")

    assert "Adventure Island (USA).nes" in candidates
    assert "Adventure Island (USA)" in candidates
    assert "Adventure Island" in candidates


def test_find_matching_media_file_matches_plain_title_against_region_tagged_rom_name(tmp_path) -> None:
    media_dir = tmp_path / "artwork_front"
    media_dir.mkdir(parents=True)
    expected = media_dir / "Adventure Island.png"
    expected.write_bytes(b"png")

    match = _find_matching_media_file(
        media_dir,
        _game_name_candidates("Adventure Island (USA).nes"),
        IMAGE_MEDIA_SUFFIXES,
    )

    assert match == expected


def test_systemlayout_mode_prefers_selected_item_collection_before_parent_collection() -> None:
    class FakeMainWindow:
        def _resolve_static_theme_render(self, element):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            return None

        def _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry, *, allow_system_fallback=True):
            assert game_entry is None
            if layout_collection == "Neo Geo":
                return ThemePreviewRenderData(text="item-system")
            if layout_collection == "2 ARCADE GENRES":
                return ThemePreviewRenderData(text="parent-system")
            return None

        def _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index):
            return None

        _theme_menu_entry_for_element = MainWindow._theme_menu_entry_for_element
        _theme_preview_layout_collection_candidates = MainWindow._theme_preview_layout_collection_candidates

    element = themes.ThemePreviewElement(
        label="menu",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="menu",
        value=None,
        x=0.0,
        y=0.0,
        width=435.0,
        height=108.0,
        layer=17,
        mode="systemlayout",
    )
    game_entry = GameManifestEntry(game_name="Bang Bang Busters", collection_name="Neo Geo", rom_path="bbbuster.zip")

    result = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry=object(),
        collection_name="2 ARCADE GENRES",
        game_entry=game_entry,
        collection_games=(game_entry,),
        collection_index=1,
        layout_collection="1 ARCADES",
    )

    assert result is not None
    assert result.text == "item-system"


def test_systemlayout_mode_uses_parent_collection_for_menu_placeholder_entries() -> None:
    class FakeMainWindow:
        def _resolve_static_theme_render(self, element):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            return None

        def _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry, *, allow_system_fallback=True):
            assert game_entry is None
            if layout_collection == "1 COMPUTERS":
                return ThemePreviewRenderData(text="parent-system")
            if layout_collection == "Commodore 64":
                return ThemePreviewRenderData(text="child-system")
            return None

        def _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index):
            return None

        _theme_menu_entry_for_element = MainWindow._theme_menu_entry_for_element
        _theme_preview_layout_collection_candidates = MainWindow._theme_preview_layout_collection_candidates

    element = themes.ThemePreviewElement(
        label="logo",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=705.0,
        height=200.0,
        layer=13,
        mode="systemlayout",
    )
    game_entry = GameManifestEntry(game_name="Commodore 64", collection_name="Commodore 64", rom_path="Commodore 64")

    result = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry=object(),
        collection_name="1 COMPUTERS",
        game_entry=game_entry,
        collection_games=(game_entry,),
        collection_index=1,
        layout_collection="1 COMPUTERS",
    )

    assert result is not None
    assert result.text == "parent-system"


def test_systemlayout_mode_placeholder_does_not_fall_through_to_game_logo_render() -> None:
    class FakeMainWindow:
        def _resolve_static_theme_render(self, element):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            return None

        def _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry, *, allow_system_fallback=True):
            return None

        def _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index):
            return ThemePreviewRenderData(text="wrong-child-logo")

        _theme_menu_entry_for_element = MainWindow._theme_menu_entry_for_element
        _theme_preview_layout_collection_candidates = MainWindow._theme_preview_layout_collection_candidates

    element = themes.ThemePreviewElement(
        label="logo",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=705.0,
        height=200.0,
        layer=13,
        mode="systemlayout",
    )
    game_entry = GameManifestEntry(game_name="Commodore 64", collection_name="Commodore 64", rom_path="Commodore 64")

    result = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry=object(),
        collection_name="1 COMPUTERS",
        game_entry=game_entry,
        collection_games=(game_entry,),
        collection_index=1,
        layout_collection="1 COMPUTERS",
    )

    assert result is None


def test_settled_preview_applies_menuexit_for_inactive_menu_group() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    fanart = themes.ThemePreviewElement(
        label="fanart",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="fanart",
        value=None,
        x=0.0,
        y=0.0,
        width=1920.0,
        height=1080.0,
        layer=3,
        alpha=1.0,
        event_anim_targets=(("menuexit", "0", (("alpha", 0.0),)),),
    )
    system = themes.ThemePreviewElement(
        label="system",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="system",
        value=None,
        x=0.0,
        y=0.0,
        width=1920.0,
        height=1080.0,
        layer=3,
        alpha=0.0,
        event_anim_targets=(("menuenter", "1", (("alpha", 1.0),)),),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="CoinOPS",
        selected_collection="Nintendo Entertainment System",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=True,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(fanart, system),
        collection_override_count=1,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)

    fanart_values = widget._effective_preview_animation_values(fanart)
    system_values = widget._effective_preview_animation_values(system)

    assert fanart_values["alpha"] == 0.0
    assert system_values["alpha"] == 1.0


def test_settled_preview_does_not_apply_bare_menuexit_without_menu_condition() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="logoSlot",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=50.0,
        layer=5,
        event_anim_targets=(("menuexit", None, (("alpha", 0.0),)),),
    )

    values = widget._effective_preview_animation_values(element)

    assert "alpha" not in values


def test_wheel_motion_preserves_settled_menuenter_state_under_menuscroll() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    video = themes.ThemePreviewElement(
        label="screenshot",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=1920.0,
        height=1080.0,
        layer=5,
        alpha=1.0,
        event_anim_targets=(
            ("menuenter", "1", (("width", 1000.0), ("xoffset", -300.0))),
            ("menuscroll", "1", (("alpha", 1.0),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="CoinOPS",
        selected_collection="Commodore VIC-20",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(video,),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget._wheel_anim_active = True

    values = widget._effective_preview_animation_values(video)

    assert values["width"] == 1000.0
    assert values["xoffset"] == -300.0
    assert values["alpha"] == 1.0


def test_parser_preserves_onmenuexit_event_targets(tmp_path: Path) -> None:
    _write_theme_layout(
        tmp_path,
        "Inline",
        """
<layout width="1920" height="1080">
  <reloadableImage type="fanart" alpha="1" width="1920" height="1080">
    <onMenuExit menuIndex="0">
      <set duration="0.2">
        <animate type="alpha" to="0"/>
      </set>
    </onMenuExit>
  </reloadableImage>
</layout>
""",
    )
    preview = themes.build_theme_layout_preview(tmp_path, "Inline")

    element = next(item for item in preview.elements if item.slot_name == "fanart")
    assert ("menuexit", "0", (("alpha", 0.0),)) in element.event_anim_targets
    assert any(event_name == "menuexit" and menu_index == "0" for event_name, menu_index, _sets in element.event_anim_sets)


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


def test_width_only_video_with_max_height_fills_height_cap() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(640, 480)
    pixmap.fill(Qt.GlobalColor.white)
    element = themes.ThemePreviewElement(
        label="screenshot",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=185.0,
        y=378.0,
        width=600.0,
        height=360.0,
        layer=5,
        explicit_width=True,
        explicit_height=False,
        max_width=600.0,
        max_height=433.0,
        x_origin="center",
        y_origin="center",
    )
    full_rect = QRectF(0.0, 0.0, 541.25, 433.0)

    scaled = pixmap.scaled(QSize(32767, int(round(full_rect.height())) + 1), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    draw_rect = widget._aligned_media_rect(full_rect, scaled, element)

    assert draw_rect.height() >= 432.0


def test_playlist_image_slots_do_not_fit_within_box() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="playlist",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="playlist",
        value=None,
        x=1070.0,
        y=25.0,
        width=350.0,
        height=125.0,
        layer=12,
        explicit_width=True,
        explicit_height=True,
    )

    assert widget._should_fit_media_rect(element) is False


def test_aligned_media_rect_centers_overflow_without_explicit_origin() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(400, 175)
    pixmap.fill(Qt.GlobalColor.white)
    element = themes.ThemePreviewElement(
        label="playlist",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="playlist",
        value=None,
        x=1070.0,
        y=25.0,
        width=350.0,
        height=125.0,
        layer=12,
        explicit_width=True,
        explicit_height=True,
    )
    bounds = QRectF(0.0, 0.0, 350.0, 125.0)

    rect = widget._aligned_media_rect(bounds, pixmap, element)

    assert rect.x() < 0.0
    assert rect.y() < 0.0
    assert abs(rect.center().x() - bounds.center().x()) < 0.001
    assert abs(rect.center().y() - bounds.center().y()) < 0.001


def test_media_display_rect_for_width_only_video_with_max_height_uses_height_cap() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(640, 480)
    pixmap.fill(Qt.GlobalColor.white)
    element = themes.ThemePreviewElement(
        label="backgroundVideo",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=1000.0,
        height=1080.0,
        layer=5,
        explicit_width=True,
        explicit_height=False,
        max_height=1080.0,
    )
    render_data = ThemePreviewRenderData(pixmap=pixmap)

    rect = widget._media_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        render_data,
        animated_values=None,
    )

    assert rect is not None
    assert rect.height() >= 1079.0
    assert rect.width() > 1000.0


def test_media_display_rect_honors_position_animation_for_fixed_size_media() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    pixmap = QPixmap(897, 972)
    pixmap.fill(Qt.GlobalColor.white)
    element = themes.ThemePreviewElement(
        label="Cafe80sTV",
        kind="image",
        tag_name="image",
        slot_name=None,
        value=None,
        x=-1000.0,
        y=-50.0,
        width=897.0,
        height=972.0,
        layer=6,
        anchor_x=-1000.0,
        anchor_y=-50.0,
        explicit_width=True,
        explicit_height=True,
    )
    render_data = ThemePreviewRenderData(pixmap=pixmap)

    rect = widget._media_display_rect(
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        1.0,
        1.0,
        render_data,
        animated_values={"x": 200.0},
    )

    assert rect is not None
    assert rect.x() == pytest.approx(200.0)
    assert rect.y() == pytest.approx(-50.0)
    assert rect.width() == pytest.approx(897.0)
    assert rect.height() == pytest.approx(972.0)


def test_menu_without_logo_image_falls_back_to_game_name_text() -> None:
    class FakeMainWindow:
        def _resolve_static_theme_render(self, element):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, game_entry, collection_games, collection_index):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            return None

        def _resolve_layout_theme_render(self, element, theme_entry, layout_collection, game_entry, *, allow_system_fallback=True):
            return None

        def _resolve_game_theme_render(self, element, theme_entry, collection_name, game_entry, collection_games, collection_index):
            return MainWindow._resolve_game_theme_render(
                self,
                element,
                theme_entry,
                collection_name,
                game_entry,
                collection_games,
                collection_index,
            )

        def _resolve_theme_game_media_root(self, game_entry):
            return None

        def _resolve_game_media_path(self, media_root, base_names, slot_key):
            return None

        def _resolve_game_video_path(self, media_root, base_names, slot_key):
            return None

        def _resolve_common_theme_render(self, theme_entry, slot_key, game_entry, collection_name, common_root=None):
            return None

        def _resolve_common_layout_video(self, theme_entry, slot_key, common_root=None):
            return None

        def _theme_menu_entry_for_element(self, element, selected_entry, collection_games, collection_index):
            return selected_entry

        def _target_dir(self):
            return None

    element = themes.ThemePreviewElement(
        label="menu",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=260.0,
        height=120.0,
        layer=18,
    )
    game_entry = GameManifestEntry(game_name="Ghostbusters II (USA).nes", collection_name="Nintendo Entertainment System", rom_path="Ghostbusters II (USA).nes")

    result = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry=None,
        collection_name="Nintendo Entertainment System",
        game_entry=game_entry,
        collection_games=(game_entry,),
        collection_index=1,
        layout_collection=None,
    )

    assert result is not None
    assert result.text == "Ghostbusters II (USA).nes"


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


def test_resolve_theme_preview_text_collection_placeholder_uses_collection_info_conf(tmp_path: Path) -> None:
    info_dir = tmp_path / "appdata" / "retrofe" / "collections" / "Epoch Super Cassette Vision"
    info_dir.mkdir(parents=True, exist_ok=True)
    (info_dir / "info.conf").write_text(
        "manufacturer = Epoch Co.\n"
        "year = 1984\n"
        "genre = Console\n",
        encoding="utf-8",
    )

    class FakeMainWindow:
        def _resolve_theme_game_metadata(self, collection_name, game_entry):
            return None

        def _target_dir(self):
            return tmp_path

    game_entry = GameManifestEntry(
        game_name="Epoch Super Cassette Vision",
        collection_name="Epoch Super Cassette Vision",
        rom_path="Epoch Super Cassette Vision",
        source_pack="Epoch Super Cassette Vision",
        install_collection_name="Epoch Super Cassette Vision",
    )
    year_element = themes.ThemePreviewElement(
        label="year",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="year",
        value=None,
        x=0.0,
        y=0.0,
        width=140.0,
        height=40.0,
        layer=15,
    )
    manufacturer_element = themes.ThemePreviewElement(
        label="manufacturer",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="manufacturer",
        value=None,
        x=0.0,
        y=0.0,
        width=400.0,
        height=40.0,
        layer=15,
    )
    genre_element = themes.ThemePreviewElement(
        label="genre",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="genre",
        value=None,
        x=0.0,
        y=0.0,
        width=400.0,
        height=40.0,
        layer=15,
    )

    assert MainWindow._resolve_theme_preview_text(
        FakeMainWindow(),
        year_element,
        "1 CONSOLES",
        game_entry,
        (game_entry,),
        1,
    ) == "1984"
    assert MainWindow._resolve_theme_preview_text(
        FakeMainWindow(),
        manufacturer_element,
        "1 CONSOLES",
        game_entry,
        (game_entry,),
        1,
    ) == "Epoch Co."
    assert MainWindow._resolve_theme_preview_text(
        FakeMainWindow(),
        genre_element,
        "1 CONSOLES",
        game_entry,
        (game_entry,),
        1,
    ) == "Console"


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


def test_stop_wheel_animation_plays_menuexit_before_highlightenter_when_available(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    element = themes.ThemePreviewElement(
        label="sideLogo",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=250.0,
        height=100.0,
        layer=10,
        alpha=0.6,
        menu_position=2,
        menu_selected_position=5,
        event_anim_sets=(
            ("menuexit", None, ((0.2, (("alpha", 0.6, 0.0, "linear"),)),)),
            ("highlightenter", None, ((0.1, (("alpha", 0.0, 1.0, "linear"),)),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Cyberpunkd",
        selected_collection="1 CONSOLES",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=True,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(element,),
        collection_override_count=1,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)
    widget._wheel_anim_active = True
    widget._event_anim_name = "menuscroll"
    widget._event_anim_values = {element: {"alpha": 0.6}}

    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 10.0)
    widget.stop_wheel_animation()

    assert widget._event_anim_name == "menuexit"
    assert widget._pending_event_animation == "highlightenter"

    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 10.25)
    widget._on_event_anim_tick()

    assert widget._event_anim_name == "highlightenter"
    assert widget._pending_event_animation is None


def test_bare_menuexit_transition_skips_adjacent_menu_slots() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    adjacent = themes.ThemePreviewElement(
        label="adjacent",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=250.0,
        height=100.0,
        layer=10,
        alpha=0.9,
        menu_position=4,
        menu_selected_position=5,
        event_anim_sets=(
            ("menuexit", None, ((0.2, (("alpha", 0.9, 0.0, "linear"),)),)),
        ),
    )
    outer = themes.ThemePreviewElement(
        label="outer",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=250.0,
        height=100.0,
        layer=10,
        alpha=0.6,
        menu_position=2,
        menu_selected_position=5,
        event_anim_sets=(
            ("menuexit", None, ((0.2, (("alpha", 0.6, 0.0, "linear"),)),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Cyberpunkd",
        selected_collection="1 CONSOLES",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=True,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(adjacent, outer),
        collection_override_count=1,
        common_slots=(),
        system_slots=(),
    )
    widget.set_preview(preview)

    widget._start_event_animation("menuexit")

    assert widget._event_anim_name == "menuexit"
    assert adjacent not in widget._event_anim_values
    assert outer in widget._event_anim_values


def test_idle_animation_uses_live_event_alpha_when_from_is_omitted(monkeypatch) -> None:
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
        alpha=0.0,
        idle_anim_sets=((1.2, (("alpha", None, 0.0, "linear"),)),),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Gemini",
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
    widget._event_anim_name = "menuscroll"
    widget._event_anim_values = {element: {"alpha": 1.0}}
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 10.0)
    widget._idle_anim_start_ms = 10_000.0

    widget._on_idle_anim_tick()

    assert widget._effective_preview_animation_values(element)["alpha"] > 0.95


def test_alpha_only_idle_animation_does_not_override_media_geometry(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    element = themes.ThemePreviewElement(
        label="device",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="device",
        value=None,
        x=770.0,
        y=250.0,
        width=220.0,
        height=160.0,
        layer=7,
        max_height=360.0,
        alpha=0.0,
        idle_anim_sets=((1.0, (("alpha", 0.0, 0.85, "linear"),)),),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Cafe80s",
        selected_collection="1 HANDHELDS",
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
    widget._idle_anim_seed_values = {element: {"alpha": 0.0}}
    widget._idle_anim_start_ms = 0.0
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 0.5)

    widget._on_idle_anim_tick()

    values = widget._effective_preview_animation_values(element)
    assert round(values.get("alpha", 0.0), 3) == 0.425
    assert "width" not in values
    assert "height" not in values


def test_idle_animation_can_animate_menu_position(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._animation_enabled = True
    element = themes.ThemePreviewElement(
        label="selected cover",
        kind="menu",
        tag_name="menu",
        slot_name="artwork_front",
        value=None,
        x=610.0,
        y=650.0,
        width=550.0,
        height=550.0,
        layer=12,
        selected=True,
        idle_anim_sets=(
            (2.0, (("y", None, 720.0, "easeinquadratic"),)),
            (1.4, (("y", None, 650.0, "easeinquadratic"),)),
        ),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Cyberpunkd",
        selected_collection="Nintendo Game Boy Advance",
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
    widget._idle_anim_seed_values = {element: {"y": 650.0}}
    widget._idle_anim_start_ms = 0.0
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 1.0)

    widget._on_idle_anim_tick()

    values = widget._effective_preview_animation_values(element)
    assert values["y"] > 665.0


def test_still_mode_uses_idle_terminal_values_for_non_menu_elements_only() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    image_element = themes.ThemePreviewElement(
        label="entry",
        kind="image",
        tag_name="image",
        slot_name=None,
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
        layer=2,
        alpha=1.0,
        idle_anim_sets=((3.0, (("nop", None, None, "linear"),)), (0.001, (("alpha", None, 0.0, "linear"),))),
    )
    menu_element = themes.ThemePreviewElement(
        label="selected",
        kind="menu",
        tag_name="menu",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
        layer=10,
        selected=True,
        idle_anim_sets=((2.0, (("alpha", None, 0.0, "linear"),)),),
    )

    image_values = widget._effective_preview_animation_values(image_element)
    menu_values = widget._effective_preview_animation_values(menu_element)

    assert image_values == {"alpha": 0.0}
    assert menu_values == {}


def test_still_mode_preserves_menu_enter_state_for_non_menu_elements() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="menubg",
        kind="image",
        tag_name="image",
        slot_name=None,
        value=None,
        x=0.0,
        y=1040.0,
        width=100.0,
        height=50.0,
        layer=11,
        alpha=1.0,
        idle_anim_sets=(
            (2.3, (("y", None, 1040.0, "linear"),)),
            (1.0, (("y", None, 1185.0, "linear"),)),
            (2.0, (("alpha", None, 0.0, "linear"),)),
        ),
        event_anim_targets=(("menuenter", None, (("alpha", 1.0), ("y", 1040.0))),),
    )

    values = widget._effective_preview_animation_values(element)

    assert values == {"alpha": 1.0, "y": 1040.0}


def test_on_wheel_animation_finished_restarts_widget_highlight_restore() -> None:
    class FakeThemesPreview:
        def __init__(self) -> None:
            self._wheel_anim_total_games = 5
            self._wheel_anim_start_game_0 = 0
            self._wheel_anim_target_advance = 2
            self.stopped = False
            self.preserve_scroll_tail = False

        def stop_wheel_animation(self, *, preserve_scroll_tail: bool = False) -> None:
            self.stopped = True
            self.preserve_scroll_tail = preserve_scroll_tail

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
            self._theme_preview_promoted_final_zero_index = None
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

        def _theme_preview_should_preserve_scroll_tail(self) -> bool:
            return True

    fake = FakeMainWindow()
    MainWindow._on_wheel_animation_finished(fake)

    assert fake.themes_preview.stopped is True
    assert fake.themes_preview.preserve_scroll_tail is True
    assert fake.render_data_set is False
    assert fake._theme_preview_pending_settled_render is True
    assert fake.scheduled is True


def test_on_wheel_animation_finished_skips_rebuild_when_final_target_already_promoted() -> None:
    class FakeThemesPreview:
        def __init__(self) -> None:
            self._wheel_anim_total_games = 10
            self._wheel_anim_start_game_0 = 2
            self._wheel_anim_target_advance = 3
            self.stopped = False
            self.preserve_scroll_tail = False

        def stop_wheel_animation(self, *, preserve_scroll_tail: bool = False) -> None:
            self.stopped = True
            self.preserve_scroll_tail = preserve_scroll_tail

    class FakeCombo:
        def __init__(self) -> None:
            self._index = 0

        def count(self) -> int:
            return 20

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
            self._theme_preview_promoted_final_zero_index = 5
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

        def _theme_preview_should_preserve_scroll_tail(self) -> bool:
            return True

        def _theme_preview_should_preserve_scroll_tail(self) -> bool:
            return True

        def _theme_preview_should_preserve_scroll_tail(self) -> bool:
            return True

    fake = FakeMainWindow()
    MainWindow._on_wheel_animation_finished(fake)

    assert fake.themes_preview.stopped is True
    assert fake.themes_preview.preserve_scroll_tail is True
    assert fake.render_data_set is False
    assert fake._theme_preview_pending_settled_render is True
    assert fake._theme_preview_promoted_final_zero_index is None
    assert fake.scheduled is True


def test_theme_preview_scroll_fade_finished_applies_pending_settled_render() -> None:
    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_pending_settled_render = True
            self._theme_preview = object()
            self.render_data_set = False

        def _build_theme_render_data(self, preview):
            assert preview is self._theme_preview
            return {"done": True}

        def _set_theme_preview_render_data(self, data, transition=False) -> None:
            assert data == {"done": True}
            assert transition is False
            self.render_data_set = True

    fake = FakeMainWindow()

    MainWindow._on_theme_preview_scroll_fade_finished(fake)

    assert fake.render_data_set is True
    assert fake._theme_preview_pending_settled_render is False


def test_theme_preview_should_preserve_scroll_tail_for_multiple_menu_groups_and_hidden_selected() -> None:
    preview = themes.ThemeLayoutPreview(
        theme_name="Fan Art Magazine",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=768.0,
        canvas_height=1366.0,
        elements=(
            themes.ThemePreviewElement("logo1", "menu", "menu", "logo", None, 0.0, 0.0, 100.0, 100.0, 1),
            themes.ThemePreviewElement("logoSel", "menu", "menu", "logo", None, 0.0, 120.0, 100.0, 100.0, 1, selected=True),
            themes.ThemePreviewElement("bg", "image", "image", None, None, 0.0, 0.0, 50.0, 50.0, 0),
            themes.ThemePreviewElement("coverHiddenSel", "menu", "menu", "artwork_front_s", None, 0.0, 1000.0, 200.0, 266.0, 1, selected=True, alpha=0.0),
            themes.ThemePreviewElement("coverVisible", "menu", "menu", "artwork_front_s", None, 0.0, 1000.0, 200.0, 266.0, 2),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )

    class FakeMainWindow:
        _theme_preview = preview

    assert MainWindow._theme_preview_should_preserve_scroll_tail(FakeMainWindow()) is True


def test_theme_preview_should_not_preserve_scroll_tail_for_single_visible_menu_group() -> None:
    preview = themes.ThemeLayoutPreview(
        theme_name="Gemini",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(
            themes.ThemePreviewElement("slot1", "menu", "menu", "logo", None, 0.0, 0.0, 100.0, 100.0, 1),
            themes.ThemePreviewElement("slotSel", "menu", "menu", "logo", None, 0.0, 120.0, 100.0, 100.0, 1, selected=True, alpha=1.0),
            themes.ThemePreviewElement("slot3", "menu", "menu", "logo", None, 0.0, 240.0, 100.0, 100.0, 1),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )

    class FakeMainWindow:
        _theme_preview = preview

    assert MainWindow._theme_preview_should_preserve_scroll_tail(FakeMainWindow()) is False


def test_scroll_fade_finishes_settled_render_before_highlight_restore() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    order: list[str] = []

    def on_finished() -> None:
        order.append("settled")

    widget.scrollFadeFinished.connect(on_finished)
    widget._scroll_anim_opacity = 0.0
    widget._scroll_fading_out = True
    widget._pending_highlight_restore = True
    widget._wheel_anim_extra_groups = [([], {}, 0)]
    widget._wheel_anim_last_scroll_pos = 1.0

    original_start = widget._start_event_animation

    def recording_start(event_name: str) -> None:
        order.append(event_name)
        original_start(event_name)

    widget._start_event_animation = recording_start  # type: ignore[method-assign]

    widget._on_scroll_fade_tick()

    assert order[0] == "settled"
    assert "highlightenter" in order[1:]


def test_stop_wheel_animation_can_preserve_scroll_tail() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._wheel_anim_active = True
    widget._scroll_fading_out = True
    widget._scroll_anim_opacity = 0.5
    widget._wheel_anim_extra_groups = [([], {}, 0)]
    widget._wheel_anim_last_scroll_pos = 3.25

    widget.stop_wheel_animation(preserve_scroll_tail=True)

    assert widget._scroll_fading_out is True
    assert widget._scroll_anim_opacity == 0.5
    assert widget._wheel_anim_extra_groups == [([], {}, 0)]
    assert widget._wheel_anim_last_scroll_pos == 3.25
    assert widget._pending_highlight_restore is True


def test_stop_wheel_animation_preserve_tail_restarts_idle_immediately() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._wheel_anim_active = True
    widget._animation_enabled = True
    widget._preview = themes.ThemeLayoutPreview(
        theme_name="Test",
        selected_collection=None,
        root_layout_path=Path("layout.xml"),
        active_layout_path=Path("layout.xml"),
        using_collection_override=False,
        canvas_width=1920.0,
        canvas_height=1080.0,
        elements=(
            themes.ThemePreviewElement(
                label="firstLetter",
                kind="reloadable_image",
                tag_name="reloadableImage",
                slot_name="firstLetter",
                value=None,
                x=0.0,
                y=0.0,
                width=10.0,
                height=10.0,
                layer=1,
                idle_anim_sets=((0.5, (("alpha", 1.0, 0.0, "linear"),)),),
            ),
        ),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
        layout_collection=None,
        error=None,
    )

    called = {"restart": 0}

    def fake_restart() -> None:
        called["restart"] += 1

    widget._restart_idle_animation = fake_restart  # type: ignore[method-assign]

    widget.stop_wheel_animation(preserve_scroll_tail=True)

    assert called["restart"] == 1
    assert widget._pending_highlight_restore is True


def test_ordered_elements_preserves_source_order_within_same_layer() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    elements = (
        themes.ThemePreviewElement(label="b", kind="image", tag_name="image", slot_name=None, value=None, x=0, y=0, width=50, height=50, layer=6),
        themes.ThemePreviewElement(label="a", kind="image", tag_name="image", slot_name=None, value=None, x=0, y=0, width=100, height=100, layer=6),
        themes.ThemePreviewElement(label="c", kind="image", tag_name="image", slot_name=None, value=None, x=0, y=0, width=25, height=25, layer=7),
    )

    ordered = widget._ordered_elements(elements)

    assert [element.label for element in ordered] == ["b", "a", "c"]


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


def test_fixed_width_singleline_text_honors_right_alignment(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="year",
        kind="reloadable_text",
        tag_name="reloadableText",
        slot_name="year",
        value=None,
        x=1200.0,
        y=365.0,
        width=140.0,
        height=40.0,
        layer=15,
        explicit_width=True,
        explicit_height=False,
        x_origin="right",
        y_origin="top",
        font_size=40.0,
        load_font_size=40.0,
    )
    image = QImage(1600, 900, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    visible_rect = QRectF(1060.0, 365.0, 140.0, 40.0)
    captured: dict[str, object] = {}
    original_draw_text = QPainter.drawText

    def fake_draw_text(self, *args):
        if len(args) >= 3 and isinstance(args[0], QRectF):
            captured["rect"] = QRectF(args[0])
            captured["flags"] = args[1]
            captured["text"] = args[2]
            return None
        return original_draw_text(self, *args)

    monkeypatch.setattr(QPainter, "drawText", fake_draw_text)
    widget._draw_element_text(
        painter,
        element,
        visible_rect,
        visible_rect,
        visible_rect,
        "1988",
        1.0,
        1.0,
    )
    painter.end()

    assert captured["text"] == "1988"
    assert int(captured["flags"]) & int(Qt.AlignmentFlag.AlignRight)
    assert int(captured["flags"]) & int(Qt.TextFlag.TextSingleLine)


def test_draw_rect_pixmap_does_not_use_rotated_bounding_fit_for_menu_items(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="menu:logo 4",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=165.0,
        y=500.0,
        width=250.0,
        height=100.0,
        layer=12,
        explicit_width=True,
        explicit_height=True,
        angle=-90.0,
    )
    pixmap = QPixmap(400, 114)
    pixmap.fill(Qt.GlobalColor.white)
    image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    called = {"rotated": False}

    def fake_scaled_rotated_pixmap(*args, **kwargs):
        called["rotated"] = True
        return pixmap

    monkeypatch.setattr(widget, "_scaled_rotated_pixmap", fake_scaled_rotated_pixmap)
    widget._draw_rect_pixmap(
        painter,
        pixmap,
        element,
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        QRectF(165.0, 500.0, 250.0, 100.0),
    )
    painter.end()

    assert called["rotated"] is False


def test_draw_wheel_logo_does_not_use_rotated_bounding_fit_for_menu_items(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="menu:logo 4",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=165.0,
        y=500.0,
        width=250.0,
        height=100.0,
        layer=12,
        explicit_width=True,
        explicit_height=True,
        angle=-90.0,
    )
    pixmap = QPixmap(400, 114)
    pixmap.fill(Qt.GlobalColor.white)
    image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    called = {"rotated": False}

    def fake_scaled_rotated_pixmap(*args, **kwargs):
        called["rotated"] = True
        return pixmap

    monkeypatch.setattr(widget, "_scaled_rotated_pixmap", fake_scaled_rotated_pixmap)
    widget._draw_wheel_logo(
        painter,
        pixmap,
        element,
        QRectF(165.0, 500.0, 250.0, 100.0),
        QRectF(0.0, 0.0, 1920.0, 1080.0),
        -90.0,
        1.0,
    )
    painter.end()

    assert called["rotated"] is False


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
            self._theme_preview_video_sessions = {}

    fake = FakeMainWindow()
    MainWindow._handle_theme_preview_video_frame(fake, element, FakeFrame())
    updated = fake._theme_preview_render_data[element]
    assert updated.pixmap is not None
    assert not updated.pixmap.isNull()


def test_theme_preview_pixmap_blank_detection_distinguishes_black_from_content() -> None:
    _ensure_app()
    black_image = QImage(32, 24, QImage.Format.Format_RGB32)
    black_image.fill(0xFF000000)
    black = QPixmap.fromImage(black_image)
    content_image = QImage(32, 24, QImage.Format.Format_RGB32)
    content_image.fill(0xFF000000)
    content_image.setPixelColor(10, 10, Qt.GlobalColor.white)
    content = QPixmap.fromImage(content_image)

    assert MainWindow._theme_preview_pixmap_looks_blank(black) is True
    assert MainWindow._theme_preview_pixmap_looks_blank(content) is False


def test_theme_preview_video_frame_ignores_blank_startup_frame_during_grace_window() -> None:
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
    existing = QPixmap(24, 24)
    existing.fill(Qt.GlobalColor.red)
    black_image = QImage(24, 24, QImage.Format.Format_RGB32)
    black_image.fill(0xFF000000)
    black = QPixmap.fromImage(black_image)

    class FakeFrame:
        pass

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_render_data = {
                element: ThemePreviewRenderData(pixmap=existing, video_path=Path("new.mp4"))
            }
            self._theme_preview_video_sessions = {
                element: ThemePreviewVideoSession(
                    element=element,
                    video_path=Path("new.mp4"),
                    player=type("Player", (), {"position": lambda self: 100})(),
                    audio_output=None,
                    video_sink=None,
                    created_at_ms=(time.monotonic() * 1000.0) - 50.0,
                )
            }
            self._theme_video_dirty = False

    fake = FakeMainWindow()
    original = MainWindow._theme_preview_pixmap_from_frame
    try:
        MainWindow._theme_preview_pixmap_from_frame = staticmethod(lambda frame: black)
        MainWindow._handle_theme_preview_video_frame(fake, element, FakeFrame())
    finally:
        MainWindow._theme_preview_pixmap_from_frame = original

    updated = fake._theme_preview_render_data[element]
    assert updated.pixmap is not None
    assert updated.pixmap.cacheKey() == existing.cacheKey()
    assert fake._theme_video_dirty is False
    assert fake._theme_preview_video_sessions[element].accepted_live_frame is False


def test_theme_preview_video_frame_ignores_blank_startup_frame_while_playback_position_is_early() -> None:
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
    existing = QPixmap(24, 24)
    existing.fill(Qt.GlobalColor.red)
    black_image = QImage(24, 24, QImage.Format.Format_RGB32)
    black_image.fill(0xFF000000)
    black = QPixmap.fromImage(black_image)

    class FakeFrame:
        pass

    class FakePlayer:
        def position(self) -> int:
            return 120

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_render_data = {
                element: ThemePreviewRenderData(pixmap=existing, video_path=Path("new.mp4"))
            }
            self._theme_preview_video_sessions = {
                element: ThemePreviewVideoSession(
                    element=element,
                    video_path=Path("new.mp4"),
                    player=FakePlayer(),
                    audio_output=None,
                    video_sink=None,
                    created_at_ms=(time.monotonic() * 1000.0) - 1500.0,
                )
            }
            self._theme_video_dirty = False

    fake = FakeMainWindow()
    original = MainWindow._theme_preview_pixmap_from_frame
    try:
        MainWindow._theme_preview_pixmap_from_frame = staticmethod(lambda frame: black)
        MainWindow._handle_theme_preview_video_frame(fake, element, FakeFrame())
    finally:
        MainWindow._theme_preview_pixmap_from_frame = original

    updated = fake._theme_preview_render_data[element]
    assert updated.pixmap is not None
    assert updated.pixmap.cacheKey() == existing.cacheKey()
    assert fake._theme_video_dirty is False
    assert fake._theme_preview_video_sessions[element].accepted_live_frame is False


def test_theme_preview_video_frame_primes_first_live_frame_before_replacing_previous_content() -> None:
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
    existing = QPixmap(24, 24)
    existing.fill(Qt.GlobalColor.red)
    first_live = QPixmap(24, 24)
    first_live.fill(Qt.GlobalColor.green)
    second_live = QPixmap(24, 24)
    second_live.fill(Qt.GlobalColor.blue)

    class FakeFrame:
        pass

    class FakePlayer:
        def position(self) -> int:
            return 800

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_render_data = {
                element: ThemePreviewRenderData(pixmap=existing, video_path=Path("new.mp4"))
            }
            self._theme_preview_video_sessions = {
                element: ThemePreviewVideoSession(
                    element=element,
                    video_path=Path("new.mp4"),
                    player=FakePlayer(),
                    audio_output=None,
                    video_sink=None,
                    created_at_ms=(time.monotonic() * 1000.0) - 1500.0,
                )
            }
            self._theme_video_dirty = False

    fake = FakeMainWindow()
    original = MainWindow._theme_preview_pixmap_from_frame
    frames = [first_live, second_live]
    try:
        MainWindow._theme_preview_pixmap_from_frame = staticmethod(lambda frame: frames.pop(0))
        MainWindow._handle_theme_preview_video_frame(fake, element, FakeFrame())
        first_update = fake._theme_preview_render_data[element]
        assert first_update.pixmap is not None
        assert first_update.pixmap.cacheKey() == existing.cacheKey()
        assert fake._theme_video_dirty is False
        assert fake._theme_preview_video_sessions[element].accepted_live_frame is False
        assert fake._theme_preview_video_sessions[element].primed_live_frame is not None

        MainWindow._handle_theme_preview_video_frame(fake, element, FakeFrame())
    finally:
        MainWindow._theme_preview_pixmap_from_frame = original

    second_update = fake._theme_preview_render_data[element]
    assert second_update.pixmap is not None
    assert second_update.pixmap.cacheKey() == second_live.cacheKey()
    assert fake._theme_video_dirty is True
    assert fake._theme_preview_video_sessions[element].accepted_live_frame is True
    assert fake._theme_preview_video_sessions[element].primed_live_frame is None


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


def test_trigger_theme_preview_random_advance_uses_non_logo_menu_wheels(monkeypatch) -> None:
    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = type(
                "Preview",
                (),
                {
                    "elements": (
                        themes.ThemePreviewElement(
                            label="cover",
                            kind="menu",
                            tag_name="menu",
                            slot_name="artwork_front",
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
            self._selected_theme_collection_name = "Nintendo Game Boy Advance"
            self.themes_collection_filter = type("Combo", (), {"currentData": lambda self: "Nintendo Game Boy Advance"})()
            self.themes_game_filter = type("Combo", (), {"currentIndex": lambda self: 1})()
            self.called_with: tuple[int, int | None] | None = None

        def _theme_games_for_collection(self, collection_name: str):
            return tuple(
                GameManifestEntry(game_name=f"G{i}", collection_name="Nintendo Game Boy Advance", rom_path=f"g{i}.zip")
                for i in range(25)
            )

        def _start_wheel_animation(self, advance_count: int, *, target_offset: int | None = None) -> None:
            self.called_with = (advance_count, target_offset)

        def _jump_theme_preview_to_index(self, zero_index: int) -> None:
            raise AssertionError("wheel path should be used")

    fake = FakeMainWindow()
    monkeypatch.setattr("onesauce_companion.ui.main_window.random.randint", lambda a, b: 9)
    MainWindow._trigger_theme_preview_random_advance(fake)

    assert fake.called_with == (9, None)


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
        _common_slot_candidate_names = MainWindow._common_slot_candidate_names

        def _resolve_theme_game_metadata(self, collection_name, game_entry):
            return None

    result = MainWindow._resolve_common_theme_render(FakeMainWindow(), theme_entry, "cabinet", game_entry, "MAME")

    assert result is not None
    assert result.pixmap is not None
    assert not result.pixmap.isNull()


def test_resolve_common_theme_render_playlist_prefers_all_playlist_art(tmp_path: Path) -> None:
    _ensure_app()
    theme_root = tmp_path / "base_assets" / "layouts" / "Renee"
    playlist_dir = theme_root / "collections" / "_common" / "medium_artwork" / "playlist"
    playlist_dir.mkdir(parents=True, exist_ok=True)
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF00FF00)
    assert image.save(str(playlist_dir / "all.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="Renee",
        root_dir=theme_root,
        layout_path=theme_root / "layout.xml",
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=("playlist",),
    )
    game_entry = GameManifestEntry(game_name="Total Carnage", collection_name="MAME", rom_path="totcarn.zip")

    class FakeMainWindow:
        _common_slot_candidate_names = MainWindow._common_slot_candidate_names

        def _resolve_theme_game_metadata(self, collection_name, game_entry):
            return None

    result = MainWindow._resolve_common_theme_render(FakeMainWindow(), theme_entry, "playlist", game_entry, "MAME")

    assert result is not None
    assert result.pixmap is not None
    assert not result.pixmap.isNull()


def test_common_root_for_mode_prefers_base_assets_common_when_appdata_common_missing(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    (target_root / "base_assets" / "collections" / "_common").mkdir(parents=True, exist_ok=True)
    theme_root = tmp_path / "base_assets" / "layouts" / "Cafe80s"
    theme_root.mkdir(parents=True, exist_ok=True)

    class FakeMainWindow:
        def _target_dir(self):
            return target_root

    theme_entry = themes.ThemeCatalogEntry(
        name="Cafe80s",
        root_dir=theme_root,
        layout_path=theme_root / "layout.xml",
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=("genre",),
    )

    resolved = MainWindow._common_root_for_mode(FakeMainWindow(), theme_entry, "common")

    assert resolved == target_root / "base_assets" / "collections" / "_common"


def test_common_slot_candidate_names_use_metadata_for_common_icon_slots() -> None:
    game_entry = GameManifestEntry(game_name="'88 Games", collection_name="MAME", rom_path="88games.zip")

    class FakeMetadata:
        def value_for_slot(self, slot_name: str) -> str | None:
            return {
                "manufacturer": "Konami",
                "genre": "Sports/Track & Field",
                "numberplayers": "4",
                "score": "3.6",
            }.get(slot_name.casefold())

    class FakeMainWindow:
        def _resolve_theme_game_metadata(self, collection_name, game_entry):
            return FakeMetadata()

    manufacturer = MainWindow._common_slot_candidate_names(FakeMainWindow(), "manufacturer", game_entry, "MAME")
    genre = MainWindow._common_slot_candidate_names(FakeMainWindow(), "genre", game_entry, "MAME")
    players = MainWindow._common_slot_candidate_names(FakeMainWindow(), "numberplayers", game_entry, "MAME")
    score = MainWindow._common_slot_candidate_names(FakeMainWindow(), "score", game_entry, "MAME")

    assert manufacturer == ("Konami",)
    assert "Sports/Track & Field" in genre
    assert "Sports_Track & Field" in genre
    assert players == ("4",)
    assert score == ("3.6",)


def test_resolve_common_theme_render_uses_metadata_named_common_art(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path / "target"
    genre_dir = target_root / "base_assets" / "collections" / "_common" / "medium_artwork" / "genre"
    manufacturer_dir = target_root / "base_assets" / "collections" / "_common" / "medium_artwork" / "manufacturer"
    players_dir = target_root / "base_assets" / "collections" / "_common" / "medium_artwork" / "numberPlayers"
    score_dir = target_root / "base_assets" / "collections" / "_common" / "medium_artwork" / "score"
    for folder, filename, color in (
        (genre_dir, "Sports_Track & Field.png", 0xFF00FF00),
        (manufacturer_dir, "Konami.png", 0xFFFF0000),
        (players_dir, "4.png", 0xFF0000FF),
        (score_dir, "3.6.png", 0xFFFFFF00),
    ):
        folder.mkdir(parents=True, exist_ok=True)
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(color)
        assert image.save(str(folder / filename))

    theme_root = tmp_path / "base_assets" / "layouts" / "Cafe80s"
    theme_root.mkdir(parents=True, exist_ok=True)
    theme_entry = themes.ThemeCatalogEntry(
        name="Cafe80s",
        root_dir=theme_root,
        layout_path=theme_root / "layout.xml",
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=("genre", "manufacturer", "numberPlayers", "score"),
    )
    game_entry = GameManifestEntry(game_name="'88 Games", collection_name="MAME", rom_path="88games.zip")

    class FakeMetadata:
        def value_for_slot(self, slot_name: str) -> str | None:
            return {
                "manufacturer": "Konami",
                "genre": "Sports/Track & Field",
                "numberplayers": "4",
                "score": "3.6",
            }.get(slot_name.casefold())

    class FakeMainWindow:
        _common_root_for_mode = MainWindow._common_root_for_mode
        _common_slot_candidate_names = MainWindow._common_slot_candidate_names

        def _target_dir(self):
            return target_root

        def _resolve_theme_game_metadata(self, collection_name, game_entry):
            return FakeMetadata()

    for slot_name in ("genre", "manufacturer", "numberPlayers", "score"):
        common_root = MainWindow._common_root_for_mode(FakeMainWindow(), theme_entry, "common")
        result = MainWindow._resolve_common_theme_render(
            FakeMainWindow(),
            theme_entry,
            slot_name,
            game_entry,
            "MAME",
            common_root,
        )
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
    _ensure_app()
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


def test_start_wheel_animation_uses_text_fallback_for_menu_slots_without_logo_images() -> None:
    _ensure_app()
    class FakeThemesPreview:
        def __init__(self) -> None:
            self.called = None

        def start_wheel_animation(self, slot_elements, logos, sel_idx, start_game_0, advance_count, total_games, duration_ms, target_advance=None, extra_groups=None):
            self.called = {
                "slot_elements": slot_elements,
                "logos": logos,
                "sel_idx": sel_idx,
                "extra_groups": extra_groups,
            }

    entry_a = GameManifestEntry(game_name="Avenger", collection_name="Commodore VIC-20", rom_path="Avenger.zip")
    entry_b = GameManifestEntry(game_name="Radar Rat Race", collection_name="Commodore VIC-20", rom_path="Radar Rat Race.zip")

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = themes.ThemeLayoutPreview(
                theme_name="CoinOPS",
                selected_collection="Commodore VIC-20",
                root_layout_path=None,
                active_layout_path=None,
                using_collection_override=False,
                canvas_width=1920.0,
                canvas_height=1080.0,
                elements=(
                    themes.ThemePreviewElement("logo 1", "menu", "menu", "logo", None, 0.0, 0.0, 100.0, 100.0, 1, menu_position=1, menu_selected_position=2),
                    themes.ThemePreviewElement("logo sel", "menu", "menu", "logo", None, 100.0, 0.0, 100.0, 100.0, 1, selected=True, menu_position=2, menu_selected_position=2),
                ),
                collection_override_count=0,
                common_slots=(),
                system_slots=(),
            )
            self._selected_theme_collection_name = "Commodore VIC-20"
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
    assert fake.themes_preview.called["logos"]
    assert set(fake.themes_preview.called["logos"].keys()) >= {0, 1}


def test_start_wheel_animation_uses_child_collection_logo_for_placeholder_menu_entries(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path / "target"
    logo_dir = target_root / "content" / "retrofe" / "collections" / "Commodore 64" / "system_artwork"
    logo_dir.mkdir(parents=True, exist_ok=True)
    image = QImage(12, 12, QImage.Format.Format_ARGB32)
    image.fill(0xFF3366FF)
    assert image.save(str(logo_dir / "logo.png"))

    class FakeThemesPreview:
        def __init__(self) -> None:
            self.called = None

        def start_wheel_animation(self, slot_elements, logos, sel_idx, start_game_0, advance_count, total_games, duration_ms, target_advance=None, extra_groups=None):
            self.called = {
                "logos": logos,
                "slot_elements": slot_elements,
            }

    entry = GameManifestEntry(game_name="Commodore 64", collection_name="1 COLLECTIONS", rom_path="Commodore 64")

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = themes.ThemeLayoutPreview(
                theme_name="Cyberpunkd",
                selected_collection="1 COLLECTIONS",
                root_layout_path=None,
                active_layout_path=None,
                using_collection_override=False,
                canvas_width=1920.0,
                canvas_height=1080.0,
                elements=(
                    themes.ThemePreviewElement("logo sel", "menu", "menu", "logo", None, 0.0, 0.0, 100.0, 100.0, 1, selected=True, menu_position=1, menu_selected_position=1),
                ),
                collection_override_count=0,
                common_slots=(),
                system_slots=(),
            )
            self._selected_theme_collection_name = "1 COLLECTIONS"
            self._theme_entries = []
            self._theme_preview_video_sessions = {}
            self.themes_preview = FakeThemesPreview()
            self.themes_game_filter = type("Combo", (), {"currentIndex": lambda self: 1})()
            self._theme_preview_wheel_spinning = False

        def _target_dir(self):
            return target_root

        def _theme_games_for_collection(self, collection_name: str):
            return (entry,)

        def _apply_theme_preview_session_state(self, session) -> None:
            return None

        def _resolve_theme_game_media_root(self, game_entry):
            return None

        def _resolve_game_media_path(self, media_root, base_names, slot_key):
            return None

        def _make_wheel_text_pixmap(self, text: str, ref_element):
            raise AssertionError("text fallback should not be used when child collection logo exists")

    fake = FakeMainWindow()

    MainWindow._start_wheel_animation(fake, 1)

    assert fake.themes_preview.called is not None
    logos = fake.themes_preview.called["logos"]
    assert 0 in logos
    assert not logos[0].isNull()


def test_resolve_game_theme_render_placeholder_menu_with_text_fallback_uses_text_when_no_logo_exists(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path / "target"
    logo_dir = target_root / "content" / "retrofe" / "collections" / "1 ARCADES" / "system_artwork"
    logo_dir.mkdir(parents=True, exist_ok=True)
    image = QImage(12, 12, QImage.Format.Format_ARGB32)
    image.fill(0xFF3366FF)
    assert image.save(str(logo_dir / "logo.png"))

    element = themes.ThemePreviewElement(
        label="menu logo selected",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=50.0,
        layer=12,
        selected=True,
        text_fallback=True,
        text_format="uppercase",
        menu_position=1,
        menu_selected_position=1,
    )
    game_entry = GameManifestEntry(game_name="1 ARCADES", collection_name="1 ARCADES", rom_path="1 ARCADES")

    class FakeMainWindow:
        def _target_dir(self):
            return target_root

        def _theme_menu_entry_for_element(self, element, selected_entry, collection_games, collection_index):
            return selected_entry

        def _resolve_theme_game_media_root(self, display_entry):
            return None

        def _resolve_game_media_path(self, media_root, base_names, slot_key):
            return None

        def _resolve_theme_preview_text(self, element, collection_name, display_entry, collection_games, collection_index):
            return None

    render = MainWindow._resolve_game_theme_render(
        FakeMainWindow(),
        element,
        None,
        "Main",
        game_entry,
        (game_entry,),
        1,
    )

    assert render is not None
    assert render.text == "1 ARCADES"


def test_start_wheel_animation_text_fallback_uses_child_theme_logo_for_placeholder_entries(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path / "target"
    theme_root = target_root / "base_assets" / "layouts" / "LUNA OG" / "collections" / "1 ARCADES" / "system_artwork"
    logo_dir = target_root / "content" / "retrofe" / "collections" / "1 ARCADES" / "system_artwork"
    theme_root.mkdir(parents=True, exist_ok=True)
    logo_dir.mkdir(parents=True, exist_ok=True)
    theme_image = QImage(30, 12, QImage.Format.Format_ARGB32)
    theme_image.fill(0xFFFF6600)
    assert theme_image.save(str(theme_root / "logo.png"))
    image = QImage(12, 12, QImage.Format.Format_ARGB32)
    image.fill(0xFF3366FF)
    assert image.save(str(logo_dir / "logo.png"))

    class FakeThemesPreview:
        def __init__(self) -> None:
            self.called = None

        def start_wheel_animation(self, slot_elements, logos, sel_idx, start_game_0, advance_count, total_games, duration_ms, target_advance=None, extra_groups=None):
            self.called = {
                "logos": logos,
                "slot_elements": slot_elements,
            }

    entry = GameManifestEntry(game_name="1 ARCADES", collection_name="1 ARCADES", rom_path="1 ARCADES")

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = themes.ThemeLayoutPreview(
                theme_name="LUNA OG",
                selected_collection="Main",
                root_layout_path=None,
                active_layout_path=None,
                using_collection_override=False,
                canvas_width=1920.0,
                canvas_height=1080.0,
                elements=(
                    themes.ThemePreviewElement(
                        "logo sel",
                        "menu",
                        "menu",
                        "logo",
                        None,
                        0.0,
                        0.0,
                        100.0,
                        50.0,
                        1,
                        mode="layout",
                        selected=True,
                        menu_position=1,
                        menu_selected_position=1,
                        text_fallback=True,
                        text_format="uppercase",
                    ),
                ),
                collection_override_count=0,
                common_slots=(),
                system_slots=(),
            )
            self._selected_theme_collection_name = "Main"
            self._theme_entries = (
                themes.ThemeCatalogEntry(
                    name="LUNA OG",
                    root_dir=target_root / "base_assets" / "layouts" / "LUNA OG",
                    layout_path=None,
                    splash_path=None,
                    collection_overrides=(),
                    common_slots=(),
                    layout_sync_aliases=(),
                ),
            )
            self._theme_preview_video_sessions = {}
            self.themes_preview = FakeThemesPreview()
            self.themes_game_filter = type("Combo", (), {"currentIndex": lambda self: 1})()
            self._theme_preview_wheel_spinning = False

        def _target_dir(self):
            return target_root

        def _theme_games_for_collection(self, collection_name: str):
            return (entry,)

        def _apply_theme_preview_session_state(self, session) -> None:
            return None

        def _resolve_theme_game_media_root(self, game_entry):
            return None

        def _resolve_game_media_path(self, media_root, base_names, slot_key):
            return None

        def _make_wheel_text_pixmap(self, text: str, ref_element):
            pixmap = QPixmap(20, 10)
            pixmap.fill()
            return pixmap

    fake = FakeMainWindow()

    MainWindow._start_wheel_animation(fake, 1)

    assert fake.themes_preview.called is not None
    logos = fake.themes_preview.called["logos"]
    assert 0 in logos
    assert logos[0].width() == 30
    assert logos[0].height() == 12


def test_resolve_layout_theme_render_placeholder_menu_with_text_fallback_prefers_child_theme_logo(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path / "target"
    theme_root = target_root / "base_assets" / "layouts" / "LUNA OG"
    child_sa = theme_root / "collections" / "1 COLLECTIONS" / "system_artwork"
    child_sa.mkdir(parents=True, exist_ok=True)
    image = QImage(40, 16, QImage.Format.Format_ARGB32)
    image.fill(0xFF55AA33)
    assert image.save(str(child_sa / "logo.png"))

    element = themes.ThemePreviewElement(
        label="menu logo selected",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=50.0,
        layer=12,
        selected=True,
        text_fallback=True,
        text_format="uppercase",
        mode="layout",
        menu_position=1,
        menu_selected_position=1,
    )
    game_entry = GameManifestEntry(game_name="1 COLLECTIONS", collection_name="1 COLLECTIONS", rom_path="1 COLLECTIONS")
    theme_entry = themes.ThemeCatalogEntry(
        name="LUNA OG",
        root_dir=theme_root,
        layout_path=None,
        splash_path=None,
        collection_overrides=(),
        common_slots=(),
        layout_sync_aliases=(),
    )

    class FakeMainWindow:
        def _resolve_collection_theme_render(self, element, collection_name):
            return None

    render = MainWindow._resolve_layout_theme_render(
        FakeMainWindow(),
        element,
        theme_entry,
        "Main",
        game_entry,
    )

    assert render is not None
    assert render.pixmap is not None
    assert render.pixmap.width() == 40
    assert render.pixmap.height() == 16


def test_resolve_theme_preview_element_render_luna_main_menu_prefers_child_theme_logo(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path
    theme_root = target_root / "base_assets" / "layouts" / "LUNA OG"
    child_theme_sa = theme_root / "collections" / "1 HANDHELDS" / "system_artwork"
    child_theme_sa.mkdir(parents=True, exist_ok=True)
    child_theme = QImage(40, 16, QImage.Format.Format_ARGB32)
    child_theme.fill(0xFF55AA33)
    assert child_theme.save(str(child_theme_sa / "logo.png"))

    collection_sa = target_root / "content" / "retrofe" / "collections" / "1 HANDHELDS" / "system_artwork"
    collection_sa.mkdir(parents=True, exist_ok=True)
    collection_logo = QImage(200, 24, QImage.Format.Format_ARGB32)
    collection_logo.fill(0xFF3366FF)
    assert collection_logo.save(str(collection_sa / "logo.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="LUNA OG",
        root_dir=theme_root,
        layout_path=None,
        splash_path=None,
        collection_overrides=(),
        common_slots=(),
        layout_sync_aliases=(),
    )
    element = themes.ThemePreviewElement(
        label="menu logo selected",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=50.0,
        layer=12,
        selected=True,
        text_fallback=True,
        text_format="uppercase",
        mode="layout",
        menu_position=1,
        menu_selected_position=1,
    )
    games = (
        GameManifestEntry(game_name="1 ARCADES", collection_name="1 ARCADES", rom_path="1 ARCADES"),
        GameManifestEntry(game_name="1 HANDHELDS", collection_name="1 HANDHELDS", rom_path="1 HANDHELDS"),
    )

    class FakeMainWindow:
        def _target_dir(self):
            return target_root

        _resolve_collection_theme_render = MainWindow._resolve_collection_theme_render
        _resolve_layout_theme_render = MainWindow._resolve_layout_theme_render
        _theme_preview_layout_collection_candidates = MainWindow._theme_preview_layout_collection_candidates
        _theme_menu_entry_for_element = MainWindow._theme_menu_entry_for_element
        _resolve_theme_preview_element_render = MainWindow._resolve_theme_preview_element_render
        _resolve_static_theme_render = MainWindow._resolve_static_theme_render
        _resolve_game_theme_render = MainWindow._resolve_game_theme_render
        _resolve_layout_preferred_render = MainWindow._resolve_layout_preferred_render
        _resolve_theme_preview_text = MainWindow._resolve_theme_preview_text
        _resolve_theme_game_media_root = MainWindow._resolve_theme_game_media_root
        _resolve_game_media_path = MainWindow._resolve_game_media_path
        _common_root_for_mode = MainWindow._common_root_for_mode
        _resolve_common_theme_render = MainWindow._resolve_common_theme_render

    render = MainWindow._resolve_theme_preview_element_render(
        FakeMainWindow(),
        element,
        theme_entry,
        "Main",
        games[1],
        games,
        2,
    )

    assert render is not None
    assert render.pixmap is not None
    assert render.pixmap.width() == 40
    assert render.pixmap.height() == 16


def test_theme_games_for_collection_empty_subset_rule_includes_entire_source_collection() -> None:
    from onesauce_companion.services.collections import CollectionDefinition, CollectionSubsetRule

    entry_a = GameManifestEntry(game_name="A", collection_name="MAME", rom_path="a.zip")
    entry_b = GameManifestEntry(game_name="B", collection_name="MAME", rom_path="b.zip")

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_games_cache = {}
            self._game_entries = (entry_a, entry_b)
            self._collection_entries = ()

        def _target_dir(self):
            return Path("Q:/")

        def _scan_collection_game_entries(self, collection_name: str):
            return tuple()

        def _excluded_games_for_current_target(self):
            return set()

        def _child_collection_names(self, collection_name: str):
            return tuple()

        def _theme_games_for_collection(self, collection_name: str):
            return MainWindow._theme_games_for_collection(self, collection_name)

    fake = FakeMainWindow()
    original_scan = MainWindow._theme_games_for_collection.__globals__["scan_collection_definitions"]
    try:
        MainWindow._theme_games_for_collection.__globals__["scan_collection_definitions"] = lambda target: (
            CollectionDefinition(
                name="02 ARCADE ALL",
                subset_rules=(CollectionSubsetRule(source_collection="MAME", item_names=tuple()),),
                valid_extensions=tuple(),
                has_settings=False,
                has_info=True,
                has_menu=False,
                has_menu_supported=False,
                has_menu_directory=False,
                has_launchers=False,
                has_playlists=True,
            ),
        )
        result = MainWindow._theme_games_for_collection(fake, "02 ARCADE ALL")
    finally:
        MainWindow._theme_games_for_collection.__globals__["scan_collection_definitions"] = original_scan

    assert tuple(entry.game_name for entry in result) == ("A", "B")


def test_theme_games_for_collection_menu_placeholders_preserve_child_collection_identity() -> None:
    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_games_cache = {}
            self._game_entries = tuple()
            self._collection_entries = tuple()

        def _target_dir(self):
            return Path("Q:/")

        def _scan_collection_game_entries(self, collection_name: str):
            return tuple()

        def _excluded_games_for_current_target(self):
            return set()

        def _child_collection_names(self, collection_name: str):
            return ("Commodore 64", "Atari ST") if collection_name == "1 COMPUTERS" else tuple()

        def _theme_games_for_collection(self, collection_name: str):
            return MainWindow._theme_games_for_collection(self, collection_name)

    fake = FakeMainWindow()
    original_scan = MainWindow._theme_games_for_collection.__globals__["scan_collection_definitions"]
    try:
        MainWindow._theme_games_for_collection.__globals__["scan_collection_definitions"] = lambda target: tuple()
        result = MainWindow._theme_games_for_collection(fake, "1 COMPUTERS")
    finally:
        MainWindow._theme_games_for_collection.__globals__["scan_collection_definitions"] = original_scan

    assert {(entry.game_name, entry.collection_name, entry.rom_path) for entry in result} == {
        ("Atari ST", "Atari ST", "Atari ST"),
        ("Commodore 64", "Commodore 64", "Commodore 64"),
    }


def test_resolve_game_theme_render_collection_placeholder_uses_collection_video() -> None:
    _ensure_app()

    class FakeMainWindow:
        def _theme_menu_entry_for_element(self, element, selected_entry, collection_games, collection_index):
            return selected_entry

        def _resolve_theme_game_media_root(self, display_entry):
            return None

        def _resolve_collection_theme_render(self, element, collection_name):
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.white)
            return ThemePreviewRenderData(pixmap=pixmap, video_path=Path("Q:/content/retrofe/collections/Commodore 64/medium_artwork/video/example.mp4"))

    element = themes.ThemePreviewElement(
        label="screenshot",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=400.0,
        height=300.0,
        layer=0,
    )
    game_entry = GameManifestEntry(
        game_name="Commodore 64",
        collection_name="Commodore 64",
        rom_path="Commodore 64",
    )

    render = MainWindow._resolve_game_theme_render(
        FakeMainWindow(),
        element,
        None,
        "1 COMPUTERS",
        game_entry,
        (game_entry,),
        1,
    )

    assert render is not None
    assert render.video_path is not None


def test_resolve_layout_theme_render_menu_placeholder_uses_child_system_logo(tmp_path: Path) -> None:
    _ensure_app()
    theme_root = tmp_path / "base_assets" / "layouts" / "Cafe80s"
    system_artwork = theme_root / "collections" / "Commodore 64" / "system_artwork"
    system_artwork.mkdir(parents=True, exist_ok=True)
    pixmap = QPixmap(32, 16)
    pixmap.fill(Qt.GlobalColor.white)
    assert pixmap.save(str(system_artwork / "logo.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="Cafe80s",
        root_dir=theme_root,
        layout_path=None,
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=tuple(),
    )
    element = themes.ThemePreviewElement(
        label="menu:logo 7 selected",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=300.0,
        height=100.0,
        layer=11,
    )
    game_entry = GameManifestEntry(
        game_name="Commodore 64",
        collection_name="Commodore 64",
        rom_path="Commodore 64",
    )

    class FakeMainWindow:
        def _target_dir(self):
            return tmp_path

        _resolve_collection_theme_render = MainWindow._resolve_collection_theme_render
        _resolve_layout_theme_render = MainWindow._resolve_layout_theme_render

    render = MainWindow._resolve_layout_theme_render(
        FakeMainWindow(),
        element,
        theme_entry,
        "Commodore 64",
        game_entry,
    )

    assert render is not None
    assert render.pixmap is not None
    assert not render.pixmap.isNull()


def test_resolve_layout_theme_render_collection_placeholder_uses_collection_video_fallback() -> None:
    _ensure_app()

    theme_entry = themes.ThemeCatalogEntry(
        name="LUNA OG",
        root_dir=Path("Q:/base_assets/layouts/LUNA OG"),
        layout_path=None,
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=tuple(),
    )
    element = themes.ThemePreviewElement(
        label="screenshot",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=480.0,
        height=360.0,
        layer=6,
    )
    game_entry = GameManifestEntry(
        game_name="1 COLLECTIONS",
        collection_name="1 COLLECTIONS",
        rom_path="1 COLLECTIONS",
        source_pack="1 COLLECTIONS",
        install_collection_name="1 COLLECTIONS",
    )

    class FakeMainWindow:
        def _resolve_collection_theme_render(self, resolved_element, collection_name):
            assert resolved_element is element
            assert collection_name == "1 COLLECTIONS"
            pixmap = QPixmap(32, 18)
            pixmap.fill(Qt.GlobalColor.white)
            return ThemePreviewRenderData(
                pixmap=pixmap,
                video_path=Path("Q:/base_assets/collections/1 COLLECTIONS/system_artwork/video.mp4"),
            )

    render = MainWindow._resolve_layout_theme_render(
        FakeMainWindow(),
        element,
        theme_entry,
        "Main",
        game_entry,
    )

    assert render is not None
    assert render.video_path == Path("Q:/base_assets/collections/1 COLLECTIONS/system_artwork/video.mp4")
    assert render.pixmap is not None


def test_find_first_collection_video_prefers_direct_video_file(tmp_path: Path) -> None:
    media_root = tmp_path / "system_artwork"
    media_root.mkdir(parents=True, exist_ok=True)
    direct_video = media_root / "video.mp4"
    direct_video.write_bytes(b"")
    video_dir = media_root / "video"
    video_dir.mkdir()
    nested_video = video_dir / "other.mp4"
    nested_video.write_bytes(b"")

    assert _find_first_collection_video(media_root) == direct_video


def test_resolve_layout_theme_render_menu_placeholder_prefers_collection_system_logo_before_child_theme_logo(tmp_path: Path) -> None:
    _ensure_app()
    target_root = tmp_path
    collection_system_artwork = target_root / "content" / "retrofe" / "collections" / "Epoch Super Cassette Vision" / "system_artwork"
    collection_system_artwork.mkdir(parents=True, exist_ok=True)
    collection_pixmap = QPixmap(400, 175)
    collection_pixmap.fill(Qt.GlobalColor.red)
    assert collection_pixmap.save(str(collection_system_artwork / "logo.png"))

    theme_root = tmp_path / "base_assets" / "layouts" / "Cyberpunkd"
    child_system_artwork = theme_root / "collections" / "Epoch Super Cassette Vision" / "system_artwork"
    child_system_artwork.mkdir(parents=True, exist_ok=True)
    child_pixmap = QPixmap(1920, 187)
    child_pixmap.fill(Qt.GlobalColor.blue)
    assert child_pixmap.save(str(child_system_artwork / "logo.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="Cyberpunkd",
        root_dir=theme_root,
        layout_path=None,
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=tuple(),
    )
    element = themes.ThemePreviewElement(
        label="menu:logo 5 selected",
        kind="menu",
        tag_name="item",
        slot_name="logo",
        value=None,
        x=0.0,
        y=0.0,
        width=300.0,
        height=100.0,
        layer=12,
    )
    game_entry = GameManifestEntry(
        game_name="Epoch Super Cassette Vision",
        collection_name="Epoch Super Cassette Vision",
        rom_path="Epoch Super Cassette Vision",
        source_pack="Epoch Super Cassette Vision",
        install_collection_name="Epoch Super Cassette Vision",
    )

    class FakeMainWindow:
        def _target_dir(self):
            return target_root

        _resolve_collection_theme_render = MainWindow._resolve_collection_theme_render
        _resolve_layout_theme_render = MainWindow._resolve_layout_theme_render

    render = MainWindow._resolve_layout_theme_render(
        FakeMainWindow(),
        element,
        theme_entry,
        "Epoch Super Cassette Vision",
        game_entry,
    )

    assert render is not None
    assert render.pixmap is not None
    assert render.pixmap.width() == 400
    assert render.pixmap.height() == 175


def test_resolve_layout_theme_render_non_menu_placeholder_uses_child_theme_system_artwork(tmp_path: Path) -> None:
    _ensure_app()
    theme_root = tmp_path / "base_assets" / "layouts" / "Cafe80s"
    child_system_artwork = theme_root / "collections" / "Atari Lynx" / "system_artwork"
    child_system_artwork.mkdir(parents=True, exist_ok=True)
    pixmap = QPixmap(40, 20)
    pixmap.fill(Qt.GlobalColor.white)
    assert pixmap.save(str(child_system_artwork / "device.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="Cafe80s",
        root_dir=theme_root,
        layout_path=None,
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=tuple(),
    )
    element = themes.ThemePreviewElement(
        label="device",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="device",
        value=None,
        x=0.0,
        y=0.0,
        width=300.0,
        height=100.0,
        layer=7,
    )
    game_entry = GameManifestEntry(
        game_name="Atari Lynx",
        collection_name="Atari Lynx",
        rom_path="Atari Lynx",
    )

    render = MainWindow._resolve_layout_theme_render(
        MainWindow.__new__(MainWindow),
        element,
        theme_entry,
        "1 HANDHELDS",
        game_entry,
    )

    assert render is not None
    assert render.pixmap is not None
    assert not render.pixmap.isNull()
    assert render.pixmap.width() == 40


def test_resolve_layout_theme_render_handheld_device_prefers_collection_system_artwork_when_max_box_is_authored(tmp_path: Path) -> None:
    _ensure_app()
    target = tmp_path / "target"
    theme_root = target / "base_assets" / "layouts" / "Cafe80s"
    child_system_artwork = theme_root / "collections" / "Atari Lynx" / "system_artwork"
    child_system_artwork.mkdir(parents=True, exist_ok=True)
    child_pixmap = QPixmap(40, 20)
    child_pixmap.fill(Qt.GlobalColor.white)
    assert child_pixmap.save(str(child_system_artwork / "device.png"))

    collection_system_artwork = target / "content" / "retrofe" / "collections" / "Atari Lynx" / "system_artwork"
    collection_system_artwork.mkdir(parents=True, exist_ok=True)
    collection_pixmap = QPixmap(60, 30)
    collection_pixmap.fill(Qt.GlobalColor.red)
    assert collection_pixmap.save(str(collection_system_artwork / "device.png"))

    theme_entry = themes.ThemeCatalogEntry(
        name="Cafe80s",
        root_dir=theme_root,
        layout_path=None,
        splash_path=None,
        collection_overrides=tuple(),
        common_slots=tuple(),
    )
    element = themes.ThemePreviewElement(
        label="device",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="device",
        value=None,
        x=770.0,
        y=250.0,
        width=0.0,
        height=0.0,
        layer=7,
        explicit_width=False,
        explicit_height=False,
        max_width=475.0,
        max_height=360.0,
        x_origin="center",
        y_origin="center",
    )
    game_entry = GameManifestEntry(
        game_name="Atari Lynx",
        collection_name="Atari Lynx",
        rom_path="Atari Lynx",
    )

    window = MainWindow.__new__(MainWindow)
    window._target_dir = lambda: target  # type: ignore[method-assign]

    render = MainWindow._resolve_layout_theme_render(
        window,
        element,
        theme_entry,
        "1 HANDHELDS",
        game_entry,
    )

    assert render is not None
    assert render.pixmap is not None
    assert not render.pixmap.isNull()
    assert render.pixmap.width() == 60


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


def test_handle_theme_preview_scroll_index_changed_marks_final_target_without_rebuilding_full_render() -> None:
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
        label="background",
        kind="reloadable_image",
        tag_name="reloadableImage",
        slot_name="artwork_front",
        value=None,
        x=0.0,
        y=0.0,
        width=100.0,
        height=100.0,
        layer=0,
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Fan Art Magazine",
        selected_collection="MAME",
        root_layout_path=None,
        active_layout_path=None,
        using_collection_override=False,
        canvas_width=768.0,
        canvas_height=1366.0,
        elements=(static_element, reload_element),
        collection_override_count=0,
        common_slots=(),
        system_slots=(),
    )
    game_a = GameManifestEntry(game_name="A", collection_name="MAME", rom_path="a.zip")
    game_b = GameManifestEntry(game_name="B", collection_name="MAME", rom_path="b.zip")

    class FakePreviewWidget:
        def __init__(self) -> None:
            self._wheel_anim_pending_finish = True
            self._wheel_anim_start_game_0 = 0
            self._wheel_anim_advance_count = 1
            self._wheel_anim_total_games = 2
            self.updated = None

        def set_render_data(self, data, transition=False) -> None:
            self.updated = (dict(data), transition)

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview = preview
            self._theme_preview_wheel_spinning = True
            self._selected_theme_collection_name = "MAME"
            self.themes_preview = FakePreviewWidget()
            self._theme_preview_render_data = {
                static_element: ThemePreviewRenderData(text="old-bg"),
                reload_element: ThemePreviewRenderData(text="old-title"),
            }
            self.synced = 0

        def _theme_games_for_collection(self, collection_name: str):
            assert collection_name == "MAME"
            return (game_a, game_b)

        def _build_theme_render_data_for_state(self, active_preview, selected_collection, game_entry, collection_games, collection_index, scroll_only=False):
            assert scroll_only is False
            assert active_preview is preview
            assert game_entry == game_b
            return {
                static_element: ThemePreviewRenderData(text="new-bg"),
                reload_element: ThemePreviewRenderData(text="new-title"),
            }

        def _sync_theme_preview_video_sessions(self) -> None:
            self.synced += 1

        def _sync_theme_preview_animation_controls(self) -> None:
            self.synced += 1

    fake = FakeMainWindow()

    MainWindow._handle_theme_preview_scroll_index_changed(fake, 1)

    assert fake.themes_preview.updated is None
    assert fake._theme_preview_promoted_final_zero_index == 1
    assert fake.synced == 0


def test_set_theme_preview_render_data_preserves_previous_video_frame_until_new_source_draws() -> None:
    _ensure_app()
    element = themes.ThemePreviewElement(
        label="preview-video",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=400.0,
        height=300.0,
        layer=5,
    )
    old_pixmap = QPixmap(32, 24)
    old_pixmap.fill()
    new_pixmap = QPixmap(48, 36)
    new_pixmap.fill()

    class FakePreviewWidget:
        def __init__(self) -> None:
            self.updated: tuple[dict[themes.ThemePreviewElement, ThemePreviewRenderData], bool] | None = None

        def set_render_data(self, data, transition=False) -> None:
            self.updated = (dict(data), transition)

    class FakeMainWindow:
        def __init__(self) -> None:
            self._theme_preview_render_data = {
                element: ThemePreviewRenderData(pixmap=old_pixmap, video_path=Path("old.mp4")),
            }
            self._theme_preview_promoted_final_zero_index = 7
            self.themes_preview = FakePreviewWidget()
            self.synced = 0

        def _sync_theme_preview_video_sessions(self) -> None:
            self.synced += 1

        def _sync_theme_preview_animation_controls(self) -> None:
            self.synced += 1

    fake = FakeMainWindow()

    MainWindow._set_theme_preview_render_data(
        fake,
        {element: ThemePreviewRenderData(pixmap=new_pixmap, video_path=Path("new.mp4"))},
        transition=False,
    )

    stored = fake._theme_preview_render_data[element]
    assert stored.video_path == Path("new.mp4")
    assert stored.pixmap is not None
    assert stored.pixmap.cacheKey() == old_pixmap.cacheKey()
    assert fake._theme_preview_promoted_final_zero_index is None
    assert fake.synced == 2
    assert fake.themes_preview.updated is not None
    sent_data, sent_transition = fake.themes_preview.updated
    assert sent_transition is False
    assert sent_data[element].video_path == Path("new.mp4")
    assert sent_data[element].pixmap is not None
    assert sent_data[element].pixmap.cacheKey() == old_pixmap.cacheKey()


def test_restart_idle_animation_seeds_first_cycle_from_current_effective_values() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="screenshot-video",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=400.0,
        height=300.0,
        layer=5,
        alpha=0.0,
        idle_anim_sets=((0.5, (("alpha", None, 1.0, "easeinquadratic"),)),),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Live Wallpapers",
        selected_collection="THEMES",
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
    widget._animation_enabled = True
    widget._idle_anim_values = {element: {"alpha": 1.0}}
    widget._event_anim_values = {}

    widget._restart_idle_animation()

    seeded = widget._idle_anim_values.get(element)
    assert seeded is not None
    assert seeded.get("alpha") == 1.0


def test_idle_animation_carries_forward_end_state_between_loops_for_implicit_from_values(monkeypatch) -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    element = themes.ThemePreviewElement(
        label="screenshot-video",
        kind="reloadable_video",
        tag_name="reloadableVideo",
        slot_name="screenshot",
        value=None,
        x=0.0,
        y=0.0,
        width=400.0,
        height=300.0,
        layer=5,
        alpha=0.0,
        idle_anim_sets=((0.5, (("alpha", None, 1.0, "easeinquadratic"),)),),
    )
    preview = themes.ThemeLayoutPreview(
        theme_name="Live Wallpapers",
        selected_collection="THEMES",
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
    widget._animation_enabled = True
    widget._idle_anim_seed_values = {element: {"alpha": 0.0}}
    widget._idle_anim_start_ms = 0.0
    monkeypatch.setattr("onesauce_companion.ui.main_window.time.monotonic", lambda: 0.75)

    widget._on_idle_anim_tick()

    values = widget._idle_anim_values.get(element)
    assert values is not None
    assert values.get("alpha") == 1.0


def test_on_wheel_anim_tick_emits_final_index_before_finishing() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    emitted_indices: list[int] = []
    finished: list[bool] = []
    widget.wheelAnimationIndexChanged.connect(emitted_indices.append)
    widget.wheelAnimationFinished.connect(lambda: finished.append(True))
    widget._wheel_anim_active = True
    widget._wheel_anim_start_game_0 = 4
    widget._wheel_anim_advance_count = 3
    widget._wheel_anim_total_games = 10
    widget._wheel_anim_duration_ms = 100
    widget._wheel_anim_start_ms = 0.0
    widget._wheel_anim_last_emitted_index = 4

    import onesauce_companion.ui.main_window as main_window_module

    original_monotonic = main_window_module.time.monotonic
    main_window_module.time.monotonic = lambda: 1.0
    try:
        widget._on_wheel_anim_tick()
        assert emitted_indices[-1] == 7
        assert widget._wheel_anim_pending_finish is True
        widget._complete_wheel_animation()
    finally:
        main_window_module.time.monotonic = original_monotonic

    assert finished == [True]


def test_on_wheel_anim_tick_snaps_last_scroll_position_to_final_advance_before_finish() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    widget._wheel_anim_active = True
    widget._wheel_anim_start_game_0 = 0
    widget._wheel_anim_advance_count = 5
    widget._wheel_anim_total_games = 20
    widget._wheel_anim_duration_ms = 100
    widget._wheel_anim_start_ms = 0.0
    widget._wheel_anim_last_scroll_pos = 4.72

    import onesauce_companion.ui.main_window as main_window_module

    original_monotonic = main_window_module.time.monotonic
    main_window_module.time.monotonic = lambda: 1.0
    try:
        widget._on_wheel_anim_tick()
    finally:
        main_window_module.time.monotonic = original_monotonic

    assert widget._wheel_anim_pending_finish is True
    assert widget._wheel_anim_last_scroll_pos == 5.0


def test_draw_animated_wheel_uses_scrolling_list_slot_tween_order() -> None:
    _ensure_app()
    widget = ThemeLayoutPreviewWidget()
    elements = [
        themes.ThemePreviewElement("slot0", "menu", "menu", "logo", None, 0.0, 100.0, 40.0, 40.0, 1, menu_position=1, menu_selected_position=2),
        themes.ThemePreviewElement("slot1", "menu", "menu", "logo", None, 100.0, 100.0, 40.0, 40.0, 1, selected=True, menu_position=2, menu_selected_position=2),
        themes.ThemePreviewElement("slot2", "menu", "menu", "logo", None, 200.0, 100.0, 40.0, 40.0, 1, menu_position=3, menu_selected_position=2),
    ]
    widget._wheel_anim_slot_elements = elements
    widget._wheel_anim_logos = {
        0: QPixmap(10, 10),
        1: QPixmap(11, 11),
        2: QPixmap(12, 12),
    }
    for pixmap in widget._wheel_anim_logos.values():
        pixmap.fill()
    widget._wheel_anim_sel_idx = 1
    widget._wheel_anim_extra_groups = []
    widget._wheel_anim_start_game_0 = 0
    widget._wheel_anim_advance_count = 1
    widget._wheel_anim_total_games = 10
    widget._wheel_anim_duration_ms = 1000
    widget._wheel_anim_start_ms = 0.0

    captured: dict[int, QRectF] = {}

    def capture(_painter, pixmap, _element, draw_rect, _clip_rect, _angle, _opacity=1.0):
        captured[pixmap.width()] = QRectF(draw_rect)

    widget._draw_wheel_logo = capture  # type: ignore[method-assign]
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        import onesauce_companion.ui.main_window as main_window_module

        original_monotonic = main_window_module.time.monotonic
        main_window_module.time.monotonic = lambda: 0.5
        try:
            widget._draw_animated_wheel(painter, QRectF(0.0, 0.0, 400.0, 400.0), 1.0, 1.0)
        finally:
            main_window_module.time.monotonic = original_monotonic
    finally:
        painter.end()

    # The wrap-around slot uses the newly loaded item and should tween from slot0 toward
    # the last scroll point, not remain pinned at the first slot.
    assert 12 in captured
    assert captured[12].x() > 50.0


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


def test_theme_games_for_subset_collection_uses_sub_rules_to_build_real_game_entries(tmp_path: Path) -> None:
    subset_dir = tmp_path / "appdata" / "retrofe" / "collections" / "02 ARCADE ALL"
    subset_dir.mkdir(parents=True, exist_ok=True)
    (subset_dir / "MAME.sub").write_text("bangball\n", encoding="utf-8")
    (subset_dir / "Daphne.sub").write_text("astron\n", encoding="utf-8")

    class FakeMainWindow:
        _theme_games_for_collection = MainWindow._theme_games_for_collection

        def __init__(self) -> None:
            self._theme_games_cache: dict[str, tuple[GameManifestEntry, ...]] = {}
            self._game_entries = (
                GameManifestEntry(game_name="bangball.zip", collection_name="MAME", rom_path="bangball.zip"),
                GameManifestEntry(game_name="other.zip", collection_name="MAME", rom_path="other.zip"),
                GameManifestEntry(game_name="astron.zip", collection_name="Daphne", rom_path="astron.zip"),
            )

        def _target_dir(self):
            return tmp_path

        def _child_collection_names(self, collection_name: str) -> tuple[str, ...]:
            return tuple()

        def _scan_collection_game_entries(self, collection_name: str) -> tuple[GameManifestEntry, ...]:
            return tuple()

        def _excluded_games_for_current_target(self):
            return frozenset()

    fake = FakeMainWindow()
    entries = fake._theme_games_for_collection("02 ARCADE ALL")

    assert [entry.rom_path for entry in entries] == ["astron.zip", "bangball.zip"]
    assert [entry.collection_name for entry in entries] == ["Daphne", "MAME"]
