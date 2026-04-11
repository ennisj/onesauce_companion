from __future__ import annotations

from zipfile import ZipFile

from onesauce_companion.manifest import REQUIRED_COMPONENTS
from onesauce_companion.services.control import OperationController
from onesauce_companion.services.installer import Installer


def test_download_component_uses_cached_archive_without_network(tmp_path):
    spec = next(component for component in REQUIRED_COMPONENTS if component.key == "appdata")
    archive_path = tmp_path / spec.cache_name
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b46".encode("utf-16"))

    installer = Installer((spec,), cache_dir=tmp_path)

    class FailDownloader:
        authenticated_user = None

        def authenticate_with_archive_org(self, credentials):
            raise AssertionError("cache hit should not authenticate")

        def clone(self):
            raise AssertionError("cache hit should not clone downloader")

        def download(self, *args, **kwargs):
            raise AssertionError("cache hit should not download")

    installer.downloader = FailDownloader()

    result = installer._download_component(
        spec,
        credentials=None,
        controller=OperationController(),
        log_callback=None,
        status_callback=None,
        emit_progress=lambda *args: None,
    )

    assert result == archive_path
