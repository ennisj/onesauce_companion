from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BufferedRandom, BufferedWriter
from pathlib import Path
from threading import RLock
from time import monotonic, sleep
from typing import Callable

from internetarchive import get_item, get_session
from requests.exceptions import ConnectTimeout, ConnectionError, HTTPError, ReadTimeout

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.archive_org import USER_AGENT, ArchiveOrgCredentials, get_authenticated_config
from onesauce_companion.services.control import OperationController


ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    bytes_downloaded: int
    total_bytes: int | None
    resumed: bool


@dataclass(frozen=True)
class _DownloadSegment:
    index: int
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class DownloadAuthorizationError(RuntimeError):
    """Raised when Archive.org denies access to a download."""


class Downloader:
    def __init__(
        self,
        auth_config: dict | None = None,
        authenticated_user: str | None = None,
        authenticated_email: str | None = None,
        file_metadata_cache: dict[str, dict[str, dict]] | None = None,
        file_metadata_lock: RLock | None = None,
    ) -> None:
        self._auth_lock = RLock()
        self._auth_config = copy.deepcopy(auth_config) if auth_config is not None else None
        self._session = self._build_session()
        self._authenticated_user = authenticated_user
        self._authenticated_email = authenticated_email
        self._file_metadata_cache = file_metadata_cache if file_metadata_cache is not None else {}
        self._file_metadata_lock = file_metadata_lock if file_metadata_lock is not None else RLock()
        self.segmented_downloads_enabled = False
        self.segmented_download_min_size_bytes = 512 * 1024 * 1024
        self.segmented_download_segments = 4

    def clone(self) -> "Downloader":
        with self._auth_lock:
            clone = Downloader(
                auth_config=self._auth_config,
                authenticated_user=self._authenticated_user,
                authenticated_email=self._authenticated_email,
                file_metadata_cache=self._file_metadata_cache,
                file_metadata_lock=self._file_metadata_lock,
            )
            clone.segmented_downloads_enabled = self.segmented_downloads_enabled
            clone.segmented_download_min_size_bytes = self.segmented_download_min_size_bytes
            clone.segmented_download_segments = self.segmented_download_segments
            return clone

    def authenticate_with_archive_org(self, credentials: ArchiveOrgCredentials | None) -> str | None:
        if credentials is None:
            return None
        with self._auth_lock:
            if self._authenticated_email == credentials.email and self._auth_config is not None:
                return self._authenticated_user
            self._auth_config, self._authenticated_user = get_authenticated_config(credentials)
            self._authenticated_email = credentials.email
            self._session = self._build_session()
            return self._authenticated_user

    @property
    def authenticated_user(self) -> str | None:
        with self._auth_lock:
            return self._authenticated_user

    def download(
        self,
        spec: ComponentSpec,
        destination: Path,
        controller: OperationController | None = None,
        component_key: str | None = None,
        progress_callback: ProgressCallback | None = None,
        retries: int = 3,
        chunk_size: int = 4 * 1024 * 1024,
    ) -> DownloadResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if controller:
            controller.raise_if_cancelled(component_key)
        if destination.exists():
            size = destination.stat().st_size
            if progress_callback:
                progress_callback(size, size)
            return DownloadResult(
                path=destination,
                bytes_downloaded=size,
                total_bytes=size,
                resumed=False,
            )
        partial_path = destination.with_suffix(destination.suffix + ".part")
        return self._download_once(
            spec,
            destination,
            partial_path,
            controller,
            component_key,
            progress_callback,
            retries,
            chunk_size,
        )

    def _download_once(
        self,
        spec: ComponentSpec,
        destination: Path,
        partial_path: Path,
        controller: OperationController | None,
        component_key: str | None,
        progress_callback: ProgressCallback | None,
        retries: int,
        chunk_size: int,
    ) -> DownloadResult:
        item, file_metadata = self._item_and_file_metadata(spec)
        if file_metadata is None:
            raise FileNotFoundError(f"Archive.org file not found: {spec.archive_item}/{spec.filename}")

        archive_file = item.get_file(spec.filename, file_metadata=file_metadata)
        total_bytes = _parse_total_bytes(file_metadata, spec)
        if total_bytes is not None and partial_path.exists() and partial_path.stat().st_size >= total_bytes:
            partial_path.replace(destination)
            final_size = destination.stat().st_size
            if progress_callback:
                progress_callback(final_size, total_bytes)
            return DownloadResult(
                path=destination,
                bytes_downloaded=final_size,
                total_bytes=total_bytes,
                resumed=True,
            )

        if total_bytes is not None and self._should_use_segmented_download(destination, partial_path, total_bytes):
            response = None
            try:
                response = archive_file.download(
                    file_path=partial_path.name,
                    destdir=str(partial_path.parent),
                    retries=0,
                    verbose=False,
                    return_responses=True,
                    chunk_size=1,
                    headers={"Range": "bytes=0-0"},
                )
                if getattr(response, "status_code", None) == 206:
                    return self._download_segmented(
                        archive_file,
                        destination,
                        controller,
                        component_key,
                        progress_callback,
                        retries,
                        chunk_size,
                        total_bytes,
                    )
            finally:
                if response is not None:
                    response.close()

        last_error: Exception | None = None
        resumed_any = False
        for attempt in range(retries + 1):
            existing_size = partial_path.stat().st_size if partial_path.exists() else 0
            resumed = existing_size > 0
            resumed_any = resumed_any or resumed
            headers: dict[str, str] = {}
            if resumed:
                headers["Range"] = f"bytes={existing_size}-"
            if progress_callback:
                progress_callback(existing_size, total_bytes)
            if controller:
                controller.raise_if_paused(component_key)
                controller.raise_if_cancelled(component_key)

            response = None
            try:
                response = archive_file.download(
                    file_path=partial_path.name,
                    destdir=str(partial_path.parent),
                    retries=0,
                    verbose=False,
                    return_responses=True,
                    chunk_size=chunk_size,
                    headers=headers,
                )
                if resumed and getattr(response, "status_code", None) != 206:
                    try:
                        partial_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    if attempt < retries:
                        continue
                    raise OSError("Archive.org did not honor the resume request for the partial download.")

                controlled_handle = _ControlledFileWriter(
                    partial_path,
                    downloaded=existing_size,
                    total_bytes=total_bytes,
                    controller=controller,
                    component_key=component_key,
                    progress_callback=progress_callback,
                )
                with response:
                    with controlled_handle:
                        if resumed:
                            controlled_handle.seek(existing_size)
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                controlled_handle.write(chunk)
                written_size = partial_path.stat().st_size if partial_path.exists() else 0
                if total_bytes is not None and written_size != total_bytes:
                    if written_size > total_bytes:
                        # Oversized partials cannot be resumed; restart from scratch.
                        partial_path.unlink(missing_ok=True)
                    last_error = OSError(
                        f"Download for {spec.filename} ended early: "
                        f"got {written_size} of {total_bytes} bytes."
                    )
                    if attempt < retries:
                        continue
                    raise last_error
                break
            except HTTPError as exc:
                response_obj = exc.response
                if response_obj is not None and response_obj.status_code in {401, 403}:
                    raise DownloadAuthorizationError(
                        "Archive.org denied access to this file. Enter valid Archive.org credentials and try again."
                    ) from exc
                last_error = exc
            except (ConnectionError, ConnectTimeout, ReadTimeout, OSError) as exc:
                last_error = exc
            finally:
                if response is not None:
                    response.close()

            if attempt >= retries:
                assert last_error is not None
                raise last_error
            sleep(1)

        if controller:
            controller.raise_if_cancelled(component_key)
        partial_path.replace(destination)
        final_size = destination.stat().st_size
        if progress_callback:
            progress_callback(final_size, total_bytes or final_size)
        return DownloadResult(
            path=destination,
            bytes_downloaded=final_size,
            total_bytes=total_bytes or final_size,
            resumed=resumed_any,
        )

    def _build_session(self):
        session = get_session(config=self._auth_config)
        session.headers.update({"User-Agent": USER_AGENT})
        return session

    def _should_use_segmented_download(
        self,
        destination: Path,
        partial_path: Path,
        total_bytes: int | None,
    ) -> bool:
        if not self.segmented_downloads_enabled or total_bytes is None:
            return False
        if total_bytes < max(1, self.segmented_download_min_size_bytes):
            return False
        if self.segmented_download_segments < 2:
            return False
        if destination.exists() or partial_path.exists():
            return False
        return True

    def _download_segmented(
        self,
        archive_file,
        destination: Path,
        controller: OperationController | None,
        component_key: str | None,
        progress_callback: ProgressCallback | None,
        retries: int,
        chunk_size: int,
        total_bytes: int,
    ) -> DownloadResult:
        segments = _planned_segments(total_bytes, self.segmented_download_segments)
        segment_progress = [_existing_segment_size(destination, segment) for segment in segments]
        resumed = any(size > 0 for size in segment_progress)
        progress_emitter = _AggregateProgressEmitter(segment_progress, total_bytes, progress_callback)
        if progress_callback:
            progress_callback(sum(segment_progress), total_bytes)

        with ThreadPoolExecutor(max_workers=len(segments)) as executor:
            futures = [
                executor.submit(
                    self._download_segment,
                    archive_file,
                    destination,
                    segment,
                    controller,
                    component_key,
                    retries,
                    chunk_size,
                    progress_emitter,
                )
                for segment in segments
            ]
            try:
                for future in as_completed(futures):
                    future.result()
            except Exception:
                for future in futures:
                    future.cancel()
                raise

        _assemble_segments(destination, segments)
        final_size = destination.stat().st_size
        if final_size != total_bytes:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise OSError(f"Downloaded file size mismatch: expected {total_bytes}, got {final_size}.")
        if progress_callback:
            progress_callback(final_size, total_bytes)
        return DownloadResult(
            path=destination,
            bytes_downloaded=final_size,
            total_bytes=total_bytes,
            resumed=resumed,
        )

    def _download_segment(
        self,
        archive_file,
        destination: Path,
        segment: "_DownloadSegment",
        controller: OperationController | None,
        component_key: str | None,
        retries: int,
        chunk_size: int,
        progress_emitter: "_AggregateProgressEmitter",
    ) -> None:
        segment_path = _segment_path(destination, segment.index)
        segment_path.parent.mkdir(parents=True, exist_ok=True)
        existing_size = segment_path.stat().st_size if segment_path.exists() else 0
        if existing_size > segment.length:
            segment_path.unlink(missing_ok=True)
            existing_size = 0
        if existing_size == segment.length:
            progress_emitter.update(segment.index, existing_size)
            return

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            if controller:
                controller.raise_if_paused(component_key)
                controller.raise_if_cancelled(component_key)
            existing_size = segment_path.stat().st_size if segment_path.exists() else 0
            if existing_size > segment.length:
                segment_path.unlink(missing_ok=True)
                existing_size = 0
            if existing_size == segment.length:
                progress_emitter.update(segment.index, existing_size)
                return
            range_start = segment.start + existing_size
            headers = {"Range": f"bytes={range_start}-{segment.end}"}
            response = None
            try:
                response = archive_file.download(
                    file_path=segment_path.name,
                    destdir=str(segment_path.parent),
                    retries=0,
                    verbose=False,
                    return_responses=True,
                    chunk_size=chunk_size,
                    headers=headers,
                )
                if getattr(response, "status_code", None) != 206:
                    raise OSError("Archive.org did not honor the segmented range request.")
                mode = "ab" if existing_size else "wb"
                downloaded = existing_size
                with response:
                    with segment_path.open(mode) as handle:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if controller:
                                controller.raise_if_paused(component_key)
                                controller.raise_if_cancelled(component_key)
                            if not chunk:
                                continue
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if downloaded > segment.length:
                                raise OSError("Segment download exceeded its expected length.")
                            progress_emitter.update(segment.index, downloaded)
                if downloaded == segment.length:
                    return
                raise OSError("Segment download ended before its expected length.")
            except HTTPError as exc:
                response_obj = exc.response
                if response_obj is not None and response_obj.status_code in {401, 403}:
                    raise DownloadAuthorizationError(
                        "Archive.org denied access to this file. Enter valid Archive.org credentials and try again."
                    ) from exc
                last_error = exc
            except (ConnectionError, ConnectTimeout, ReadTimeout, OSError) as exc:
                last_error = exc
            finally:
                if response is not None:
                    response.close()
            if attempt >= retries:
                assert last_error is not None
                raise last_error
            sleep(1)

    def _item_and_file_metadata(self, spec: ComponentSpec):
        item = get_item(spec.archive_item, archive_session=self._session)
        with self._file_metadata_lock:
            files_by_name = self._file_metadata_cache.get(spec.archive_item)
            if files_by_name is not None:
                return item, files_by_name.get(spec.filename)

            files_by_name = {
                str(entry.get("name")): entry
                for entry in item.files
                if isinstance(entry.get("name"), str)
            }
            self._file_metadata_cache[spec.archive_item] = files_by_name
            return item, files_by_name.get(spec.filename)


def _parse_total_bytes(file_metadata: dict, spec: ComponentSpec) -> int | None:
    value = file_metadata.get("size")
    if value is None:
        return spec.size_bytes
    try:
        return int(value)
    except (TypeError, ValueError):
        return spec.size_bytes


def _planned_segments(total_bytes: int, requested_segments: int) -> tuple[_DownloadSegment, ...]:
    segment_count = max(2, min(8, requested_segments, total_bytes))
    base_size, remainder = divmod(total_bytes, segment_count)
    segments: list[_DownloadSegment] = []
    start = 0
    for index in range(segment_count):
        length = base_size + (1 if index < remainder else 0)
        end = start + length - 1
        segments.append(_DownloadSegment(index=index, start=start, end=end))
        start = end + 1
    return tuple(segments)


def _segment_path(destination: Path, index: int) -> Path:
    return Path(f"{destination}.part.{index}")


def _existing_segment_size(destination: Path, segment: _DownloadSegment) -> int:
    path = _segment_path(destination, segment.index)
    return min(path.stat().st_size, segment.length) if path.exists() else 0


def _assemble_segments(destination: Path, segments: tuple[_DownloadSegment, ...]) -> None:
    partial_path = destination.with_suffix(destination.suffix + ".part")
    try:
        with partial_path.open("wb") as output:
            for segment in segments:
                path = _segment_path(destination, segment.index)
                size = path.stat().st_size
                if size != segment.length:
                    raise OSError(f"Segment {segment.index} size mismatch: expected {segment.length}, got {size}.")
                with path.open("rb") as input_file:
                    while True:
                        data = input_file.read(8 * 1024 * 1024)
                        if not data:
                            break
                        output.write(data)
        partial_path.replace(destination)
    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    for segment in segments:
        try:
            _segment_path(destination, segment.index).unlink(missing_ok=True)
        except OSError:
            pass


class _AggregateProgressEmitter:
    def __init__(
        self,
        segment_progress: list[int],
        total_bytes: int,
        progress_callback: ProgressCallback | None,
    ) -> None:
        self._segment_progress = segment_progress
        self._total_bytes = total_bytes
        self._progress_callback = progress_callback
        self._lock = RLock()
        self._last_progress_bytes = sum(segment_progress)
        self._last_progress_at = 0.0

    def update(self, index: int, downloaded: int) -> None:
        if self._progress_callback is None:
            return
        with self._lock:
            self._segment_progress[index] = downloaded
            total_downloaded = sum(self._segment_progress)
            now = monotonic()
            should_emit = (
                total_downloaded == self._total_bytes
                or total_downloaded - self._last_progress_bytes >= 8 * 1024 * 1024
                or now - self._last_progress_at >= 0.25
            )
            if not should_emit:
                return
            self._last_progress_bytes = total_downloaded
            self._last_progress_at = now
        self._progress_callback(total_downloaded, self._total_bytes)


class _ControlledFileWriter:
    def __init__(
        self,
        path: Path,
        *,
        downloaded: int,
        total_bytes: int | None,
        controller: OperationController | None,
        component_key: str | None,
        progress_callback: ProgressCallback | None,
    ) -> None:
        self._path = path
        self._handle: BufferedRandom | BufferedWriter | None = None
        self._downloaded = downloaded
        self._total_bytes = total_bytes
        self._controller = controller
        self._component_key = component_key
        self._progress_callback = progress_callback
        self._resume_mode = False
        self._last_progress_bytes = downloaded
        self._last_progress_at = 0.0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.close()

    def write(self, chunk: bytes) -> int:
        if self._controller:
            self._controller.raise_if_paused(self._component_key)
            self._controller.raise_if_cancelled(self._component_key)
        handle = self._ensure_handle()
        written = handle.write(chunk)
        self._downloaded += written
        if self._progress_callback is not None and self._should_emit_progress():
            self._progress_callback(self._downloaded, self._total_bytes)
        return written

    def seek(self, offset: int, whence: int = 0) -> int:
        self._resume_mode = True
        return self._ensure_handle().seek(offset, whence)

    def _ensure_handle(self):
        if self._handle is not None:
            return self._handle
        if self._resume_mode:
            self._handle = self._path.open("rb+")
        else:
            self._handle = self._path.open("wb")
        return self._handle

    def __getattr__(self, name: str):
        if self._handle is None and name in {"tell", "fileno", "flush"}:
            self._ensure_handle()
        if self._handle is None:
            raise AttributeError(name)
        return getattr(self._handle, name)

    def _should_emit_progress(self) -> bool:
        if self._progress_callback is None:
            return False
        now = monotonic()
        if self._downloaded == self._total_bytes:
            self._last_progress_bytes = self._downloaded
            self._last_progress_at = now
            return True
        if self._downloaded - self._last_progress_bytes >= 8 * 1024 * 1024:
            self._last_progress_bytes = self._downloaded
            self._last_progress_at = now
            return True
        if now - self._last_progress_at >= 0.25:
            self._last_progress_bytes = self._downloaded
            self._last_progress_at = now
            return True
        return False

