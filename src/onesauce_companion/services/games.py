from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from onesauce_companion.services.collections import CollectionDefinition, scan_collection_definitions


@dataclass(frozen=True)
class GameManifestEntry:
    game_name: str
    collection_name: str
    rom_path: str
    source_pack: str | None = None
    install_collection_name: str | None = None
    subcollections: tuple[str, ...] = ()

    @property
    def game_pack(self) -> str:
        return self.collection_name

    @property
    def key(self) -> tuple[str, str]:
        return (self.collection_name.casefold(), self.rom_path.casefold())

    @property
    def installed_key(self) -> tuple[str, str]:
        return ((self.install_collection_name or self.collection_name).casefold(), self.rom_path.casefold())

    @property
    def exclude_keys(self) -> tuple[str, ...]:
        return _game_name_keys(self.game_name)


@lru_cache(maxsize=1)
def load_game_manifest() -> tuple[GameManifestEntry, ...]:
    manifest_path = files('onesauce_companion.data') / 'games_manifest.json.gz'
    with manifest_path.open('rb') as raw_handle:
        with gzip.open(raw_handle, 'rt', encoding='utf-8') as handle:
            payload = json.load(handle)
    entries = [
        GameManifestEntry(
            game_name=str(entry['game_name']),
            collection_name=str(entry.get('collection_name') or entry['game_pack']),
            rom_path=str(entry['rom_path']),
            source_pack=str(entry.get('source_pack') or entry.get('collection_name') or entry['game_pack']),
            install_collection_name=str(entry.get('install_collection_name') or entry.get('collection_name') or entry['game_pack']),
        )
        for entry in payload
        if _is_supported_rom_path(str(entry['rom_path']))
    ]
    return tuple(entries)


def available_collections(target_dir: Path | None = None) -> tuple[str, ...]:
    values: set[str] = set()
    for entry in build_collection_game_catalog(target_dir):
        values.add(entry.collection_name)
        values.update(entry.subcollections)
    collections = sorted(values, key=str.casefold)
    return tuple(collections)


def available_game_packs(target_dir: Path | None = None) -> tuple[str, ...]:
    return available_collections(target_dir)


def build_collection_game_catalog(
    target_dir: Path | None,
    base_entries: tuple[GameManifestEntry, ...] | None = None,
    definitions: tuple[CollectionDefinition, ...] | None = None,
) -> tuple[GameManifestEntry, ...]:
    manifest_entries = tuple(base_entries or load_game_manifest())
    collection_definitions = tuple(definitions or scan_collection_definitions(target_dir))
    if not collection_definitions:
        return manifest_entries

    definition_map = {definition.name.casefold(): definition for definition in collection_definitions}
    filtered_manifest_entries = tuple(
        entry for entry in manifest_entries if _is_allowed_for_collection(entry, definition_map)
    )

    existing_collections = {entry.collection_name.casefold() for entry in filtered_manifest_entries}
    source_entries: dict[str, list[GameManifestEntry]] = {}
    for entry in filtered_manifest_entries:
        source_entries.setdefault(entry.collection_name.casefold(), []).append(entry)

    subcollections_by_primary: dict[tuple[str, str], set[str]] = {}
    for definition in collection_definitions:
        if not definition.is_subset:
            continue
        if definition.name.casefold() in existing_collections:
            continue
        for primary_key, subcollection_name in _derived_subcollection_memberships(definition, source_entries):
            subcollections_by_primary.setdefault(primary_key, set()).add(subcollection_name)

    combined_entries = [
        replace(entry, subcollections=tuple(sorted(subcollections_by_primary.get(entry.key, set()), key=str.casefold)))
        for entry in filtered_manifest_entries
    ]
    combined_entries.sort(key=lambda entry: (entry.collection_name.casefold(), entry.game_name.casefold(), entry.rom_path.casefold()))
    return tuple(combined_entries)


def _is_allowed_for_collection(
    entry: GameManifestEntry,
    definition_map: dict[str, CollectionDefinition],
) -> bool:
    definition = definition_map.get(entry.collection_name.casefold())
    if definition is None or not definition.valid_extensions:
        return True
    return _rom_extension(entry.rom_path) in definition.valid_extensions


def _rom_extension(rom_path: str) -> str:
    return Path(rom_path).suffix.casefold().lstrip('.')


def scan_installed_games(target_dir: Path | None) -> set[tuple[str, str]]:
    if target_dir is None:
        return set()
    collections_root = target_dir / 'content' / 'retrofe' / 'collections'
    if not collections_root.exists():
        return set()

    installed: set[tuple[str, str]] = set()
    for collection_dir in collections_root.iterdir():
        roms_dir = collection_dir / 'roms'
        if not collection_dir.is_dir() or not roms_dir.exists():
            continue
        for path in roms_dir.iterdir():
            if not path.is_file():
                continue
            relative_path = path.relative_to(roms_dir).as_posix()
            if not _is_supported_rom_path(relative_path):
                continue
            installed.add((collection_dir.name.casefold(), relative_path.casefold()))
    return installed


def scan_excluded_games(target_dir: Path | None) -> set[tuple[str, str]]:
    if target_dir is None:
        return set()
    collections_root = target_dir / 'content' / 'retrofe' / 'collections'
    if not collections_root.exists():
        return set()

    excluded: set[tuple[str, str]] = set()
    for collection_dir in collections_root.iterdir():
        if not collection_dir.is_dir():
            continue
        exclude_path = collection_dir / 'exclude.txt'
        if not exclude_path.exists():
            continue
        try:
            lines = exclude_path.read_text(encoding='utf-8-sig').splitlines()
        except UnicodeDecodeError:
            lines = exclude_path.read_text(encoding='cp1252').splitlines()
        except OSError:
            continue
        for raw_line in lines:
            value = raw_line.strip()
            if not value:
                continue
            for key in _game_name_keys(value):
                excluded.add((collection_dir.name.casefold(), key))
    return excluded


def is_excluded_game(entry: GameManifestEntry, excluded_games: set[tuple[str, str]]) -> bool:
    collection_key = entry.collection_name.casefold()
    return any((collection_key, key) in excluded_games for key in entry.exclude_keys)


def _derived_subcollection_memberships(
    definition: CollectionDefinition,
    source_entries: dict[str, list[GameManifestEntry]],
) -> tuple[tuple[tuple[str, str], str], ...]:
    memberships: dict[tuple[str, str], str] = {}
    for rule in definition.subset_rules:
        source_collection_entries = source_entries.get(rule.source_collection.casefold(), [])
        if not source_collection_entries:
            continue
        if not rule.item_names:
            for source_entry in source_collection_entries:
                memberships.setdefault(source_entry.key, definition.name)
            continue
        source_index = _source_entry_index(source_collection_entries)
        for item_name in rule.item_names:
            for item_key in _game_name_keys(item_name):
                for source_entry in source_index.get(item_key, ()): 
                    memberships.setdefault(source_entry.key, definition.name)
    return tuple(memberships.items())


def _source_entry_index(entries: list[GameManifestEntry]) -> dict[str, list[GameManifestEntry]]:
    index: dict[str, list[GameManifestEntry]] = {}
    for entry in entries:
        for key in entry.exclude_keys:
            index.setdefault(key, []).append(entry)
    return index


def _game_name_keys(name: str) -> tuple[str, ...]:
    current = Path(name).name
    values: list[str] = []
    while current:
        normalized = current.casefold()
        if normalized not in values:
            values.append(normalized)
        stem = Path(current).stem
        if stem == current:
            break
        current = stem
    return tuple(values)


def _is_supported_rom_path(rom_path: str) -> bool:
    path = Path(rom_path)
    if len(path.parts) != 1:
        return False
    return path.suffix.casefold() != '.txt'
