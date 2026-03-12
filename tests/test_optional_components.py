from __future__ import annotations

from onesauce_companion.manifest import OPTIONAL_COMPONENTS
from onesauce_companion.services.installer import Installer


def test_optional_component_detects_installed_version(tmp_path):
    version_path = tmp_path / "base_assets" / "layouts" / "Simple Blue" / "Simple Blue version.txt"
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text("Build v2.0b5", encoding="utf-16")

    installer = Installer(OPTIONAL_COMPONENTS)
    statuses = installer.scan_target(tmp_path)

    simple_blue = next(status for status in statuses if status.spec.display_name == "Simple Blue")
    assert simple_blue.installed_version == "v2.0b5"
    assert simple_blue.status == "Installed"
