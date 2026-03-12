from __future__ import annotations

from pathlib import Path

from onesauce_companion.services.games import GameManifestEntry
from onesauce_companion.ui.main_window import _find_matching_bitlcd_media_file, _find_matching_lcd_marquee_file, _find_matching_media_file, _game_name_candidates, _read_story_text
from onesauce_companion.ui.main_window import _resolve_game_media_root


def test_game_name_candidates_strip_nested_suffixes() -> None:
    assert _game_name_candidates("Metal Slug.zip") == ("Metal Slug.zip", "Metal Slug")
    assert _game_name_candidates("Example.nes.zip") == ("Example.nes.zip", "Example.nes", "Example")


def test_find_matching_media_file_matches_nested_stem(tmp_path: Path) -> None:
    media_dir = tmp_path / "video"
    media_dir.mkdir()
    match = media_dir / "Example.nes.mp4"
    match.write_bytes(b"demo")

    found = _find_matching_media_file(media_dir, ("Example.nes.zip", "Example.nes", "Example"))
    assert found == match


def test_read_story_text_reads_cp1252_story(tmp_path: Path) -> None:
    story_path = tmp_path / "story.txt"
    story_path.write_bytes("Café story".encode("cp1252"))

    assert _read_story_text(story_path) == "Café story"


def test_resolve_game_media_root_falls_back_to_matching_collection(tmp_path: Path) -> None:
    media_dir = tmp_path / "base_assets" / "collections" / "SNK Neo Geo AES" / "medium_artwork"
    (media_dir / "artwork_front").mkdir(parents=True)
    (media_dir / "logo").mkdir(parents=True)
    (media_dir / "story").mkdir(parents=True)
    (media_dir / "artwork_front" / "2020bb.png").write_bytes(b"png")
    (media_dir / "logo" / "2020bb.png").write_bytes(b"png")
    (media_dir / "story" / "2020bb.txt").write_text("Demo story", encoding="utf-8")

    entry = GameManifestEntry(game_name="2020bb.zip", collection_name="MAME", rom_path="2020bb.zip")
    root = _resolve_game_media_root(tmp_path, entry, _game_name_candidates(entry.rom_path))

    assert root == media_dir


def test_resolve_game_media_root_prefers_content_collections_layout(tmp_path: Path) -> None:
    media_dir = tmp_path / "content" / "retrofe" / "collections" / "Commodore 64" / "medium_artwork"
    rom_dir = tmp_path / "content" / "retrofe" / "collections" / "Commodore 64" / "roms"
    for folder in ("artwork_front", "logo", "story", "video"):
        (media_dir / folder).mkdir(parents=True, exist_ok=True)
    rom_dir.mkdir(parents=True, exist_ok=True)

    rom_name = "$100,000 Pyramid, The (USA).d64"
    stem = "$100,000 Pyramid, The (USA)"
    (rom_dir / rom_name).write_bytes(b"demo")
    (media_dir / "artwork_front" / f"{stem}.png").write_bytes(b"png")
    (media_dir / "logo" / f"{stem}.png").write_bytes(b"png")
    (media_dir / "story" / f"{stem}.txt").write_text("Story", encoding="utf-8")
    (media_dir / "video" / f"{stem}.mp4").write_bytes(b"mp4")

    entry = GameManifestEntry(game_name=rom_name, collection_name="Commodore 64", rom_path=rom_name)
    root = _resolve_game_media_root(tmp_path, entry, _game_name_candidates(entry.rom_path))

    assert root == media_dir


def test_find_matching_media_file_matches_same_name_subfolder(tmp_path: Path) -> None:
    media_dir = tmp_path / "marquee"
    nested_dir = media_dir / "jackal"
    nested_dir.mkdir(parents=True)
    first = nested_dir / "jackal.png"
    second = nested_dir / "jackal(1).png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")

    found = _find_matching_media_file(media_dir, ("jackal.zip", "jackal"))
    assert found == first


def test_find_matching_lcd_marquee_file_falls_back_to_bitlcd(tmp_path: Path) -> None:
    media_root = tmp_path / "content" / "retrofe" / "collections" / "MAME" / "medium_artwork"
    (media_root / "lcd_marquee").mkdir(parents=True)
    bitlcd_root = tmp_path / "bitlcd"
    bitlcd_pack = bitlcd_root / "MAME_2023 10 11 Sys Spec_v2.0b2"
    bitlcd_pack.mkdir(parents=True)
    bitlcd_file = bitlcd_pack / "jackal (MAME).jpg"
    bitlcd_file.write_bytes(b"jpg")

    entry = GameManifestEntry(game_name="jackal.zip", collection_name="MAME", rom_path="jackal.zip")
    found = _find_matching_lcd_marquee_file(media_root, bitlcd_root, entry, ("jackal.zip", "jackal"))
    assert found == bitlcd_file
