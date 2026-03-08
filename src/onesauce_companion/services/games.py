from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class GameManifestEntry:
    game_name: str
    game_pack: str
    rom_path: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.game_pack.casefold(), self.rom_path.casefold())

    @property
    def exclude_keys(self) -> tuple[str, ...]:
        return _game_name_keys(self.game_name)


@lru_cache(maxsize=1)
def load_game_manifest() -> tuple[GameManifestEntry, ...]:
    manifest_path = files("onesauce_companion.data") / "games_manifest.json.gz"
    with manifest_path.open("rb") as raw_handle:
        with gzip.open(raw_handle, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    entries = [
        GameManifestEntry(
            game_name=str(entry["game_name"]),
            game_pack=str(entry["game_pack"]),
            rom_path=str(entry["rom_path"]),
        )
        for entry in payload
    ]
    return tuple(entries)


@lru_cache(maxsize=1)
def available_game_packs() -> tuple[str, ...]:
    packs = sorted({entry.game_pack for entry in load_game_manifest()}, key=str.casefold)
    return tuple(packs)


def scan_installed_games(target_dir: Path | None) -> set[tuple[str, str]]:
    if target_dir is None:
        return set()
    collections_root = target_dir / "content" / "retrofe" / "collections"
    if not collections_root.exists():
        return set()

    installed: set[tuple[str, str]] = set()
    for collection_dir in collections_root.iterdir():
        roms_dir = collection_dir / "roms"
        if not collection_dir.is_dir() or not roms_dir.exists():
            continue
        for path in roms_dir.rglob("*"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(roms_dir).as_posix()
            installed.add((collection_dir.name.casefold(), relative_path.casefold()))
    return installed


def scan_excluded_games(target_dir: Path | None) -> set[tuple[str, str]]:
    if target_dir is None:
        return set()
    collections_root = target_dir / "content" / "retrofe" / "collections"
    if not collections_root.exists():
        return set()

    excluded: set[tuple[str, str]] = set()
    for collection_dir in collections_root.iterdir():
        if not collection_dir.is_dir():
            continue
        exclude_path = collection_dir / "exclude.txt"
        if not exclude_path.exists():
            continue
        try:
            lines = exclude_path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError:
            lines = exclude_path.read_text(encoding="cp1252").splitlines()
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
    collection_key = entry.game_pack.casefold()
    return any((collection_key, key) in excluded_games for key in entry.exclude_keys)


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

