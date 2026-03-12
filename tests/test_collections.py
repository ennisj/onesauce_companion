from __future__ import annotations

from pathlib import Path

from onesauce_companion.services.collections import scan_collection_definitions


def test_scan_collection_definitions_reads_subset_rules(tmp_path: Path) -> None:
    collections_root = tmp_path / "appdata" / "retrofe" / "collections"
    collection_dir = collections_root / "Banpresto"
    collection_dir.mkdir(parents=True)
    (collection_dir / "settings.conf").write_text("demo", encoding="utf-8")
    (collection_dir / "MAME.sub").write_text("bangball\n;comment\n\n batlbubl \n", encoding="utf-8")

    definitions = scan_collection_definitions(tmp_path)

    definition = next(item for item in definitions if item.name == "Banpresto")
    assert definition.has_settings is True
    assert definition.is_subset is True
    assert definition.source_collections == ("MAME",)
    assert definition.subset_rules[0].item_names == ("bangball", "batlbubl")
