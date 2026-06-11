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


def test_archive_inspection_is_cached_across_lookups(tmp_path, monkeypatch):
    from onesauce_companion.services import download_cache

    spec = _simple_blue_spec()
    archive_path = tmp_path / spec.cache_name
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b5".encode("utf-16"))

    inspect_calls = []
    real_inspect = download_cache.inspect_archive

    def counting_inspect(path, inspected_spec):
        inspect_calls.append(path)
        return real_inspect(path, inspected_spec)

    monkeypatch.setattr(download_cache, "inspect_archive", counting_inspect)

    assert cached_download_version(tmp_path, spec) == "v2.0b5"
    assert cached_download_version(tmp_path, spec) == "v2.0b5"
    assert find_cached_download(tmp_path, spec) == archive_path

    assert len(inspect_calls) == 1


def test_archive_inspection_cache_invalidates_on_file_change(tmp_path):
    import os

    spec = _simple_blue_spec()
    archive_path = tmp_path / spec.cache_name
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b5".encode("utf-16"))
    assert cached_download_version(tmp_path, spec) == "v2.0b5"

    # Rewrite in place, then force a distinct mtime: same-size rewrites can land
    # within the filesystem timestamp granularity and reuse the inode.
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, "Build v2.0b6".encode("utf-16"))
    stat_result = archive_path.stat()
    os.utime(archive_path, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000))

    assert cached_download_version(tmp_path, spec) == "v2.0b6"
