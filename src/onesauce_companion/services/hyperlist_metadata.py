from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from onesauce_companion.services.games import GameManifestEntry


@dataclass(frozen=True)
class HyperListGameMetadata:
    name: str
    description: str | None
    manufacturer: str | None
    year: str | None
    genre: str | None
    rating: str | None
    cloneof: str | None
    crc: str | None
    enabled: str | None

    def value_for_slot(self, slot_name: str) -> str | None:
        slot_key = slot_name.casefold()
        if slot_key == "title":
            return self.description or self.name
        return {
            "description": self.description,
            "manufacturer": self.manufacturer,
            "year": self.year,
            "genre": self.genre,
            "rating": self.rating,
            "cloneof": self.cloneof,
            "crc": self.crc,
            "enabled": self.enabled,
        }.get(slot_key)


def lookup_hyperlist_metadata(
    target_dir: Path | None,
    collection_names: tuple[str, ...],
    game_entry: GameManifestEntry | None,
) -> HyperListGameMetadata | None:
    if target_dir is None or game_entry is None:
        return None
    for collection_name in collection_names:
        metadata_path = _find_hyperlist_metadata_path(target_dir, collection_name)
        if metadata_path is None:
            continue
        entries = _load_hyperlist_entries(str(metadata_path))
        for key in _lookup_keys_for_entry(game_entry):
            metadata = entries.get(key)
            if metadata is not None:
                return metadata
    return None


def _find_hyperlist_metadata_path(target_dir: Path, collection_name: str) -> Path | None:
    normalized_collection = collection_name.strip()
    if not normalized_collection:
        return None
    metadata_root = target_dir / "appdata" / "retrofe" / "meta" / "hyperlist"
    if not metadata_root.exists() or not metadata_root.is_dir():
        return None
    direct_path = metadata_root / f"{normalized_collection}.xml"
    if direct_path.exists():
        return direct_path
    target_key = normalized_collection.casefold()
    for candidate in metadata_root.glob("*.xml"):
        if candidate.stem.casefold() == target_key:
            return candidate
    return None


@lru_cache(maxsize=256)
def _load_hyperlist_entries(metadata_path: str) -> dict[str, HyperListGameMetadata]:
    path = Path(metadata_path)
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}

    entries: dict[str, HyperListGameMetadata] = {}
    for game_node in root.findall("game"):
        name = (game_node.get("name") or "").strip()
        if not name:
            continue
        metadata = HyperListGameMetadata(
            name=name,
            description=_child_text(game_node, "description"),
            manufacturer=_child_text(game_node, "manufacturer"),
            year=_child_text(game_node, "year"),
            genre=_child_text(game_node, "genre"),
            rating=_child_text(game_node, "rating"),
            cloneof=_child_text(game_node, "cloneof"),
            crc=_child_text(game_node, "crc"),
            enabled=_child_text(game_node, "enabled"),
        )
        for key in _lookup_keys_for_names((name, metadata.description or "")):
            entries.setdefault(key, metadata)
    return entries


def _lookup_keys_for_entry(game_entry: GameManifestEntry) -> tuple[str, ...]:
    return _lookup_keys_for_names(
        (
            game_entry.game_name,
            Path(game_entry.game_name).name,
            Path(game_entry.game_name).stem,
            game_entry.rom_path,
            Path(game_entry.rom_path).name,
            Path(game_entry.rom_path).stem,
        )
    )


def _lookup_keys_for_names(names: tuple[str, ...]) -> tuple[str, ...]:
    keys: list[str] = []
    for name in names:
        variants = [name.strip(), Path(name).name.strip(), Path(name).stem.strip()]
        expanded_variants: list[str] = []
        for variant in variants:
            for candidate in _name_variants(variant):
                if candidate not in expanded_variants:
                    expanded_variants.append(candidate)
        for variant in expanded_variants:
            _append_lookup_key(keys, variant)
            simplified_variant = _SIMPLIFIED_NAME_RE.sub("", variant).strip()
            if simplified_variant and simplified_variant != variant:
                _append_lookup_key(keys, simplified_variant)

        current = Path(name).stem.strip()
        while current:
            simplified = _SIMPLIFIED_NAME_RE.sub("", current).strip()
            _append_lookup_key(keys, current)
            if simplified:
                _append_lookup_key(keys, simplified)
            stem = Path(current).stem
            if stem == current:
                break
            current = stem
    return tuple(keys)


def _append_lookup_key(keys: list[str], value: str) -> None:
    normalized = _normalize_lookup_name(value)
    if normalized and normalized not in keys:
        keys.append(normalized)


def _name_variants(value: str) -> tuple[str, ...]:
    text = value.strip()
    if not text:
        return tuple()
    variants = [text]
    article_swapped = _swap_article_position(text)
    if article_swapped and article_swapped not in variants:
        variants.append(article_swapped)
    article_removed = _remove_leading_article(text)
    if article_removed and article_removed not in variants:
        variants.append(article_removed)
    swapped_removed = _remove_leading_article(article_swapped) if article_swapped else None
    if swapped_removed and swapped_removed not in variants:
        variants.append(swapped_removed)
    return tuple(variants)


def _swap_article_position(value: str) -> str | None:
    match = _TRAILING_ARTICLE_RE.match(value)
    if match:
        article = match.group("article")
        title = match.group("title").strip()
        suffix = match.group("suffix") or ""
        if title:
            return f"{article} {title}{suffix}".strip()
    match = _LEADING_ARTICLE_RE.match(value)
    if match:
        article = match.group("article")
        title = match.group("title").strip()
        suffix = match.group("suffix") or ""
        if title:
            return f"{title}, {article}{suffix}".strip()
    return None


def _remove_leading_article(value: str | None) -> str | None:
    if not value:
        return None
    match = _LEADING_ARTICLE_RE.match(value)
    if match:
        title = match.group("title").strip()
        suffix = match.group("suffix") or ""
        return f"{title}{suffix}".strip()
    return value.strip()


def _normalize_lookup_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _child_text(node: ET.Element, tag_name: str) -> str | None:
    child = node.find(tag_name)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


_SIMPLIFIED_NAME_RE = re.compile(r"\s*\([^)]*\)")
_LEADING_ARTICLE_RE = re.compile(r"^(?P<article>The|A|An)\s+(?P<title>.*?)(?P<suffix>\s*\([^)]*\))?$", re.IGNORECASE)
_TRAILING_ARTICLE_RE = re.compile(r"^(?P<title>.*?),\s*(?P<article>The|A|An)(?P<suffix>\s*\([^)]*\))?$", re.IGNORECASE)
