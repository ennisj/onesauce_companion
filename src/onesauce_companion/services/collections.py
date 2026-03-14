from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from onesauce_companion.services.versioning import normalize_name_key


@dataclass(frozen=True)
class CollectionSubsetRule:
    source_collection: str
    item_names: tuple[str, ...]


@dataclass(frozen=True)
class CollectionDefinition:
    name: str
    subset_rules: tuple[CollectionSubsetRule, ...]
    valid_extensions: tuple[str, ...]
    has_settings: bool
    has_info: bool
    has_menu: bool
    has_menu_supported: bool
    has_menu_directory: bool
    has_launchers: bool
    has_playlists: bool

    @property
    def is_subset(self) -> bool:
        return bool(self.subset_rules)

    @property
    def is_menu_collection(self) -> bool:
        return self.has_menu or self.has_menu_supported or self.has_menu_directory

    @property
    def source_collections(self) -> tuple[str, ...]:
        seen: list[str] = []
        for rule in self.subset_rules:
            if rule.source_collection not in seen:
                seen.append(rule.source_collection)
        return tuple(seen)


def scan_collection_definitions(target_dir: Path | None) -> tuple[CollectionDefinition, ...]:
    collections_root = _collections_root(target_dir)
    if collections_root is None:
        return tuple()
    return _scan_collection_definitions_cached(collections_root)


@lru_cache(maxsize=8)
def _scan_collection_definitions_cached(collections_root: Path) -> tuple[CollectionDefinition, ...]:
    definitions: list[CollectionDefinition] = []
    for collection_dir in sorted(collections_root.iterdir(), key=lambda path: path.name.casefold()):
        if not collection_dir.is_dir():
            continue
        subset_rules: list[CollectionSubsetRule] = []
        for subset_path in sorted(collection_dir.glob('*.sub'), key=lambda path: path.name.casefold()):
            item_names = _read_subset_items(subset_path)
            if not item_names:
                continue
            subset_rules.append(
                CollectionSubsetRule(
                    source_collection=subset_path.stem,
                    item_names=item_names,
                )
            )
        settings_path = collection_dir / 'settings.conf'
        definitions.append(
            CollectionDefinition(
                name=collection_dir.name,
                subset_rules=tuple(subset_rules),
                valid_extensions=_read_valid_extensions(settings_path),
                has_settings=settings_path.exists(),
                has_info=(collection_dir / 'info.conf').exists(),
                has_menu=(collection_dir / 'menu.txt').exists(),
                has_menu_supported=(collection_dir / 'menu_supported.txt').exists(),
                has_menu_directory=(collection_dir / 'menu').is_dir(),
                has_launchers=(collection_dir / 'launchers').is_dir(),
                has_playlists=(collection_dir / 'playlists').is_dir(),
            )
        )
    return tuple(definitions)


def matching_collection_names(target_dir: Path | None, expected_name: str) -> tuple[str, ...]:
    definitions = scan_collection_definitions(target_dir)
    expected_key = normalize_name_key(expected_name)
    matches: list[str] = []
    for definition in definitions:
        if normalize_name_key(definition.name) != expected_key:
            continue
        matches.append(definition.name)
    return tuple(matches)


def _read_valid_extensions(settings_path: Path) -> tuple[str, ...]:
    if not settings_path.exists():
        return tuple()
    try:
        raw_text = settings_path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        raw_text = settings_path.read_text(encoding='cp1252')
    except OSError:
        return tuple()

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if not line.lower().startswith('list.extensions') or '=' not in line:
            continue
        _, raw_value = line.split('=', 1)
        extensions: list[str] = []
        for part in raw_value.split(','):
            value = part.strip().casefold().lstrip('.')
            if value and value not in extensions:
                extensions.append(value)
        return tuple(extensions)
    return tuple()


def _collections_root(target_dir: Path | None) -> Path | None:
    if target_dir is None:
        return None
    collections_root = target_dir / 'appdata' / 'retrofe' / 'collections'
    if not collections_root.exists():
        return None
    return collections_root


def _read_subset_items(subset_path: Path) -> tuple[str, ...]:
    try:
        raw_text = subset_path.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        raw_text = subset_path.read_text(encoding='cp1252')
    except OSError:
        return tuple()

    items: list[str] = []
    for raw_line in raw_text.splitlines():
        value = raw_line.strip()
        if not value or value.startswith('#') or value.startswith(';'):
            continue
        if value not in items:
            items.append(value)
    return tuple(items)
