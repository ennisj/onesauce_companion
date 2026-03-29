from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

_log = logging.getLogger(__name__)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_ATTR_RE = re.compile(r'([^\s=/>]+)\s*=\s*(".*?"|\'.*?\')', re.DOTALL)
_LUA_BUILD_FROM_XML_RE = re.compile(r'buildFromXmlFile\s*\(\s*["\']([^"\']+)["\']')

_VISUAL_TAGS = {
    "image": "image",
    "gif": "image",                                     # animated GIF — render first frame like a static image
    "reloadableimage": "reloadable_image",
    "reloadablepanningimage": "reloadable_panning_image",
    "video": "video",
    "reloadablevideo": "reloadable_video",
    "reloadablepanningvideo": "reloadable_video",       # panning video — same rendering as reloadable_video
    "text": "text",
    "reloadabletext": "reloadable_text",
    "reloadablescrollingtext": "reloadable_scrolling_text",
    "scrollingtext": "scrolling_text",
    "statustext": "text",                               # system status text — display like a regular text element
    "menu": "menu",
}

_RECT_DEFAULTS = {
    "image": (200.0, 140.0),
    "reloadable_image": (220.0, 160.0),
    "reloadable_panning_image": (220.0, 160.0),
    "video": (320.0, 180.0),
    "reloadable_video": (320.0, 180.0),
    "text": (260.0, 48.0),
    "reloadable_text": (260.0, 48.0),
    "reloadable_scrolling_text": (300.0, 120.0),
    "scrolling_text": (300.0, 120.0),
    "menu": (320.0, 220.0),
}


@dataclass(frozen=True)
class ThemeCatalogEntry:
    name: str
    root_dir: Path
    layout_path: Path | None
    splash_path: Path | None
    collection_overrides: tuple[str, ...]
    common_slots: tuple[str, ...]


@dataclass(frozen=True)
class ThemePreviewElement:
    label: str
    kind: str
    tag_name: str
    slot_name: str | None
    value: str | None
    x: float
    y: float
    width: float
    height: float
    layer: int | None
    source_path: str | None = None
    mode: str | None = None
    selected: bool = False
    transform_points: tuple[tuple[float, float], ...] = ()
    menu_position: int | None = None
    menu_selected_position: int | None = None
    text_fallback: bool = False
    font_path: str | None = None
    font_size: float | None = None
    load_font_size: float | None = None
    font_color: str | None = None
    text_format: str | None = None
    x_origin: str | None = None
    y_origin: str | None = None
    anchor_x: float | None = None
    anchor_y: float | None = None
    explicit_width: bool = False
    explicit_height: bool = False
    min_width: float | None = None
    min_height: float | None = None
    max_width: float | None = None
    max_height: float | None = None
    angle: float | None = None
    image_type: str | None = None  # imageType fallback attribute (used when type != imageType)
    alpha: float | None = None
    elem_id: str | None = None
    reflection_id: str | None = None
    reflection_dist: float | None = None
    reflection_scale: float | None = None
    zoom_scale_to: float | None = None
    pan_speed: float | None = None
    pan_zoom_speed: float | None = None
    pan_threshold: float | None = None
    image_width_hint: float | None = None
    image_min_height: float | None = None
    scroll_direction: str | None = None
    scroll_speed: float | None = None
    scroll_start_time: float | None = None
    scroll_end_time: float | None = None
    scroll_start_position: float | None = None
    text_alignment: str | None = None
    menu_scroll_reload: bool = False
    # Idle animation sets from <onMenuIdle>. Each set is (duration_seconds, steps) where
    # each step is (prop_name, from_val, to_val, algorithm). The preview currently uses
    # alpha and selected geometry pulse properties like width/maxHeight.
    idle_anim_sets: tuple[tuple[float, tuple[tuple[str, float, float, str], ...]], ...] = ()
    # Preview-state animation targets from non-idle event blocks such as onMenuEnter,
    # onHighlightEnter, and onMenuScroll. Each entry is
    # (event_name, menuIndex_expr, ((prop_name, to_val), ...)).
    event_anim_targets: tuple[tuple[str, str | None, tuple[tuple[str, float], ...]], ...] = ()
    # Parsed timed event animations for transient preview playback.
    event_anim_sets: tuple[
        tuple[
            str,
            str | None,
            tuple[tuple[float, tuple[tuple[str, float | None, float | None, str], ...]], ...],
        ],
        ...,
    ] = ()


@dataclass(frozen=True)
class ThemeLayoutPreview:
    theme_name: str
    selected_collection: str | None
    root_layout_path: Path | None
    active_layout_path: Path | None
    using_collection_override: bool
    canvas_width: float
    canvas_height: float
    elements: tuple[ThemePreviewElement, ...]
    collection_override_count: int
    common_slots: tuple[str, ...]
    system_slots: tuple[str, ...]
    layout_collection: str | None = None
    error: str | None = None


def scan_theme_catalog(target_dir: Path | None) -> tuple[ThemeCatalogEntry, ...]:
    themes_root = _themes_root(target_dir)
    if themes_root is None:
        return tuple()

    entries: list[ThemeCatalogEntry] = []
    for theme_dir in sorted((child for child in themes_root.iterdir() if child.is_dir()), key=lambda item: item.name.casefold()):
        root_layout = theme_dir / "layout.xml"
        if root_layout.exists():
            resolved_layout: Path | None = root_layout
        else:
            root_lua = theme_dir / "layout.lua"
            resolved_layout = _lua_xml_skeleton_path(root_lua, theme_dir) if root_lua.exists() else None
        splash_path = theme_dir / "splash.xml"
        entries.append(
            ThemeCatalogEntry(
                name=theme_dir.name,
                root_dir=theme_dir,
                layout_path=resolved_layout,
                splash_path=splash_path if splash_path.exists() else None,
                collection_overrides=_collection_override_names(theme_dir),
                common_slots=_common_slot_names(theme_dir),
            )
        )
    return tuple(entries)


def build_theme_layout_preview(
    target_dir: Path | None,
    theme_name: str,
    collection_name: str | None = None,
    layout_collection_name: str | None = None,
) -> ThemeLayoutPreview | None:
    theme_entry = next((entry for entry in scan_theme_catalog(target_dir) if entry.name == theme_name), None)
    if theme_entry is None:
        return None

    selected_collection = collection_name or None
    layout_source = layout_collection_name if layout_collection_name is not None else selected_collection
    collection_layout_path = _collection_layout_path(theme_entry.root_dir, layout_source)
    active_layout_path = collection_layout_path if collection_layout_path is not None and collection_layout_path.exists() else theme_entry.layout_path
    using_collection_override = active_layout_path is not None and collection_layout_path is not None and active_layout_path == collection_layout_path

    system_slots = _system_slot_names(theme_entry.root_dir, selected_collection) if selected_collection else tuple()
    if active_layout_path is None or not active_layout_path.exists():
        lua_root = theme_entry.root_dir / "layout.lua"
        lua_collection = (theme_entry.root_dir / "collections" / layout_source / "layout" / "layout.lua") if layout_source else None
        uses_lua = (lua_root.exists() or (lua_collection is not None and lua_collection.exists()))
        error_msg = (
            "This theme uses Lua-scripted layouts; no XML skeleton could be located for preview."
            if uses_lua else
            "No layout.xml file found for this theme."
        )
        return ThemeLayoutPreview(
            theme_name=theme_entry.name,
            selected_collection=selected_collection,
            root_layout_path=theme_entry.layout_path,
            active_layout_path=active_layout_path,
            using_collection_override=using_collection_override,
            canvas_width=1920.0,
            canvas_height=1080.0,
            elements=tuple(),
            collection_override_count=len(theme_entry.collection_overrides),
            common_slots=theme_entry.common_slots,
            system_slots=system_slots,
            error=error_msg,
        )

    root, parse_error = _parse_layout_root(active_layout_path)
    if root is None and collection_layout_path is not None and theme_entry.layout_path is not None and theme_entry.layout_path.exists():
        fallback_root, fallback_error = _parse_layout_root(theme_entry.layout_path)
        if fallback_root is not None:
            root = fallback_root
            active_layout_path = theme_entry.layout_path
            using_collection_override = False
            parse_error = f"Collection layout could not be repaired; showing the root layout instead. {parse_error or fallback_error or ''}".strip()

    if root is None:
        return ThemeLayoutPreview(
            theme_name=theme_entry.name,
            selected_collection=selected_collection,
            root_layout_path=theme_entry.layout_path,
            active_layout_path=active_layout_path,
            using_collection_override=using_collection_override,
            canvas_width=1920.0,
            canvas_height=1080.0,
            elements=tuple(),
            collection_override_count=len(theme_entry.collection_overrides),
            common_slots=theme_entry.common_slots,
            system_slots=system_slots,
            error=parse_error or "Layout XML could not be parsed.",
        )

    layout_attrs = _normalized_attrib(root)
    canvas_width = _float_value(layout_attrs.get("width"), 1920.0) or 1920.0
    canvas_height = _float_value(layout_attrs.get("height"), 1080.0) or 1080.0

    inherited_style = {
        "font": layout_attrs.get("font"),
        "fontsize": layout_attrs.get("fontsize"),
        "loadfontsize": layout_attrs.get("loadfontsize"),
        "fontcolor": layout_attrs.get("fontcolor"),
        "textformat": layout_attrs.get("textformat"),
    }

    elements: list[ThemePreviewElement] = []
    _collect_preview_elements(root, active_layout_path, canvas_width, canvas_height, inherited_style, elements)

    elements.sort(key=lambda item: (item.layer if item.layer is not None else -1, item.width * item.height, item.label.casefold()))
    _log.info("build_theme_layout_preview: theme=%r collection=%r layout_path=%s elements=%d error=%r",
              theme_entry.name, selected_collection, active_layout_path, len(elements), parse_error)
    return ThemeLayoutPreview(
        theme_name=theme_entry.name,
        selected_collection=selected_collection,
        root_layout_path=theme_entry.layout_path,
        active_layout_path=active_layout_path,
        using_collection_override=using_collection_override,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        elements=tuple(elements),
        collection_override_count=len(theme_entry.collection_overrides),
        common_slots=theme_entry.common_slots,
        system_slots=system_slots,
        layout_collection=layout_source,
        error=parse_error,
    )


def _collect_preview_elements(
    node: ET.Element,
    layout_path: Path,
    canvas_width: float,
    canvas_height: float,
    inherited_style: dict[str, str | None],
    elements: list[ThemePreviewElement],
) -> None:
    for child in node:
        tag_name = _local_tag_name(child.tag)
        if tag_name in {"container", "view"}:
            _collect_preview_elements(child, layout_path, canvas_width, canvas_height, inherited_style, elements)
            continue
        kind = _VISUAL_TAGS.get(tag_name)
        if kind is None:
            continue
        if kind == "menu":
            new_menu_items = _parse_menu_elements(child, layout_path, canvas_width, canvas_height, inherited_style)
            if new_menu_items:
                # When multiple menus share the same imageType/slot (e.g. two logo wheels),
                # keep only the last definition — the earlier one is typically a transition overlay.
                slot = new_menu_items[0].slot_name
                elements[:] = [e for e in elements if not (e.kind == "menu" and e.slot_name == slot)]
                elements.extend(new_menu_items)
            continue
        preview_element = _parse_preview_element(child, layout_path, canvas_width, canvas_height, kind, inherited_style)
        if preview_element is not None:
            elements.append(preview_element)


def _parse_idle_anim_sets(
    node: ET.Element,
    base_values: dict[str, float],
) -> tuple[tuple[float, tuple[tuple[str, float, float, str], ...]], ...]:
    """Parse <onMenuIdle> or <onIdle> child animations. Returns resolved (duration, steps) tuples."""
    idle_node = next(
        (c for c in node if _local_tag_name(c.tag).casefold() == "onmenuidle"),
        None,
    ) or next(
        (c for c in node if _local_tag_name(c.tag).casefold() == "onidle"),
        None,
    )
    if idle_node is None:
        return ()
    sets: list[tuple[float, tuple[tuple[str, float, float, str], ...]]] = []
    current_values = dict(base_values)
    for set_node in idle_node:
        if _local_tag_name(set_node.tag).casefold() != "set":
            continue
        set_attrs = _normalized_attrib(set_node)
        duration = _float_value(set_attrs.get("duration")) or 0.0
        steps: list[tuple[str, float, float, str]] = []
        for anim_node in set_node:
            if _local_tag_name(anim_node.tag).casefold() != "animate":
                continue
            anim_attrs = _normalized_attrib(anim_node)
            prop_name = anim_attrs.get("type", "").casefold()
            if prop_name not in {"alpha", "width", "height", "maxwidth", "maxheight"}:
                continue
            to_val = _float_value(anim_attrs.get("to"))
            if to_val is None:
                continue
            from_raw = _float_value(anim_attrs.get("from"))
            from_val = from_raw if from_raw is not None else current_values.get(prop_name)
            if from_val is None:
                continue
            algorithm = (anim_attrs.get("algorithm") or "linear").casefold()
            steps.append((prop_name, from_val, to_val, algorithm))
        # Advance current values to end of this set
        for prop_name, _, to_v, _ in steps:
            current_values[prop_name] = to_v
        sets.append((duration, tuple(steps)))
    return tuple(sets)


def _parse_event_anim_targets(
    node: ET.Element,
) -> tuple[tuple[str, str | None, tuple[tuple[str, float], ...]], ...]:
    supported_events = {
        "onmenuenter": "menuenter",
        "onhighlightenter": "highlightenter",
        "onmenuscroll": "menuscroll",
    }
    supported_props = {
        "alpha",
        "width",
        "height",
        "maxwidth",
        "maxheight",
        "x",
        "y",
        "xoffset",
        "yoffset",
    }
    targets: list[tuple[str, str | None, tuple[tuple[str, float], ...]]] = []
    for event_node in node:
        event_name = supported_events.get(_local_tag_name(event_node.tag).casefold())
        if event_name is None:
            continue
        event_attrs = _normalized_attrib(event_node)
        menu_index = event_attrs.get("menuindex")
        event_values: dict[str, float] = {}
        for set_node in event_node:
            if _local_tag_name(set_node.tag).casefold() != "set":
                continue
            for anim_node in set_node:
                if _local_tag_name(anim_node.tag).casefold() != "animate":
                    continue
                anim_attrs = _normalized_attrib(anim_node)
                prop_name = anim_attrs.get("type", "").casefold()
                if prop_name not in supported_props:
                    continue
                to_val = _float_value(anim_attrs.get("to"))
                if to_val is None:
                    continue
                event_values[prop_name] = to_val
        if event_values:
            targets.append((event_name, menu_index, tuple(event_values.items())))
    return tuple(targets)


def _parse_event_anim_sets(
    node: ET.Element,
    base_values: dict[str, float],
) -> tuple[
    tuple[
        str,
        str | None,
        tuple[tuple[float, tuple[tuple[str, float | None, float | None, str], ...]], ...],
    ],
    ...,
]:
    supported_events = {
        "onmenuenter": "menuenter",
        "onhighlightenter": "highlightenter",
        "onmenuscroll": "menuscroll",
    }
    supported_props = {
        "alpha",
        "width",
        "height",
        "maxwidth",
        "maxheight",
        "x",
        "y",
        "xoffset",
        "yoffset",
    }
    event_sets: list[
        tuple[
            str,
            str | None,
            tuple[tuple[float, tuple[tuple[str, float | None, float | None, str], ...]], ...],
        ]
    ] = []
    for event_node in node:
        event_name = supported_events.get(_local_tag_name(event_node.tag).casefold())
        if event_name is None:
            continue
        event_attrs = _normalized_attrib(event_node)
        menu_index = event_attrs.get("menuindex")
        current_values = dict(base_values)
        parsed_sets: list[tuple[float, tuple[tuple[str, float | None, float | None, str], ...]]] = []
        for set_node in event_node:
            if _local_tag_name(set_node.tag).casefold() != "set":
                continue
            set_attrs = _normalized_attrib(set_node)
            duration = _float_value(set_attrs.get("duration")) or 0.0
            steps: list[tuple[str, float | None, float | None, str]] = []
            for anim_node in set_node:
                if _local_tag_name(anim_node.tag).casefold() != "animate":
                    continue
                anim_attrs = _normalized_attrib(anim_node)
                prop_name = anim_attrs.get("type", "").casefold()
                algorithm = (anim_attrs.get("algorithm") or "linear").casefold()
                if prop_name == "nop":
                    steps.append((prop_name, None, None, algorithm))
                    continue
                if prop_name not in supported_props:
                    continue
                to_val = _float_value(anim_attrs.get("to"))
                from_raw = _float_value(anim_attrs.get("from"))
                from_val = from_raw if from_raw is not None else current_values.get(prop_name)
                steps.append((prop_name, from_val, to_val, algorithm))
                if to_val is not None:
                    current_values[prop_name] = to_val
            parsed_sets.append((duration, tuple(steps)))
        if parsed_sets:
            event_sets.append((event_name, menu_index, tuple(parsed_sets)))
    return tuple(event_sets)


def _parse_preview_element(
    node: ET.Element,
    layout_path: Path,
    canvas_width: float,
    canvas_height: float,
    kind: str,
    inherited_style: dict[str, str | None],
) -> ThemePreviewElement | None:
    attrs = _normalized_attrib(node)
    source_path = attrs.get("src")
    resolved_source_path = _resolve_source_path(layout_path, source_path)
    font_value = attrs.get("font") or inherited_style.get("font")
    resolved_font_path = _resolve_source_path(layout_path, font_value)
    rect = _resolve_rect(attrs, canvas_width, canvas_height, kind, resolved_source_path)
    if rect is None:
        return None
    x, y, width, height = rect
    layer = _int_value(attrs.get("layer"))
    transform_points = _transform_points(attrs.get("transform"))
    base_alpha = _float_value(attrs.get("alpha")) or 1.0
    idle_base_values: dict[str, float] = {"alpha": base_alpha}
    for attr_name, prop_name in (
        ("width", "width"),
        ("height", "height"),
        ("maxwidth", "maxwidth"),
        ("maxheight", "maxheight"),
    ):
        value = _float_value(attrs.get(attr_name))
        if value is not None:
            idle_base_values[prop_name] = value
    return ThemePreviewElement(
        label=_label_for_node(node, kind),
        kind=kind,
        tag_name=_local_tag_name(node.tag),
        slot_name=attrs.get("type") or attrs.get("imagetype") or ("video" if kind == "reloadable_video" else None),
        value=attrs.get("value"),
        x=x,
        y=y,
        width=width,
        height=height,
        layer=layer,
        source_path=resolved_source_path,
        mode=attrs.get("mode"),
        transform_points=transform_points or tuple(),
        text_fallback=(attrs.get("textfallback", "").casefold() in {"true", "1", "yes"}),
        font_path=resolved_font_path,
        font_size=_float_value(attrs.get("fontsize") or inherited_style.get("fontsize")),
        load_font_size=_float_value(attrs.get("loadfontsize") or inherited_style.get("loadfontsize")),
        font_color=attrs.get("fontcolor") or inherited_style.get("fontcolor"),
        text_format=attrs.get("textformat") or inherited_style.get("textformat"),
        x_origin=attrs.get("xorigin"),
        y_origin=attrs.get("yorigin"),
        anchor_x=_float_value(attrs.get("x")),
        anchor_y=_float_value(attrs.get("y")),
        explicit_width=bool(attrs.get("width") or attrs.get("containerwidth")),
        explicit_height=bool(attrs.get("height") or attrs.get("containerheight")),
        min_width=_float_value(attrs.get("minwidth")),
        min_height=_float_value(attrs.get("minheight")),
        max_width=_float_value(attrs.get("maxwidth")),
        max_height=_float_value(attrs.get("maxheight")),
        angle=_float_value(attrs.get("angle")),
        image_type=attrs.get("imagetype"),
        alpha=_float_value(attrs.get("alpha")),
        elem_id=attrs.get("id") or None,
        reflection_id=attrs.get("reflectionid") or None,
        reflection_dist=_float_value(attrs.get("reflectiondist")),
        reflection_scale=_float_value(attrs.get("reflectionscale")),
        zoom_scale_to=_float_value(attrs.get("zoomscaleto")),
        pan_speed=_float_value(attrs.get("speed")),
        pan_zoom_speed=_float_value(attrs.get("zoomspeed")),
        pan_threshold=_float_value(attrs.get("threshold")),
        image_width_hint=_float_value(attrs.get("imagewidth")),
        image_min_height=_float_value(attrs.get("imageminheight")),
        idle_anim_sets=_parse_idle_anim_sets(node, idle_base_values),
        event_anim_targets=_parse_event_anim_targets(node),
        event_anim_sets=_parse_event_anim_sets(node, idle_base_values),
        scroll_direction=attrs.get("direction"),
        scroll_speed=_float_value(attrs.get("scrollingspeed")),
        scroll_start_time=_float_value(attrs.get("starttime")),
        scroll_end_time=_float_value(attrs.get("endtime")),
        scroll_start_position=_float_value(attrs.get("startposition")),
        text_alignment=attrs.get("alignment"),
        menu_scroll_reload=(attrs.get("menuscrollreload", "").casefold() in {"true", "1", "yes"}),
    )


def _parse_menu_elements(
    node: ET.Element,
    layout_path: Path,
    canvas_width: float,
    canvas_height: float,
    inherited_style: dict[str, str | None],
) -> list[ThemePreviewElement]:
    menu_attrs = _normalized_attrib(node)
    item_defaults: dict[str, str] = {}
    elements: list[ThemePreviewElement] = []
    menu_label = menu_attrs.get("imagetype") or menu_attrs.get("type") or "menu"
    source_path = _resolve_source_path(layout_path, menu_attrs.get("src"))
    font_value = menu_attrs.get("font") or inherited_style.get("font")
    resolved_font_path = _resolve_source_path(layout_path, font_value)
    item_number = 0
    pending: list[ThemePreviewElement] = []
    for child in node:
        child_tag = _local_tag_name(child.tag)
        if child_tag == "itemdefaults":
            item_defaults = _normalized_attrib(child)
            continue
        if child_tag != "item":
            continue
        item_attrs = dict(menu_attrs)
        item_attrs.update(item_defaults)
        item_attrs.update(_normalized_attrib(child))
        alpha_value = _float_value(item_attrs.get("alpha"))
        selected = item_attrs.get("selected", "").casefold() == "true"
        if alpha_value is not None and alpha_value <= 0 and not selected:
            continue
        rect = _resolve_rect(item_attrs, canvas_width, canvas_height, "menu", source_path)
        if rect is not None:
            item_number += 1
            layer = _int_value(item_attrs.get("layer")) or _int_value(item_defaults.get("layer")) or _int_value(menu_attrs.get("layer"))
            label = f"menu:{menu_label} {item_number}"
            if selected:
                label += " selected"
            pending.append(
                ThemePreviewElement(
                    label=label,
                    kind="menu",
                    tag_name="menu",
                    slot_name=menu_attrs.get("imagetype") or menu_attrs.get("type"),
                    value=menu_attrs.get("value"),
                    x=rect[0],
                    y=rect[1],
                    width=max(1.0, rect[2]),
                    height=max(1.0, rect[3]),
                    layer=layer,
                    source_path=source_path,
                    mode=menu_attrs.get("mode"),
                    selected=selected,
                    menu_position=item_number,
                    text_fallback=(item_attrs.get("textfallback", "").casefold() in {"true", "1", "yes"}),
                    font_path=resolved_font_path,
                    font_size=_float_value(item_attrs.get("fontsize") or inherited_style.get("fontsize")),
                    load_font_size=_float_value(item_attrs.get("loadfontsize") or inherited_style.get("loadfontsize")),
                    font_color=item_attrs.get("fontcolor") or inherited_style.get("fontcolor"),
                    text_format=item_attrs.get("textformat") or inherited_style.get("textformat"),
                    x_origin=item_attrs.get("xorigin"),
                    y_origin=item_attrs.get("yorigin"),
                    anchor_x=_float_value(item_attrs.get("x")),
                    anchor_y=_float_value(item_attrs.get("y")),
                    explicit_width=bool(item_attrs.get("width") or item_attrs.get("containerwidth")),
                    explicit_height=bool(item_attrs.get("height") or item_attrs.get("containerheight")),
                    min_width=_float_value(item_attrs.get("minwidth")),
                    min_height=_float_value(item_attrs.get("minheight")),
                    max_width=_float_value(item_attrs.get("maxwidth")),
                    max_height=_float_value(item_attrs.get("maxheight")),
                    angle=_float_value(item_attrs.get("angle")),
                    image_type=None,
                    alpha=_float_value(item_attrs.get("alpha")),
                    event_anim_targets=_parse_event_anim_targets(child),
                    event_anim_sets=_parse_event_anim_sets(child, {"alpha": _float_value(item_attrs.get("alpha")) or 1.0}),
                    menu_scroll_reload=(item_attrs.get("menuscrollreload", "").casefold() in {"true", "1", "yes"}),
                )
            )

    if pending:
        # selectedOffset (0-based) overrides scanning items for selected="true".
        selected_offset_raw = _int_value(menu_attrs.get("selectedoffset"))
        if selected_offset_raw is not None:
            selected_position: int | None = selected_offset_raw + 1
        else:
            selected_position = next((element.menu_position for element in pending if element.selected), None)
        return [
            ThemePreviewElement(
                label=element.label,
                kind=element.kind,
                tag_name=element.tag_name,
                slot_name=element.slot_name,
                value=element.value,
                x=element.x,
                y=element.y,
                width=element.width,
                height=element.height,
                layer=element.layer,
                source_path=element.source_path,
                mode=element.mode,
                selected=(element.menu_position == selected_position),
                transform_points=element.transform_points,
                menu_position=element.menu_position,
                menu_selected_position=selected_position,
                text_fallback=element.text_fallback,
                font_path=element.font_path,
                font_size=element.font_size,
                load_font_size=element.load_font_size,
                font_color=element.font_color,
                text_format=element.text_format,
                x_origin=element.x_origin,
                y_origin=element.y_origin,
                anchor_x=element.anchor_x,
                anchor_y=element.anchor_y,
                explicit_width=element.explicit_width,
                explicit_height=element.explicit_height,
                min_width=element.min_width,
                min_height=element.min_height,
                max_width=element.max_width,
                max_height=element.max_height,
                angle=element.angle,
                image_type=element.image_type,
                alpha=element.alpha,
                zoom_scale_to=element.zoom_scale_to,
                pan_speed=element.pan_speed,
                pan_zoom_speed=element.pan_zoom_speed,
                pan_threshold=element.pan_threshold,
                    image_width_hint=element.image_width_hint,
                    image_min_height=element.image_min_height,
                    event_anim_targets=element.event_anim_targets,
                    event_anim_sets=element.event_anim_sets,
                    scroll_direction=element.scroll_direction,
                    scroll_speed=element.scroll_speed,
                    scroll_start_time=element.scroll_start_time,
                    scroll_end_time=element.scroll_end_time,
                    scroll_start_position=element.scroll_start_position,
                    text_alignment=element.text_alignment,
                    menu_scroll_reload=element.menu_scroll_reload,
                )
            for element in pending
        ]

    rect = _resolve_rect({**menu_attrs, **item_defaults}, canvas_width, canvas_height, "menu", source_path)
    if rect is None:
        return []
    layer = _int_value(item_defaults.get("layer")) or _int_value(menu_attrs.get("layer"))
    selected_offset_raw = _int_value(menu_attrs.get("selectedoffset"))
    synthesized_selected_pos = (selected_offset_raw + 1) if selected_offset_raw is not None else 1
    return [
        ThemePreviewElement(
            label=f"menu:{menu_label}",
            kind="menu",
            tag_name="menu",
            slot_name=menu_attrs.get("imagetype") or menu_attrs.get("type"),
            value=menu_attrs.get("value"),
            x=rect[0],
            y=rect[1],
            width=max(1.0, rect[2]),
            height=max(1.0, rect[3]),
            layer=layer,
            source_path=source_path,
            mode=menu_attrs.get("mode"),
            selected=False,
            menu_position=1,
            menu_selected_position=synthesized_selected_pos,
            text_fallback=(menu_attrs.get("textfallback", "").casefold() in {"true", "1", "yes"}),
            font_path=resolved_font_path,
            font_size=_float_value(menu_attrs.get("fontsize") or inherited_style.get("fontsize")),
            load_font_size=_float_value(menu_attrs.get("loadfontsize") or inherited_style.get("loadfontsize")),
            font_color=menu_attrs.get("fontcolor") or inherited_style.get("fontcolor"),
            text_format=menu_attrs.get("textformat") or inherited_style.get("textformat"),
            x_origin=menu_attrs.get("xorigin"),
            y_origin=menu_attrs.get("yorigin"),
            anchor_x=_float_value(menu_attrs.get("x")),
            anchor_y=_float_value(menu_attrs.get("y")),
            explicit_width=bool(menu_attrs.get("width") or menu_attrs.get("containerwidth")),
            explicit_height=bool(menu_attrs.get("height") or menu_attrs.get("containerheight")),
            min_width=_float_value(menu_attrs.get("minwidth")),
            min_height=_float_value(menu_attrs.get("minheight")),
            max_width=_float_value(menu_attrs.get("maxwidth")),
            max_height=_float_value(menu_attrs.get("maxheight")),
            angle=_float_value(menu_attrs.get("angle")),
            image_type=None,
            alpha=_float_value(menu_attrs.get("alpha")),
            event_anim_targets=_parse_event_anim_targets(node),
            event_anim_sets=_parse_event_anim_sets(node, {"alpha": _float_value(menu_attrs.get("alpha")) or 1.0}),
            menu_scroll_reload=(menu_attrs.get("menuscrollreload", "").casefold() in {"true", "1", "yes"}),
        )
    ]


def _resolve_rect(
    attrs: dict[str, str],
    canvas_width: float,
    canvas_height: float,
    kind: str,
    source_path: str | None = None,
) -> tuple[float, float, float, float] | None:
    transform_rect = _transform_rect(attrs.get("transform"))
    if transform_rect is not None:
        return transform_rect

    x = _float_value(attrs.get("containerx"))
    y = _float_value(attrs.get("containery"))
    width = _float_value(attrs.get("containerwidth"))
    height = _float_value(attrs.get("containerheight"))
    if x is not None and y is not None and width is not None and height is not None:
        return (x, y, max(1.0, width), max(1.0, height))

    default_width, default_height = _RECT_DEFAULTS[kind]
    width_value = attrs.get("width")
    height_value = attrs.get("height")
    if width_value is None and (height_value or "").casefold() == "stretch" and _should_fill_missing_dimension(attrs, axis="x", kind=kind, source_path=source_path):
        width_value = "stretch"
    if height_value is None and (width_value or "").casefold() == "stretch" and _should_fill_missing_dimension(attrs, axis="y", kind=kind, source_path=source_path):
        height_value = "stretch"
    width = _resolve_dimension(width_value, canvas_width, default_width)
    height = _resolve_dimension(height_value, canvas_height, default_height)
    intrinsic_size = _intrinsic_media_dimensions(source_path)

    if width is None and height is None:
        if intrinsic_size is not None:
            width, height = intrinsic_size
        else:
            width = default_width
            height = default_height
    elif width is None:
        if intrinsic_size is not None and intrinsic_size[1] > 0:
            width = height * (intrinsic_size[0] / intrinsic_size[1]) if height is not None else intrinsic_size[0]
        else:
            width = max(default_width * 0.45, height * 1.2 if height is not None else default_width)
    elif height is None:
        if intrinsic_size is not None and intrinsic_size[0] > 0:
            height = width * (intrinsic_size[1] / intrinsic_size[0]) if width is not None else intrinsic_size[1]
        else:
            height = max(default_height * 0.45, width * 0.6 if width is not None else default_height)

    if width is None or height is None:
        return None

    min_width = _float_value(attrs.get("minwidth"))
    min_height = _float_value(attrs.get("minheight"))

    width, height = _apply_size_constraints(
        width,
        height,
        min_width=min_width,
        min_height=min_height,
        max_width=_float_value(attrs.get("maxwidth")),
        max_height=_float_value(attrs.get("maxheight")),
    )

    x = _resolve_position(
        attrs.get("x"),
        attrs.get("xorigin"),
        canvas_width,
        width,
        _float_value(attrs.get("xoffset"), 0.0) or 0.0,
    )
    y = _resolve_position(
        attrs.get("y"),
        attrs.get("yorigin"),
        canvas_height,
        height,
        _float_value(attrs.get("yoffset"), 0.0) or 0.0,
    )
    return (x, y, max(1.0, width), max(1.0, height))


def _apply_size_constraints(
    width: float,
    height: float,
    *,
    min_width: float | None,
    min_height: float | None,
    max_width: float | None,
    max_height: float | None,
) -> tuple[float, float]:
    """Apply RetroFE-like min/max constraints while preserving aspect ratio."""
    if width <= 0 or height <= 0:
        return (width, height)

    if min_width is not None and min_width > 0 and width < min_width:
        scale = min_width / width
        width = min_width
        height *= scale
    if min_height is not None and min_height > 0 and height < min_height:
        scale = min_height / height
        height = min_height
        width *= scale

    if max_width is not None and max_width > 0 and width > max_width:
        scale = max_width / width
        width = max_width
        height *= scale
    if max_height is not None and max_height > 0 and height > max_height:
        scale = max_height / height
        height = max_height
        width *= scale

    return (width, height)


def _should_fill_missing_dimension(attrs: dict[str, str], axis: str, kind: str, source_path: str | None = None) -> bool:
    if kind not in {"image", "reloadable_image", "video", "reloadable_video"}:
        return False
    if source_path is not None and _intrinsic_media_dimensions(source_path) is not None:
        return False
    if axis == "x":
        return not any(attrs.get(key) for key in ("x", "xorigin", "xoffset", "containerx", "containerwidth"))
    if axis == "y":
        return not any(attrs.get(key) for key in ("y", "yorigin", "yoffset", "containery", "containerheight"))
    return False


def _resolve_position(value: str | None, origin: str | None, canvas_size: float, size: float, offset: float) -> float:
    origin_key = (origin or "").casefold()
    value_key = (value or "").casefold()

    if value_key in {"left", "top"}:
        base = 0.0
    elif value_key in {"right", "bottom"}:
        base = canvas_size - size
    elif value_key == "center":
        base = (canvas_size - size) / 2.0
    else:
        numeric_value = _float_value(value, 0.0) or 0.0
        if origin_key in {"center", "middle"}:
            base = numeric_value - size / 2.0
        elif origin_key in {"right", "bottom"}:
            base = numeric_value - size
        else:
            base = numeric_value
    return base + offset


def _resolve_dimension(value: str | None, canvas_size: float, default: float) -> float | None:
    if value is None:
        return None
    value_key = value.casefold()
    if value_key == "stretch":
        return canvas_size
    if value_key in {"center", "left", "right", "top", "bottom"}:
        return default
    numeric_value = _float_value(value)
    return numeric_value if numeric_value is not None and numeric_value > 0 else None


def _label_for_node(node: ET.Element, kind: str) -> str:
    attrs = _normalized_attrib(node)
    if kind == "menu":
        label = attrs.get("imagetype") or attrs.get("type") or "menu"
        return f"menu:{label}"
    for key in ("type", "imagetype", "value"):
        value = attrs.get(key)
        if value:
            return _trim_label(value)
    source_path = attrs.get("src")
    if source_path:
        return _trim_label(Path(source_path).stem or source_path)
    return _trim_label(kind.replace("_", " "))


def _trim_label(value: str) -> str:
    compact = " ".join(value.replace("\n", " ").split())
    return compact if len(compact) <= 32 else compact[:29].rstrip() + "..."


def _transform_rect(transform_value: str | None) -> tuple[float, float, float, float] | None:
    points = _transform_points(transform_value)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(1.0, max(xs) - min(xs)), max(1.0, max(ys) - min(ys)))


def _transform_points(transform_value: str | None) -> tuple[tuple[float, float], ...]:
    if not transform_value:
        return tuple()
    points = [(float(x), float(y)) for x, y in re.findall(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", transform_value)]
    if len(points) >= 4:
        return tuple(points[-4:])
    return tuple(points)


def _collection_override_names(theme_dir: Path) -> tuple[str, ...]:
    collections_root = theme_dir / "collections"
    if not collections_root.exists():
        return tuple()
    names = [
        child.name
        for child in collections_root.iterdir()
        if child.is_dir() and child.name != "_common" and _directory_has_files(child)
    ]
    names.sort(key=str.casefold)
    return tuple(names)


def _common_slot_names(theme_dir: Path) -> tuple[str, ...]:
    common_root = theme_dir / "collections" / "_common" / "medium_artwork"
    if not common_root.exists():
        return tuple()
    names = [child.name for child in common_root.iterdir() if child.is_dir()]
    names.sort(key=str.casefold)
    return tuple(names)


def _system_slot_names(theme_dir: Path, collection_name: str | None) -> tuple[str, ...]:
    if not collection_name:
        return tuple()
    system_root = theme_dir / "collections" / collection_name / "system_artwork"
    if not system_root.exists():
        return tuple()
    names = [child.name for child in system_root.iterdir() if child.is_dir()]
    names.sort(key=str.casefold)
    return tuple(names)


def _collection_layout_path(theme_dir: Path, collection_name: str | None) -> Path | None:
    if not collection_name:
        return None
    xml_candidate = theme_dir / "collections" / collection_name / "layout" / "layout.xml"
    if xml_candidate.exists():
        return xml_candidate
    lua_candidate = theme_dir / "collections" / collection_name / "layout" / "layout.lua"
    if lua_candidate.exists():
        return _lua_xml_skeleton_path(lua_candidate, theme_dir)
    return None


_LUA_SKELETON_NAMES = (
    "non_arcade_games.xml",
    "arcade_games.xml",
    "arcade_systems.xml",
    "non_arcade_systems.xml",
)


def _lua_xml_skeleton_path(lua_path: Path, theme_dir: Path) -> Path | None:
    """Scan a Lua layout file for buildFromXmlFile() and return the resolved XML skeleton path.

    Falls back to probing known shared skeleton names under collections/ when the
    Lua file does not contain a simple string literal path (e.g. it delegates to a
    helper module that constructs the path at runtime).
    """
    try:
        lua_text = lua_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = _LUA_BUILD_FROM_XML_RE.search(lua_text)
    if match is not None:
        rel_path = match.group(1)
        # Paths are typically relative to the Lua file's directory (e.g. "../../arcade_games.xml")
        candidate = (lua_path.parent / rel_path).resolve()
        if candidate.exists():
            return candidate
        # Fallback: relative to the theme root
        candidate2 = (theme_dir / rel_path).resolve()
        if candidate2.exists():
            return candidate2
    # No extractable path — probe for known shared skeleton names (LUNA OG-style themes)
    for skeleton_name in _LUA_SKELETON_NAMES:
        skeleton = theme_dir / "collections" / skeleton_name
        if skeleton.exists():
            return skeleton
    return None


def _parse_layout_root(layout_path: Path) -> tuple[ET.Element | None, str | None]:
    try:
        raw_xml = layout_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return (None, str(exc))

    try:
        return (ET.fromstring(raw_xml), None)
    except ET.ParseError as exc:
        sanitized_xml = _sanitize_layout_xml(raw_xml)
        try:
            return (ET.fromstring(sanitized_xml), f"Recovered from malformed XML: {exc}")
        except ET.ParseError as sanitized_exc:
            _log.error("Layout XML parse failed even after sanitization: %s — %s", layout_path, sanitized_exc)
            return (None, f"{exc}; sanitized parse failed: {sanitized_exc}")


def _sanitize_layout_xml(raw_xml: str) -> str:
    # Hardcoded fix for LUNA OG typo: 144/166 collection layout files have
    # <onEnter>...</onMenuEnter> — opening tag is the typo; should be <onMenuEnter>.
    raw_xml = re.sub(r"<onEnter>(.*?)</onMenuEnter>", r"<onMenuEnter>\1</onMenuEnter>", raw_xml)
    xml_without_comments = _COMMENT_RE.sub("", raw_xml)
    repaired: list[str] = []
    stack: list[str] = []
    last_index = 0
    for match in _TAG_RE.finditer(xml_without_comments):
        repaired.append(xml_without_comments[last_index:match.start()])
        repaired.append(_sanitize_tag_token(match.group(0), stack))
        last_index = match.end()
    repaired.append(xml_without_comments[last_index:])
    while stack:
        repaired.append(f"</{stack.pop()}>")
    return "".join(repaired)


def _sanitize_tag_token(token: str, stack: list[str]) -> str:
    stripped = token.strip()
    if stripped.startswith(("<?", "<!")):
        return token
    if stripped.startswith("</"):
        match = re.match(r"</\s*([^\s>/]+)\s*>", stripped)
        if match is None:
            return ""
        closing_name = match.group(1)
        if not stack:
            return ""
        if stack[-1] == closing_name:
            stack.pop()
            return f"</{closing_name}>"
        if closing_name in stack:
            repaired = []
            while stack and stack[-1] != closing_name:
                repaired.append(f"</{stack.pop()}>")
            if stack and stack[-1] == closing_name:
                stack.pop()
                repaired.append(f"</{closing_name}>")
            return "".join(repaired)
        return f"</{stack.pop()}>"

    match = re.match(r"<\s*([^\s/>]+)(.*?)(/?)\s*>", token, re.DOTALL)
    if match is None:
        return token
    tag_name = match.group(1)
    attr_text = _dedupe_tag_attributes(match.group(2))
    is_self_closing = token.rstrip().endswith("/>")
    rebuilt = f"<{tag_name}"
    if attr_text:
        rebuilt += f" {attr_text}"
    rebuilt += "/>" if is_self_closing else ">"
    if not is_self_closing:
        stack.append(tag_name)
    return rebuilt


def _dedupe_tag_attributes(attr_text: str) -> str:
    matches = list(_ATTR_RE.finditer(attr_text))
    if not matches:
        return ""
    last_match_by_key: dict[str, int] = {}
    for index, match in enumerate(matches):
        last_match_by_key[match.group(1).casefold()] = index

    parts: list[str] = []
    for index, match in enumerate(matches):
        key = match.group(1)
        if last_match_by_key.get(key.casefold()) != index:
            continue
        parts.append(f"{key}={match.group(2)}")
    return " ".join(parts)


def _directory_has_files(directory: Path) -> bool:
    try:
        return any(path.is_file() for path in directory.rglob("*"))
    except OSError:
        return False


def _read_settings_conf(target_dir: Path) -> dict[str, str]:
    settings_path = target_dir / "appdata" / "retrofe" / "settings.conf"
    try:
        text = settings_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def _themes_root(target_dir: Path | None) -> Path | None:
    if target_dir is None:
        return None
    retrofe_path = target_dir / "appdata" / "retrofe"
    settings = _read_settings_conf(target_dir)
    base_layout_raw = settings.get("baseLayoutPath")
    if base_layout_raw:
        themes_root = Path(base_layout_raw.replace("%RETROFE_PATH%", str(retrofe_path)))
    else:
        themes_root = target_dir / "base_assets" / "layouts"
    if not themes_root.exists() or not themes_root.is_dir():
        return None
    return themes_root


def _normalized_attrib(node: ET.Element) -> dict[str, str]:
    return {key.casefold(): value for key, value in node.attrib.items()}


def _local_tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _resolve_source_path(layout_path: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    # RetroFE resolves src paths relative to the theme root, not the layout file.
    # Collection layouts live at {theme_root}/collections/{name}/layout/layout.xml,
    # so walk up from the layout's directory until the path resolves to an existing file.
    search_base = layout_path.parent
    for _ in range(5):
        candidate = search_base / path
        try:
            if candidate.exists():
                return str(candidate.resolve())
        except OSError:
            pass
        parent = search_base.parent
        if parent == search_base:
            break
        search_base = parent
    try:
        return str((layout_path.parent / path).resolve())
    except OSError:
        return str(layout_path.parent / path)


def _float_value(value: str | None, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: str | None) -> int | None:
    numeric_value = _float_value(value)
    if numeric_value is None:
        return None
    return int(numeric_value)


@lru_cache(maxsize=2048)
def _intrinsic_media_dimensions(source_path: str | None) -> tuple[float, float] | None:
    if not source_path:
        return None
    path = Path(source_path)
    if not path.exists() or not path.is_file():
        return None
    suffix = path.suffix.casefold()
    try:
        if suffix == ".png":
            with path.open("rb") as handle:
                header = handle.read(24)
            if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
                width, height = struct.unpack(">II", header[16:24])
                return (float(width), float(height))
        if suffix == ".gif":
            with path.open("rb") as handle:
                header = handle.read(10)
            if len(header) >= 10 and header[:6] in {b"GIF87a", b"GIF89a"}:
                width, height = struct.unpack("<HH", header[6:10])
                return (float(width), float(height))
        if suffix == ".bmp":
            with path.open("rb") as handle:
                header = handle.read(26)
            if len(header) >= 26 and header[:2] == b"BM":
                width, height = struct.unpack("<ii", header[18:26])
                return (float(abs(width)), float(abs(height)))
        if suffix in {".jpg", ".jpeg"}:
            with path.open("rb") as handle:
                return _jpeg_dimensions(handle)
    except OSError:
        return None
    return None


def _jpeg_dimensions(handle) -> tuple[float, float] | None:
    if handle.read(2) != b"\xff\xd8":
        return None
    while True:
        marker_prefix = handle.read(1)
        if not marker_prefix:
            return None
        if marker_prefix != b"\xff":
            continue
        marker = handle.read(1)
        while marker == b"\xff":
            marker = handle.read(1)
        if not marker or marker in {b"\xd8", b"\xd9"}:
            return None
        length_bytes = handle.read(2)
        if len(length_bytes) != 2:
            return None
        segment_length = struct.unpack(">H", length_bytes)[0]
        if segment_length < 2:
            return None
        if marker in {
            b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7",
            b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf",
        }:
            segment = handle.read(segment_length - 2)
            if len(segment) < 5:
                return None
            height, width = struct.unpack(">HH", segment[1:5])
            return (float(width), float(height))
        handle.seek(segment_length - 2, 1)
