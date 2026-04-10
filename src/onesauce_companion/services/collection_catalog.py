from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from onesauce_companion.services.collections import CollectionDefinition, scan_collection_definitions


@dataclass(frozen=True)
class CollectionCatalogEntry:
    name: str
    child_collections: tuple[str, ...]
    parent_collections: tuple[str, ...]
    game_count: int
    installed: bool


def build_collection_catalog(target_dir: Path | None) -> tuple[CollectionCatalogEntry, ...]:
    if target_dir is None:
        return tuple()

    base_root = target_dir / "base_assets" / "collections"
    content_root = target_dir / "content" / "retrofe" / "collections"
    definitions = scan_collection_definitions(target_dir)
    definition_map = {definition.name.casefold(): definition for definition in definitions}

    names: set[str] = set(_collection_dir_names(base_root))
    names.update(_collection_dir_names(content_root))

    child_map: dict[str, set[str]] = {}
    parent_map: dict[str, set[str]] = {}
    for definition in definitions:
        for source_collection in definition.source_collections:
            if _is_ignored_collection_name(source_collection):
                continue
            child_map.setdefault(source_collection, set()).add(definition.name)
            parent_map.setdefault(definition.name, set()).add(source_collection)
        for child_collection in _menu_child_collections(target_dir, definition.name):
            if _is_ignored_collection_name(child_collection):
                continue
            child_map.setdefault(definition.name, set()).add(child_collection)
            parent_map.setdefault(child_collection, set()).add(definition.name)

    count_cache: dict[str, int] = {}
    resolving: set[str] = set()

    def count_games(collection_name: str) -> int:
        key = collection_name.casefold()
        cached = count_cache.get(key)
        if cached is not None:
            return cached
        if key in resolving:
            return 0
        resolving.add(key)
        direct_count = _direct_game_count(collection_name, content_root, definition_map)
        if direct_count > 0:
            count_cache[key] = direct_count
            resolving.discard(key)
            return direct_count

        direct_count = _direct_game_count(collection_name, base_root, definition_map)
        if direct_count > 0:
            count_cache[key] = direct_count
            resolving.discard(key)
            return direct_count

        definition = definition_map.get(collection_name.casefold())
        if definition is not None and definition.subset_rules:
            item_names: set[str] = set()
            total = 0
            for rule in definition.subset_rules:
                if not rule.item_names:
                    total += count_games(rule.source_collection)
                item_names.update(rule.item_names)
            if item_names:
                result = max(total, len(item_names))
                count_cache[key] = result
                resolving.discard(key)
                return result
            if total:
                count_cache[key] = total
                resolving.discard(key)
                return total

        children = sorted(child_map.get(collection_name, set()), key=str.casefold)
        if children:
            result = sum(count_games(child_name) for child_name in children)
            count_cache[key] = result
            resolving.discard(key)
            return result
        count_cache[key] = 0
        resolving.discard(key)
        return 0

    entries = [
        CollectionCatalogEntry(
            name=name,
            child_collections=tuple(sorted((child_map.get(name, set()) & names), key=str.casefold)),
            parent_collections=tuple(sorted(parent_map.get(name, set()), key=str.casefold)),
            game_count=count_games(name),
            installed=((content_root / name).is_dir() or (base_root / name).is_dir()),
        )
        for name in sorted(names, key=str.casefold)
    ]
    return tuple(entries)


def read_collection_info_text(target_dir: Path | None, collection_name: str) -> str:
    attributes = read_collection_info_attributes(target_dir, collection_name)
    if not attributes:
        return "No collection info found."
    return "\n".join(f"{key} = {value}" for key, value in attributes)


def read_collection_info_attributes(target_dir: Path | None, collection_name: str) -> tuple[tuple[str, str], ...]:
    if target_dir is None:
        return tuple()
    info_path = target_dir / "appdata" / "retrofe" / "collections" / collection_name / "info.conf"
    if not info_path.exists():
        return tuple()
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            raw_text = info_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except OSError:
            return tuple()
    else:
        return tuple()

    attributes: list[tuple[str, str]] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or not value or key.casefold() == "title":
            continue
        attributes.append((key, value))
    return tuple(attributes)


def collection_directory_candidates(target_dir: Path | None, collection_name: str) -> tuple[Path, ...]:
    if target_dir is None:
        return tuple()
    if _is_ignored_collection_name(collection_name):
        return tuple()
    candidates: list[Path] = []
    for root in (
        target_dir / "content" / "retrofe" / "collections",
        target_dir / "base_assets" / "collections",
    ):
        candidate = root / collection_name
        if candidate.is_dir() and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _collection_dir_names(root: Path) -> tuple[str, ...]:
    if not root.exists() or not root.is_dir():
        return tuple()
    return tuple(
        collection_dir.name
        for collection_dir in sorted(root.iterdir(), key=lambda path: path.name.casefold())
        if collection_dir.is_dir() and not _is_ignored_collection_name(collection_dir.name)
    )


def _menu_child_collections(target_dir: Path, collection_name: str) -> tuple[str, ...]:
    menu_dir = target_dir / "appdata" / "retrofe" / "collections" / collection_name / "menu"
    if not menu_dir.exists() or not menu_dir.is_dir():
        return tuple()
    children: list[str] = []
    for path in sorted(menu_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        child_name = path.stem.strip()
        if not child_name or child_name in children or _is_ignored_collection_name(child_name):
            continue
        children.append(child_name)
    return tuple(children)


def _is_ignored_collection_name(name: str) -> bool:
    return name.casefold() == "_common"


def _direct_game_count(
    collection_name: str,
    collections_root: Path,
    definition_map: dict[str, CollectionDefinition],
) -> int:
    roms_root = collections_root / collection_name / "roms"
    if not roms_root.exists() or not roms_root.is_dir():
        return 0
    definition = definition_map.get(collection_name.casefold())
    valid_extensions = set(definition.valid_extensions) if definition is not None else set()
    count = 0
    for path in roms_root.iterdir():
        if not path.is_file():
            continue
        suffix = path.suffix.casefold().lstrip(".")
        if valid_extensions:
            if suffix not in valid_extensions:
                continue
        elif path.suffix.casefold() == ".txt":
            continue
        count += 1
    return count
