from __future__ import annotations

from onesauce_updater.models import ComponentSpec


ARCHIVE_ITEM = "OnesaUCEv2BaseBuild"

REQUIRED_COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        key="onesauce",
        display_name="OnesaUCE",
        archive_item=ARCHIVE_ITEM,
        filename="OneSauce v2.0b6.zip",
        download_url="https://archive.org/download/OnesaUCEv2BaseBuild/OneSauce%20v2.0b6.zip",
        install_root="OneSauce",
        version_file_relpath="OneSauce/OneSauce version.txt",
        available_version="v2.0b6",
    ),
    ComponentSpec(
        key="appdata",
        display_name="appdata",
        archive_item=ARCHIVE_ITEM,
        filename="appdata v2.0b46.zip",
        download_url="https://archive.org/download/OnesaUCEv2BaseBuild/appdata%20v2.0b46.zip",
        install_root="appdata",
        version_file_relpath="appdata/appdata version.txt",
        available_version="v2.0b46",
    ),
    ComponentSpec(
        key="base_assets",
        display_name="base_assets",
        archive_item=ARCHIVE_ITEM,
        filename="base_assets v2.0b18.zip",
        download_url="https://archive.org/download/OnesaUCEv2BaseBuild/base_assets%20v2.0b18.zip",
        install_root="base_assets",
        version_file_relpath="base_assets/base_assets version.txt",
        available_version="v2.0b18",
    ),
    ComponentSpec(
        key="content",
        display_name="content",
        archive_item=ARCHIVE_ITEM,
        filename="content v2.0b2.zip",
        download_url="https://archive.org/download/OnesaUCEv2BaseBuild/content%20v2.0b2.zip",
        install_root="content",
        version_file_relpath="content/content version.txt",
        available_version="v2.0b2",
    ),
    ComponentSpec(
        key="docs",
        display_name="docs",
        archive_item=ARCHIVE_ITEM,
        filename="docs v2.0b5.zip",
        download_url="https://archive.org/download/OnesaUCEv2BaseBuild/docs%20v2.0b5.zip",
        install_root="docs",
        version_file_relpath="docs/docs version.txt",
        available_version="v2.0b5",
    ),
    ComponentSpec(
        key="ha8800_background",
        display_name="ha8800_background",
        archive_item=ARCHIVE_ITEM,
        filename="ha8800_background v2.0b2.zip",
        download_url="https://archive.org/download/OnesaUCEv2BaseBuild/ha8800_background%20v2.0b2.zip",
        install_root="ha8800_background",
        version_file_relpath=None,
        available_version="v2.0b2",
    ),
)
