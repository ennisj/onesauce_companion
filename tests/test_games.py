from __future__ import annotations

from pathlib import Path

from onesauce_companion.services.collections import CollectionDefinition, CollectionSubsetRule
from onesauce_companion.services.games import (
    GameManifestEntry,
    available_collections,
    build_collection_game_catalog,
    is_excluded_game,
    load_game_manifest,
    scan_excluded_games,
    scan_installed_games,
)


def test_load_game_manifest_has_entries() -> None:
    manifest = load_game_manifest()
    assert manifest
    assert any(entry.collection_name == "MAME" for entry in manifest)


def test_load_game_manifest_normalizes_path_like_collection_names() -> None:
    manifest = load_game_manifest()
    daphne_entries = [entry for entry in manifest if entry.game_name == "ace.zip"]

    assert daphne_entries
    assert all(entry.collection_name == "Daphne" for entry in daphne_entries)
    assert all(entry.install_collection_name == "Daphne" for entry in daphne_entries)
    assert all(entry.source_pack == "Daphne" for entry in daphne_entries)
    assert "Daphne/assets" not in {entry.collection_name for entry in manifest}


def test_available_collections_sorted() -> None:
    collections = available_collections()
    assert collections
    assert collections == tuple(sorted(collections, key=str.casefold))


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
    entry = GameManifestEntry(game_name="example.zip", collection_name="Arcade", rom_path="example.zip")

    assert is_excluded_game(entry, excluded) is True


def test_scan_installed_games_ignores_text_files_and_subfolders(tmp_path: Path) -> None:
    roms_dir = tmp_path / "content" / "retrofe" / "collections" / "Arcade" / "roms"
    roms_dir.mkdir(parents=True, exist_ok=True)
    (roms_dir / "example.zip").write_bytes(b"demo")
    (roms_dir / "readme.txt").write_text("ignore", encoding="utf-8")
    (roms_dir / "subdir").mkdir()
    (roms_dir / "subdir" / "nested.zip").write_bytes(b"demo")

    installed = scan_installed_games(tmp_path)

    assert ("arcade", "example.zip") in installed
    assert ("arcade", "readme.txt") not in installed
    assert ("arcade", "subdir/nested.zip") not in installed


def test_build_collection_game_catalog_derives_subset_entries() -> None:
    base_entries = (
        GameManifestEntry(
            game_name="bangball.zip",
            collection_name="MAME",
            rom_path="bangball.zip",
            source_pack="Arcade",
            install_collection_name="MAME",
        ),
        GameManifestEntry(
            game_name="batlbubl.zip",
            collection_name="MAME",
            rom_path="batlbubl.zip",
            source_pack="Arcade",
            install_collection_name="MAME",
        ),
    )
    definitions = (
        CollectionDefinition(
            name="Banpresto",
            subset_rules=(CollectionSubsetRule(source_collection="MAME", item_names=("bangball",)),),
            valid_extensions=tuple(),
            has_settings=False,
            has_info=False,
            has_menu=False,
            has_menu_supported=False,
            has_menu_directory=False,
            has_launchers=False,
            has_playlists=False,
        ),
    )

    catalog = build_collection_game_catalog(None, base_entries, definitions)

    primary = next(entry for entry in catalog if entry.collection_name == "MAME" and entry.game_name == "bangball.zip")
    assert primary.installed_key == ("mame", "bangball.zip")
    assert primary.source_pack == "Arcade"
    assert primary.subcollections == ("Banpresto",)


def test_build_collection_game_catalog_preserves_existing_collection_manifest() -> None:
    base_entries = (
        GameManifestEntry(game_name="Game A.zip", collection_name="Banpresto", rom_path="Game A.zip"),
        GameManifestEntry(game_name="bangball.zip", collection_name="MAME", rom_path="bangball.zip"),
    )
    definitions = (
        CollectionDefinition(
            name="Banpresto",
            subset_rules=(CollectionSubsetRule(source_collection="MAME", item_names=("bangball",)),),
            valid_extensions=tuple(),
            has_settings=False,
            has_info=False,
            has_menu=False,
            has_menu_supported=False,
            has_menu_directory=False,
            has_launchers=False,
            has_playlists=False,
        ),
    )

    catalog = build_collection_game_catalog(None, base_entries, definitions)

    assert [entry.collection_name for entry in catalog].count("Banpresto") == 1


def test_build_collection_game_catalog_adds_full_subset_and_menu_parent_memberships(tmp_path: Path) -> None:
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (appdata_root / "02 ARCADE ALL").mkdir(parents=True)
    (appdata_root / "02 ARCADE ALL" / "MAME.sub").write_text("", encoding="utf-8")
    (appdata_root / "1 ARCADES" / "menu").mkdir(parents=True)
    (appdata_root / "1 ARCADES" / "menu" / "02 ARCADE ALL.txt").write_text("", encoding="utf-8")
    (appdata_root / "2 ARCADE SYSTEMS" / "menu").mkdir(parents=True)
    (appdata_root / "2 ARCADE SYSTEMS" / "menu" / "Daphne.txt").write_text("", encoding="utf-8")
    (appdata_root / "1 ARCADES" / "menu" / "2 ARCADE SYSTEMS.txt").write_text("", encoding="utf-8")

    base_entries = (
        GameManifestEntry(game_name="1942.zip", collection_name="MAME", rom_path="1942.zip"),
        GameManifestEntry(game_name="ace.zip", collection_name="Daphne", rom_path="ace.zip"),
    )

    catalog = build_collection_game_catalog(tmp_path, base_entries)
    entries = {(entry.collection_name, entry.game_name): entry for entry in catalog}

    assert entries[("MAME", "1942.zip")].subcollections == ("02 ARCADE ALL", "1 ARCADES")
    assert entries[("Daphne", "ace.zip")].subcollections == ("1 ARCADES", "2 ARCADE SYSTEMS")


def test_available_collections_includes_menu_parents_and_full_subset_filters(tmp_path: Path) -> None:
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (appdata_root / "02 ARCADE ALL").mkdir(parents=True)
    (appdata_root / "02 ARCADE ALL" / "MAME.sub").write_text("", encoding="utf-8")
    (appdata_root / "1 ARCADES" / "menu").mkdir(parents=True)
    (appdata_root / "1 ARCADES" / "menu" / "02 ARCADE ALL.txt").write_text("", encoding="utf-8")

    base_entries = (
        GameManifestEntry(game_name="1942.zip", collection_name="MAME", rom_path="1942.zip"),
    )

    collections = available_collections(tmp_path)
    derived_collections = {
        entry
        for entry in build_collection_game_catalog(tmp_path, base_entries)
        for entry in (entry.collection_name, *entry.subcollections)
    }

    assert "02 ARCADE ALL" in derived_collections
    assert "1 ARCADES" in derived_collections
    assert "02 ARCADE ALL" in collections
    assert "1 ARCADES" in collections
