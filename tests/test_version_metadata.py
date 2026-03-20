from __future__ import annotations

from pathlib import Path

from onesauce_companion import __version__


def test_package_version_matches_version_file() -> None:
    version_file = Path(__file__).resolve().parents[1] / "src" / "onesauce_companion" / "VERSION"
    assert __version__ == version_file.read_text(encoding="utf-8").strip()
