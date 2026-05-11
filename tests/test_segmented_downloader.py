from __future__ import annotations

from onesauce_companion.services.downloader import Downloader, _assemble_segments, _planned_segments


class _FakeResponse:
    status_code = 206

    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass

    def close(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self._content), chunk_size):
            yield self._content[index : index + chunk_size]


class _FakeArchiveFile:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self.ranges: list[str] = []

    def download(self, **kwargs):
        range_header = kwargs["headers"]["Range"]
        self.ranges.append(range_header)
        bounds = range_header.removeprefix("bytes=").split("-", 1)
        start = int(bounds[0])
        end = int(bounds[1])
        return _FakeResponse(self._content[start : end + 1])


def test_planned_segments_spreads_remainder_across_early_segments() -> None:
    segments = _planned_segments(10, 4)

    assert [(segment.start, segment.end, segment.length) for segment in segments] == [
        (0, 2, 3),
        (3, 5, 3),
        (6, 7, 2),
        (8, 9, 2),
    ]


def test_assemble_segments_writes_destination_in_order(tmp_path) -> None:
    destination = tmp_path / "archive.zip"
    segments = _planned_segments(6, 3)
    for segment, content in zip(segments, (b"ab", b"cd", b"ef"), strict=True):
        (tmp_path / f"archive.zip.part.{segment.index}").write_bytes(content)

    _assemble_segments(destination, segments)

    assert destination.read_bytes() == b"abcdef"
    assert not (tmp_path / "archive.zip.part").exists()
    for segment in segments:
        assert not (tmp_path / f"archive.zip.part.{segment.index}").exists()


def test_segmented_download_downloads_ranges_and_assembles_destination(tmp_path) -> None:
    content = b"abcdefghij"
    archive_file = _FakeArchiveFile(content)
    downloader = Downloader()
    downloader.segmented_download_segments = 4
    progress: list[tuple[int, int | None]] = []

    result = downloader._download_segmented(
        archive_file,
        tmp_path / "archive.zip",
        controller=None,
        component_key=None,
        progress_callback=lambda current, total: progress.append((current, total)),
        retries=0,
        chunk_size=2,
        total_bytes=len(content),
    )

    assert result.path.read_bytes() == content
    assert result.total_bytes == len(content)
    assert result.resumed is False
    assert sorted(archive_file.ranges) == [
        "bytes=0-2",
        "bytes=3-5",
        "bytes=6-7",
        "bytes=8-9",
    ]
    assert progress[-1] == (len(content), len(content))
