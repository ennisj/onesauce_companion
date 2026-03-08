from __future__ import annotations

from pathlib import Path

import pytest

from onesauce_updater.manifest import REQUIRED_COMPONENTS
from onesauce_updater.services.archive import inspect_archive


SAMPLE_COMPONENTS_DIR = Path("sample_components")


pytestmark = pytest.mark.skipif(
    not SAMPLE_COMPONENTS_DIR.exists(),
    reason="sample_components archives are not present in this workspace",
)


def test_embedded_versions_from_sample_archives() -> None:
    sample_files = {
        "onesauce": "OneSauce v2.0b6.zip",
        "appdata": "appdata v2.0b44.zip",
        "base_assets": "base_assets v2.0b17.zip",
        "content": "content v2.0b2.zip",
        "docs": "docs v2.0b5.zip",
    }
    expected_versions = {
        "onesauce": "v2.0b6",
        "appdata": "v2.0b44",
        "base_assets": "v2.0b17",
        "content": "v2.0b2",
        "docs": "v2.0b5",
    }

    for spec in REQUIRED_COMPONENTS:
        if spec.key not in sample_files:
            continue
        inspection = inspect_archive(SAMPLE_COMPONENTS_DIR / sample_files[spec.key], spec)
        assert inspection.embedded_version == expected_versions[spec.key]


def test_ha8800_background_has_no_embedded_version() -> None:
    spec = next(component for component in REQUIRED_COMPONENTS if component.key == "ha8800_background")
    inspection = inspect_archive(SAMPLE_COMPONENTS_DIR / spec.filename, spec)
    assert inspection.embedded_version is None
