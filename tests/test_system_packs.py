from __future__ import annotations

from onesauce_companion.manifest import build_system_pack_spec
from onesauce_companion.services.installer import Installer
from onesauce_companion.services.state import InstallState
from onesauce_companion.services.system_packs import build_system_pack_specs_from_archive_files


def test_build_system_pack_specs_uses_latest_archive_version_and_exact_mapping() -> None:
    specs = build_system_pack_specs_from_archive_files(
        [
            {"name": "Arcade v2.0b4.zip", "size": "100"},
            {"name": "Arcade v2.0b5.zip", "size": "200"},
            {"name": "SNES v2.0b2.zip", "size": "300"},
        ]
    )

    arcade = next(spec for spec in specs if spec.display_name == "Arcade")
    snes = next(spec for spec in specs if spec.display_name == "SNES")

    assert arcade.available_version == "v2.0b5"
    assert arcade.install_root == "MAME"
    assert arcade.filename == "Arcade v2.0b5.zip"
    assert arcade.size_bytes == 200
    assert snes.install_root == "Super Nintendo Entertainment System"


def test_build_system_pack_specs_keeps_unknown_pack_downloadable() -> None:
    specs = build_system_pack_specs_from_archive_files(
        [
            {"name": "NewFuturePack v2.0b1.zip", "size": "1234"},
        ]
    )

    assert len(specs) == 1
    assert specs[0].display_name == "NewFuturePack"
    assert specs[0].install_root == "NewFuturePack"
    assert specs[0].available_version == "v2.0b1"


def test_installer_uses_learned_collection_root_from_state(tmp_path) -> None:
    spec = build_system_pack_spec("NewFuturePack", "v2.0b1", 1234)
    state = InstallState(collection_roots={spec.key: "Future Collection"})
    state.save(tmp_path)

    version_file = tmp_path / "content" / "retrofe" / "collections" / "Future Collection" / "Future version.txt"
    version_file.parent.mkdir(parents=True)
    version_file.write_bytes("Build v2.0b1".encode("utf-16"))

    statuses = Installer((spec,)).scan_target(tmp_path)

    assert len(statuses) == 1
    assert statuses[0].status == "Installed"
    assert statuses[0].installed_version == "v2.0b1"


def test_installer_assumes_legacy_daphne_version_when_content_exists_without_version_file(tmp_path) -> None:
    spec = build_system_pack_spec("Daphne", "v2.0b3", 1234)
    collection_root = tmp_path / "content" / "retrofe" / "collections" / "Daphne"
    collection_root.mkdir(parents=True)
    (collection_root / "games.daphne").write_text("legacy content", encoding="utf-8")

    statuses = Installer((spec,)).scan_target(tmp_path)

    assert len(statuses) == 1
    assert statuses[0].installed_version == "v2.0b2"
    assert statuses[0].status == "Update Available"
