from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Callable

from internetarchive import get_item, get_session
from requests.exceptions import ConnectTimeout, ConnectionError, HTTPError, ReadTimeout

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.archive_org import ArchiveOrgCredentials, get_authenticated_config
from onesauce_companion.services.control import OperationController


ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    bytes_downloaded: int
    total_bytes: int | None
    resumed: bool


class DownloadAuthorizationError(RuntimeError):
    """Raised when Archive.org denies access to a download."""


class Downloader:
    def __init__(
        self,
        auth_config: dict | None = None,
        authenticated_user: str | None = None,
        authenticated_email: str | None = None,
    ) -> None:
        self._auth_config = copy.deepcopy(auth_config) if auth_config is not None else None
        self._session = self._build_session()
        self._authenticated_user = authenticated_user
        self._authenticated_email = authenticated_email

    def clone(self) -> "Downloader":
        return Downloader(
            auth_config=self._auth_config,
            authenticated_user=self._authenticated_user,
            authenticated_email=self._authenticated_email,
        )

    def authenticate_with_archive_org(self, credentials: ArchiveOrgCredentials | None) -> str | None:
        if credentials is None:
            return None
        if self._authenticated_email == credentials.email and self._auth_config is not None:
            return self._authenticated_user
        self._auth_config, self._authenticated_user = get_authenticated_config(credentials)
        self._authenticated_email = credentials.email
        self._session = self._build_session()
        return self._authenticated_user

    @property
    def authenticated_user(self) -> str | None:
        return self._authenticated_user

    def download(
        self,
        spec: ComponentSpec,
        destination: Path,
        controller: OperationController | None = None,
        component_key: str | None = None,
        progress_callback: ProgressCallback | None = None,
        retries: int = 3,
        chunk_size: int = 1024 * 1024,
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
        item = get_item(spec.archive_item, archive_session=self._session)
        file_metadata = next((entry for entry in item.files if entry.get("name") == spec.filename), None)
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
                controller.wait_if_paused(component_key)
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
        session.headers.update({"User-Agent": "onesauce-companion/0.1.0"})
        return session


def _parse_total_bytes(file_metadata: dict, spec: ComponentSpec) -> int | None:
    value = file_metadata.get("size")
    if value is None:
        return spec.size_bytes
    try:
        return int(value)
    except (TypeError, ValueError):
        return spec.size_bytes


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
        self._handle = None
        self._downloaded = downloaded
        self._total_bytes = total_bytes
        self._controller = controller
        self._component_key = component_key
        self._progress_callback = progress_callback
        self._resume_mode = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.close()

    def write(self, chunk: bytes) -> int:
        if self._controller:
            self._controller.wait_if_paused(self._component_key)
            self._controller.raise_if_cancelled(self._component_key)
        handle = self._ensure_handle()
        written = handle.write(chunk)
        handle.flush()
        self._downloaded += written
        if self._progress_callback:
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

