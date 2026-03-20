from __future__ import annotations

from onesauce_companion.services import component_catalogs


def test_build_required_component_specs_uses_latest_archive_version(monkeypatch) -> None:
    def fake_archive_files(archive_item: str):
        assert archive_item == "OnesaUCEv2BaseBuild"
        return [
            {"name": "appdata v2.0b46.zip", "size": "612065911"},
            {"name": "appdata v2.0b47.zip", "size": "700"},
            {"name": "base_assets v2.0b18.zip", "size": "4854699601"},
            {"name": "OneSauce v2.0b6.zip", "size": "625001"},
            {"name": "content v2.0b2.zip", "size": "31679"},
            {"name": "docs v2.0b5.zip", "size": "1817779"},
            {"name": "ha8800_background v2.0b2.zip", "size": "605600"},
        ]

    monkeypatch.setattr(component_catalogs, "_archive_files", fake_archive_files)

    specs = component_catalogs.build_required_component_specs()
    appdata = next(spec for spec in specs if spec.key == "appdata")

    assert appdata.filename == "appdata v2.0b47.zip"
    assert appdata.available_version == "v2.0b47"
    assert appdata.size_bytes == 700


def test_build_optional_component_specs_discovers_new_video_range(monkeypatch) -> None:
    def fake_archive_files(archive_item: str):
        if archive_item == "simple-blue_202404":
            return [{"name": "Simple Blue v2.0b5.zip", "size": "10"}]
        if archive_item == "OnesaUCEv2BaseBuild":
            return [
                {"name": "ha8800_screensaver Attract v2.0b6.zip", "size": "20"},
                {"name": "ha8800_screensaver Mi-O v2.0b5.zip", "size": "30"},
            ]
        raise AssertionError(archive_item)

    monkeypatch.setattr(component_catalogs, "_archive_files", fake_archive_files)

    specs = component_catalogs.build_optional_component_specs()

    assert any(spec.display_name == "Attract Mode Videos" for spec in specs)
    mi_o = next(spec for spec in specs if spec.display_name == "Jukebox Videos Mi-O")
    assert mi_o.available_version == "v2.0b5"
    assert mi_o.install_root == "ha8800_screensaver Mi-O"


def test_build_bitlcd_component_specs_uses_latest_version(monkeypatch) -> None:
    def fake_archive_files(archive_item: str):
        assert archive_item == "onesauce-v2-lcd-marquee-packs"
        return [
            {"name": "ScummVM Sys Specv2.0b3.zip", "size": "100"},
            {"name": "ScummVM Sys Specv2.0b4.zip", "size": "200"},
        ]

    monkeypatch.setattr(component_catalogs, "_archive_files", fake_archive_files)

    specs = component_catalogs.build_bitlcd_component_specs()
    scummvm = next(spec for spec in specs if spec.display_name == "ScummVM")

    assert scummvm.available_version == "v2.0b4"
    assert scummvm.size_bytes == 200
