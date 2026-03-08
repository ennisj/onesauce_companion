from __future__ import annotations

from pathlib import Path

from onesauce_companion.services.games import (
    GameManifestEntry,
    available_game_packs,
    is_excluded_game,
    load_game_manifest,
    scan_excluded_games,
    scan_installed_games,
)


def test_load_game_manifest_has_entries() -> None:
    manifest = load_game_manifest()
    assert manifest
    assert any(entry.game_pack == "MAME" for entry in manifest)


def test_available_game_packs_sorted() -> None:
    packs = available_game_packs()
    assert packs
    assert packs == tuple(sorted(packs, key=str.casefold))


def test_scan_installed_games_detects_roms(tmp_path: Path) -> None:
    rom_path = tmp_path / "content" / "retrofe" / "collections" / "Arcade" / "roms" / "example.zip"
    rom_path.parent.mkdir(parents=True, exist_ok=True)
    rom_path.write_bytes(b"demo")

    installed = scan_installed_games(tmp_path)
    assert ("arcade", "example.zip") in installed


def test_scan_excluded_games_reads_extensionless_names(tmp_path: Path) -> None:
    exclude_path = tmp_path / "content" / "retrofe" / "collections" / "Arcade" / "exclude.txt"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    exclude_path.write_text("example\nAnother Game\n", encoding="utf-8")

    excluded = scan_excluded_games(tmp_path)

    assert ("arcade", "example") in excluded
    assert ("arcade", "another game") in excluded


def test_is_excluded_game_matches_manifest_game_with_extension(tmp_path: Path) -> None:
    exclude_path = tmp_path / "content" / "retrofe" / "collections" / "Arcade" / "exclude.txt"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    exclude_path.write_text("example\n", encoding="utf-8")

    excluded = scan_excluded_games(tmp_path)
    entry = GameManifestEntry(game_name="example.zip", game_pack="Arcade", rom_path="example.zip")

    assert is_excluded_game(entry, excluded) is True

