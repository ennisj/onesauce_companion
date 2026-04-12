from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from onesauce_companion.services.collections import CollectionDefinition, scan_collection_definitions
from onesauce_companion.services.games import build_collection_game_catalog


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
    menu_child_map: dict[str, set[str]] = {}
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
            menu_child_map.setdefault(definition.name, set()).add(child_collection)
            parent_map.setdefault(child_collection, set()).add(definition.name)

    installed_game_keys: set[tuple[str, str]] = set()
    for collection_name in _collection_dir_names(content_root):
        installed_game_keys.update(_direct_game_keys(collection_name, content_root, definition_map))
    installed_game_entries = tuple(
        entry
        for entry in build_collection_game_catalog(target_dir)
        if entry.installed_key in installed_game_keys
    )
    manifest_covers_target = {entry.installed_key for entry in installed_game_entries} == installed_game_keys

    game_identity_map: dict[str, set[tuple[str, str]]] = {}
    if manifest_covers_target:
        for entry in installed_game_entries:
            for related_name in {entry.collection_name, *entry.subcollections}:
                if _is_ignored_collection_name(related_name):
                    continue
                game_identity_map.setdefault(related_name.casefold(), set()).add(entry.key)

    @lru_cache(maxsize=None)
    def count_games(collection_name: str) -> int:
        game_keys = game_identity_map.get(collection_name.casefold())
        if game_keys is not None:
            return len(game_keys)

        direct_count = _direct_game_count(collection_name, content_root, definition_map)
        if direct_count > 0:
            return direct_count

        direct_count = _direct_game_count(collection_name, base_root, definition_map)
        if direct_count > 0:
            return direct_count

        definition = definition_map.get(collection_name.casefold())
        if definition is not None and definition.subset_rules:
            if any(rule.include_all_items for rule in definition.subset_rules):
                return len(_full_subset_game_keys(collection_name))
            item_names: set[str] = set()
            for rule in definition.subset_rules:
                item_names.update(rule.item_names)
            if item_names:
                return len(item_names)

        children = sorted(menu_child_map.get(collection_name, set()), key=str.casefold)
        if children:
            covered_sources = set().union(*(coverage_sources(child_name) for child_name in children))
            aggregate_counts = [
                count_games(child_name)
                for child_name in children
                if is_covering_full_aggregate(child_name, covered_sources)
            ]
            if aggregate_counts:
                return max(aggregate_counts)
            return len(_menu_child_game_keys(collection_name))
        return 0

    @lru_cache(maxsize=None)
    def coverage_sources(collection_name: str) -> frozenset[str]:
        definition = definition_map.get(collection_name.casefold())
        if definition is not None and definition.subset_rules:
            return frozenset(rule.source_collection for rule in definition.subset_rules)
        if _direct_game_count(collection_name, content_root, definition_map) > 0:
            return frozenset((collection_name,))
        if _direct_game_count(collection_name, base_root, definition_map) > 0:
            return frozenset((collection_name,))
        covered_sources: set[str] = set()
        for child_name in menu_child_map.get(collection_name, set()):
            covered_sources.update(coverage_sources(child_name))
        return frozenset(covered_sources)

    def is_covering_full_aggregate(collection_name: str, required_sources: set[str]) -> bool:
        definition = definition_map.get(collection_name.casefold())
        if definition is None or not definition.subset_rules:
            return False
        if not any(rule.include_all_items for rule in definition.subset_rules):
            return False
        aggregate_sources = {rule.source_collection for rule in definition.subset_rules}
        return bool(required_sources) and aggregate_sources.issuperset(required_sources)

    @lru_cache(maxsize=None)
    def _full_subset_game_keys(collection_name: str) -> frozenset[tuple[str, str]]:
        definition = definition_map.get(collection_name.casefold())
        if definition is None:
            return frozenset()
        keys: set[tuple[str, str]] = set()
        for rule in definition.subset_rules:
            if not rule.include_all_items:
                continue
            keys.update(_direct_game_keys(rule.source_collection, content_root, definition_map))
            keys.update(_direct_game_keys(rule.source_collection, base_root, definition_map))
        return frozenset(keys)

    @lru_cache(maxsize=None)
    def _collection_game_identity_keys(collection_name: str) -> frozenset[tuple[str, str]]:
        direct_keys = _direct_game_keys(collection_name, content_root, definition_map)
        if direct_keys:
            return direct_keys

        direct_keys = _direct_game_keys(collection_name, base_root, definition_map)
        if direct_keys:
            return direct_keys

        definition = definition_map.get(collection_name.casefold())
        if definition is not None and definition.subset_rules:
            if any(rule.include_all_items for rule in definition.subset_rules):
                return _full_subset_game_keys(collection_name)
            item_keys = {
                (rule.source_collection.casefold(), _canonical_game_item_key(item_name))
                for rule in definition.subset_rules
                for item_name in rule.item_names
            }
            if item_keys:
                return frozenset(item_keys)

        if menu_child_map.get(collection_name, set()):
            return _menu_child_game_keys(collection_name)
        return frozenset()

    @lru_cache(maxsize=None)
    def _menu_child_game_keys(collection_name: str) -> frozenset[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for child_name in menu_child_map.get(collection_name, set()):
            keys.update(_collection_game_identity_keys(child_name))
        return frozenset(keys)

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


def _direct_game_keys(
    collection_name: str,
    collections_root: Path,
    definition_map: dict[str, CollectionDefinition],
) -> frozenset[tuple[str, str]]:
    roms_root = collections_root / collection_name / "roms"
    if not roms_root.exists() or not roms_root.is_dir():
        return frozenset()
    definition = definition_map.get(collection_name.casefold())
    valid_extensions = set(definition.valid_extensions) if definition is not None else set()
    keys: set[tuple[str, str]] = set()
    for path in roms_root.iterdir():
        if not path.is_file():
            continue
        suffix = path.suffix.casefold().lstrip(".")
        if valid_extensions:
            if suffix not in valid_extensions:
                continue
        elif path.suffix.casefold() == ".txt":
            continue
        keys.add((collection_name.casefold(), path.name.casefold()))
    return frozenset(keys)


def _direct_game_count(
    collection_name: str,
    collections_root: Path,
    definition_map: dict[str, CollectionDefinition],
) -> int:
    return len(_direct_game_keys(collection_name, collections_root, definition_map))


def _canonical_game_item_key(name: str) -> str:
    current = Path(name).name
    while current:
        stem = Path(current).stem
        if stem == current:
            return current.casefold()
        current = stem
    return name.casefold()
