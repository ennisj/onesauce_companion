from __future__ import annotations

import pytest

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.downloader import Downloader


def _spec(filename: str = "Component v1.0b1.zip", size_bytes: int | None = None) -> ComponentSpec:
    return ComponentSpec(
        key="component",
        display_name="Component",
        archive_item="test-item",
        filename=filename,
        download_url=f"https://archive.org/download/test-item/{filename}",
        install_root="Component",
        version_file_relpath=None,
        available_version="v1.0b1",
        size_bytes=size_bytes,
    )


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int) -> None:
        self._content = content
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass

    def close(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self._content), chunk_size):
            yield self._content[index : index + chunk_size]


class _TruncatingArchiveFile:
    """Serves a truncated body on the first request and full ranges afterwards."""

    def __init__(self, content: bytes, truncate_first_to: int) -> None:
        self._content = content
        self._truncate_first_to = truncate_first_to
        self.request_count = 0

    def download(self, **kwargs):
        self.request_count += 1
        headers = kwargs.get("headers") or {}
        range_header = headers.get("Range")
        if range_header:
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            body = self._content[start:]
            status_code = 206
        else:
            body = self._content
            status_code = 200
        if self.request_count == 1:
            body = body[: self._truncate_first_to]
        return _FakeResponse(body, status_code)


class _FakeItem:
    def __init__(self, archive_file: _TruncatingArchiveFile) -> None:
        self._archive_file = archive_file

    def get_file(self, _filename: str, file_metadata=None):
        return self._archive_file


def _downloader_for(archive_file: _TruncatingArchiveFile, total_bytes: int) -> Downloader:
    downloader = Downloader()
    downloader._item_and_file_metadata = lambda spec: (_FakeItem(archive_file), {"size": str(total_bytes)})
    return downloader


def test_truncated_download_resumes_on_retry(tmp_path) -> None:
    content = b"0123456789"
    archive_file = _TruncatingArchiveFile(content, truncate_first_to=6)
    downloader = _downloader_for(archive_file, len(content))
    destination = tmp_path / "Component v1.0b1.zip"

    result = downloader.download(_spec(), destination, retries=2, chunk_size=4)

    assert destination.read_bytes() == content
    assert result.bytes_downloaded == len(content)
    assert result.total_bytes == len(content)
    assert not destination.with_suffix(destination.suffix + ".part").exists()
    assert archive_file.request_count == 2
    assert result.resumed is True


def test_truncated_download_raises_and_keeps_partial_when_retries_exhausted(tmp_path) -> None:
    content = b"0123456789"
    archive_file = _TruncatingArchiveFile(content, truncate_first_to=6)
    downloader = _downloader_for(archive_file, len(content))
    destination = tmp_path / "Component v1.0b1.zip"

    with pytest.raises(OSError, match="ended early"):
        downloader.download(_spec(), destination, retries=0, chunk_size=4)

    assert not destination.exists()
    partial_path = destination.with_suffix(destination.suffix + ".part")
    assert partial_path.exists()
    assert partial_path.read_bytes() == content[:6]


def test_complete_download_succeeds_first_attempt(tmp_path) -> None:
    content = b"0123456789"
    archive_file = _TruncatingArchiveFile(content, truncate_first_to=len(content))
    downloader = _downloader_for(archive_file, len(content))
    destination = tmp_path / "Component v1.0b1.zip"

    result = downloader.download(_spec(), destination, retries=0, chunk_size=4)

    assert destination.read_bytes() == content
    assert result.resumed is False
    assert archive_file.request_count == 1
