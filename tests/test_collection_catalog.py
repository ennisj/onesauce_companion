from __future__ import annotations

from onesauce_companion.services.games import GameManifestEntry
from onesauce_companion.services.collection_catalog import (
    build_collection_catalog,
    read_collection_info_attributes,
    read_collection_info_text,
)


def test_build_collection_catalog_counts_direct_and_subset_collections(tmp_path):
    content_root = tmp_path / "content" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (content_root / "MAME" / "roms").mkdir(parents=True)
    (content_root / "MAME" / "roms" / "19xx.zip").write_text("", encoding="utf-8")
    (content_root / "MAME" / "roms" / "notes.txt").write_text("", encoding="utf-8")
    (appdata_root / "MAME").mkdir(parents=True)
    (appdata_root / "MAME" / "settings.conf").write_text("list.extensions = zip\n", encoding="utf-8")

    (base_root / "Capcom Classics").mkdir(parents=True)
    (appdata_root / "Capcom Classics").mkdir(parents=True)
    (appdata_root / "Capcom Classics" / "MAME.sub").write_text("19xx\n1944\n", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["MAME"].game_count == 1
    assert entries["MAME"].child_collections == ("Capcom Classics",)
    assert entries["Capcom Classics"].game_count == 1
    assert entries["Capcom Classics"].parent_collections == ("MAME",)


def test_build_collection_catalog_sums_child_collection_counts(tmp_path):
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"

    (base_root / "Arcade Genres").mkdir(parents=True)
    (appdata_root / "Arcade Genres" / "menu").mkdir(parents=True)
    (appdata_root / "Arcade Genres" / "menu" / "Shooters.txt").write_text("", encoding="utf-8")
    (appdata_root / "Arcade Genres" / "menu" / "Beat Em Ups.txt").write_text("", encoding="utf-8")

    (base_root / "Shooters").mkdir(parents=True)
    (appdata_root / "Shooters").mkdir(parents=True)
    (appdata_root / "Shooters" / "Arcade Genres.sub").write_text("1942\n19xx\n", encoding="utf-8")

    (base_root / "Beat Em Ups").mkdir(parents=True)
    (appdata_root / "Beat Em Ups").mkdir(parents=True)
    (appdata_root / "Beat Em Ups" / "Arcade Genres.sub").write_text("ffight\n", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["Arcade Genres"].child_collections == ("Beat Em Ups", "Shooters")
    assert entries["Arcade Genres"].game_count == 3


def test_build_collection_catalog_deduplicates_duplicate_games_across_menu_children(tmp_path):
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"

    (base_root / "Arcade Genres").mkdir(parents=True)
    (appdata_root / "Arcade Genres" / "menu").mkdir(parents=True)
    (appdata_root / "Arcade Genres" / "menu" / "Shooters.txt").write_text("", encoding="utf-8")
    (appdata_root / "Arcade Genres" / "menu" / "Verticals.txt").write_text("", encoding="utf-8")

    (base_root / "Shooters").mkdir(parents=True)
    (appdata_root / "Shooters").mkdir(parents=True)
    (appdata_root / "Shooters" / "MAME.sub").write_text("1942\n19xx\n", encoding="utf-8")

    (base_root / "Verticals").mkdir(parents=True)
    (appdata_root / "Verticals").mkdir(parents=True)
    (appdata_root / "Verticals" / "MAME.sub").write_text("19xx\nraiden\n", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["Shooters"].game_count == 2
    assert entries["Verticals"].game_count == 2
    assert entries["Arcade Genres"].game_count == 3


def test_build_collection_catalog_counts_unique_games_for_full_child_subset_collection(tmp_path):
    content_root = tmp_path / "content" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (base_root / "02 ARCADE ALL").mkdir(parents=True)
    arcade_all_dir = appdata_root / "02 ARCADE ALL"
    arcade_all_dir.mkdir(parents=True)
    (arcade_all_dir / "Daphne.sub").write_text("", encoding="utf-8")
    (arcade_all_dir / "MAME.sub").write_text("", encoding="utf-8")

    (content_root / "Daphne" / "roms").mkdir(parents=True)
    (content_root / "Daphne" / "roms" / "ace.zip").write_text("", encoding="utf-8")
    (content_root / "Daphne" / "roms" / "cliff.zip").write_text("", encoding="utf-8")
    (appdata_root / "Daphne").mkdir(parents=True)
    (appdata_root / "Daphne" / "settings.conf").write_text("list.extensions = zip\n", encoding="utf-8")

    (content_root / "MAME" / "roms").mkdir(parents=True)
    (content_root / "MAME" / "roms" / "1942.zip").write_text("", encoding="utf-8")
    (content_root / "MAME" / "roms" / "19xx.zip").write_text("", encoding="utf-8")
    (appdata_root / "MAME").mkdir(parents=True)
    (appdata_root / "MAME" / "settings.conf").write_text("list.extensions = zip\n", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["02 ARCADE ALL"].parent_collections == ("Daphne", "MAME")
    assert entries["02 ARCADE ALL"].game_count == 4


def test_build_collection_catalog_deduplicates_menu_parent_descendants(tmp_path):
    content_root = tmp_path / "content" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (base_root / "1 ARCADES").mkdir(parents=True)
    (appdata_root / "1 ARCADES" / "menu").mkdir(parents=True)
    (appdata_root / "1 ARCADES" / "menu" / "02 ARCADE ALL.txt").write_text("", encoding="utf-8")
    (appdata_root / "1 ARCADES" / "menu" / "2 ARCADE GENRES.txt").write_text("", encoding="utf-8")

    (base_root / "02 ARCADE ALL").mkdir(parents=True)
    arcade_all_dir = appdata_root / "02 ARCADE ALL"
    arcade_all_dir.mkdir(parents=True)
    (arcade_all_dir / "MAME.sub").write_text("", encoding="utf-8")

    (base_root / "2 ARCADE GENRES").mkdir(parents=True)
    (appdata_root / "2 ARCADE GENRES" / "menu").mkdir(parents=True)
    (appdata_root / "2 ARCADE GENRES" / "menu" / "1 Fighting.txt").write_text("", encoding="utf-8")

    (base_root / "1 Fighting").mkdir(parents=True)
    fighting_dir = appdata_root / "1 Fighting"
    fighting_dir.mkdir(parents=True)
    (fighting_dir / "MAME.sub").write_text("1942\n", encoding="utf-8")

    (content_root / "MAME" / "roms").mkdir(parents=True)
    (content_root / "MAME" / "roms" / "1942.zip").write_text("", encoding="utf-8")
    (content_root / "MAME" / "roms" / "19xx.zip").write_text("", encoding="utf-8")
    (appdata_root / "MAME").mkdir(parents=True)
    (appdata_root / "MAME" / "settings.conf").write_text("list.extensions = zip\n", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["02 ARCADE ALL"].game_count == 2
    assert entries["1 Fighting"].game_count == 1
    assert entries["2 ARCADE GENRES"].game_count == 1
    assert entries["1 ARCADES"].game_count == 2


def test_build_collection_catalog_prefers_game_catalog_counts_for_menu_parents(tmp_path, monkeypatch):
    content_root = tmp_path / "content" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (base_root / "1 CONSOLES").mkdir(parents=True)
    (appdata_root / "1 CONSOLES" / "menu").mkdir(parents=True)
    (appdata_root / "1 CONSOLES" / "menu" / "SNES.txt").write_text("", encoding="utf-8")
    (appdata_root / "1 CONSOLES" / "menu" / "Super Famicom.txt").write_text("", encoding="utf-8")

    (content_root / "SNES" / "roms").mkdir(parents=True)
    (content_root / "SNES" / "roms" / "mario.sfc").write_text("", encoding="utf-8")
    (content_root / "SNES" / "roms" / "zelda.sfc").write_text("", encoding="utf-8")
    (appdata_root / "SNES").mkdir(parents=True)
    (appdata_root / "SNES" / "settings.conf").write_text("list.extensions = sfc\n", encoding="utf-8")

    (base_root / "Super Famicom").mkdir(parents=True)
    (appdata_root / "Super Famicom").mkdir(parents=True)
    (appdata_root / "Super Famicom" / "SNES.sub").write_text("mario\n", encoding="utf-8")

    monkeypatch.setattr(
        "onesauce_companion.services.collection_catalog.build_collection_game_catalog",
        lambda _target_dir: (
            GameManifestEntry(
                game_name="mario.sfc",
                collection_name="SNES",
                rom_path="mario.sfc",
                subcollections=("1 CONSOLES", "Super Famicom"),
            ),
            GameManifestEntry(
                game_name="zelda.sfc",
                collection_name="SNES",
                rom_path="zelda.sfc",
                subcollections=("1 CONSOLES",),
            ),
        ),
    )

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["SNES"].game_count == 2
    assert entries["Super Famicom"].game_count == 1
    assert entries["1 CONSOLES"].game_count == 2


def test_build_collection_catalog_reads_menu_children(tmp_path):
    content_root = tmp_path / "content" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (base_root / "Main").mkdir(parents=True)
    (appdata_root / "Main" / "menu").mkdir(parents=True)
    (appdata_root / "Main" / "menu" / "MAME.txt").write_text("", encoding="utf-8")
    (appdata_root / "Main" / "menu" / "SNES.txt").write_text("", encoding="utf-8")

    (content_root / "MAME" / "roms").mkdir(parents=True)
    (content_root / "MAME" / "roms" / "19xx.zip").write_text("", encoding="utf-8")
    (appdata_root / "MAME").mkdir(parents=True)
    (appdata_root / "MAME" / "settings.conf").write_text("list.extensions = zip\n", encoding="utf-8")

    (content_root / "SNES" / "roms").mkdir(parents=True)
    (content_root / "SNES" / "roms" / "mario.sfc").write_text("", encoding="utf-8")
    (appdata_root / "SNES").mkdir(parents=True)
    (appdata_root / "SNES" / "settings.conf").write_text("list.extensions = sfc\n", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert entries["Main"].child_collections == ("MAME", "SNES")
    assert entries["Main"].game_count == 2
    assert entries["MAME"].parent_collections == ("Main",)
    assert entries["SNES"].parent_collections == ("Main",)


def test_build_collection_catalog_ignores_common_collection(tmp_path):
    content_root = tmp_path / "content" / "retrofe" / "collections"
    base_root = tmp_path / "base_assets" / "collections"
    appdata_root = tmp_path / "appdata" / "retrofe" / "collections"

    (content_root / "_common" / "roms").mkdir(parents=True)
    (content_root / "_common" / "roms" / "shared.zip").write_text("", encoding="utf-8")
    (base_root / "_common").mkdir(parents=True)
    (appdata_root / "_common").mkdir(parents=True)

    (base_root / "Main").mkdir(parents=True)
    (appdata_root / "Main" / "menu").mkdir(parents=True)
    (appdata_root / "Main" / "menu" / "_common.txt").write_text("", encoding="utf-8")

    entries = {entry.name: entry for entry in build_collection_catalog(tmp_path)}

    assert "_common" not in entries
    assert entries["Main"].child_collections == tuple()


def test_read_collection_info_text_reads_info_conf(tmp_path):
    info_path = tmp_path / "appdata" / "retrofe" / "collections" / "MAME" / "info.conf"
    info_path.parent.mkdir(parents=True)
    info_path.write_text("displayName = MAME\n", encoding="utf-8")

    assert read_collection_info_text(tmp_path, "MAME") == "displayName = MAME"


def test_read_collection_info_attributes_ignores_title(tmp_path):
    info_path = tmp_path / "appdata" / "retrofe" / "collections" / "SNES" / "info.conf"
    info_path.parent.mkdir(parents=True)
    info_path.write_text(
        "title = Super Nintendo Entertainment System\nmanufacturer = Nintendo\nyear = 1996\ngenre = console\n",
        encoding="utf-8",
    )

    assert read_collection_info_attributes(tmp_path, "SNES") == (
        ("manufacturer", "Nintendo"),
        ("year", "1996"),
        ("genre", "console"),
    )
