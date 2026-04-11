from __future__ import annotations

from dataclasses import replace
from zipfile import ZipFile

from onesauce_companion.manifest import OPTIONAL_COMPONENTS
from onesauce_companion.services.download_cache import cached_download_version, enforce_download_cache_policy, find_cached_download


def _simple_blue_spec():
    return next(spec for spec in OPTIONAL_COMPONENTS if spec.key == "optional_simple_blue")


def test_find_cached_download_returns_matching_archive(tmp_path):
    spec = _simple_blue_spec()
    archive_path = tmp_path / spec.cache_name
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b5".encode("utf-16"))

    assert find_cached_download(tmp_path, spec) == archive_path
    assert cached_download_version(tmp_path, spec) == "v2.0b5"


def test_find_cached_download_rejects_wrong_version_archive(tmp_path):
    spec = _simple_blue_spec()
    archive_path = tmp_path / spec.cache_name
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b4".encode("utf-16"))

    assert find_cached_download(tmp_path, spec) is None


def test_find_cached_download_accepts_newer_matching_archive_for_same_component(tmp_path):
    spec = replace(_simple_blue_spec(), filename="Simple Blue v2.0b4.zip", available_version="v2.0b4")
    archive_path = tmp_path / "Simple Blue v2.0b5.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b5".encode("utf-16"))

    assert find_cached_download(tmp_path, spec) == archive_path
    assert cached_download_version(tmp_path, spec) == "v2.0b5"


def test_latest_cache_policy_keeps_newer_matching_archive_for_same_component(tmp_path):
    spec = replace(_simple_blue_spec(), filename="Simple Blue v2.0b4.zip", available_version="v2.0b4")
    kept_archive = tmp_path / "Simple Blue v2.0b5.zip"
    old_archive = tmp_path / "Simple Blue v2.0b3.zip"
    with ZipFile(kept_archive, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b5".encode("utf-16"))
    with ZipFile(old_archive, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b3".encode("utf-16"))

    result = enforce_download_cache_policy(tmp_path, "latest", (spec,))

    assert result.deleted_files == 1
    assert kept_archive.exists()
    assert not old_archive.exists()
