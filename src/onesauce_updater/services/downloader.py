from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from onesauce_updater.services.archive_org import ArchiveOrgCredentials, authenticate
from onesauce_updater.services.control import OperationController


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
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "onesauce-updater/0.1.0"})
        self._authenticated_user: str | None = None

    def clone(self) -> "Downloader":
        cloned = Downloader()
        cloned._session.cookies.update(self._session.cookies)
        cloned._authenticated_user = self._authenticated_user
        return cloned

    def authenticate_with_archive_org(self, credentials: ArchiveOrgCredentials | None) -> str | None:
        if credentials is None:
            return None
        if self._authenticated_user == credentials.email:
            return self._authenticated_user
        self._authenticated_user = authenticate(self._session, credentials)
        return self._authenticated_user

    @property
    def authenticated_user(self) -> str | None:
        return self._authenticated_user

    def download(
        self,
        url: str,
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

        last_error: Exception | None = None
        for _ in range(retries):
            try:
                return self._download_once(
                    url,
                    destination,
                    partial_path,
                    controller,
                    component_key,
                    progress_callback,
                    chunk_size,
                )
            except (requests.RequestException, OSError) as exc:
                last_error = exc
        if last_error is None:
            raise RuntimeError(f"Download failed for {url}")
        raise last_error

    def _download_once(
        self,
        url: str,
        destination: Path,
        partial_path: Path,
        controller: OperationController | None,
        component_key: str | None,
        progress_callback: ProgressCallback | None,
        chunk_size: int,
    ) -> DownloadResult:
        existing_size = partial_path.stat().st_size if partial_path.exists() else 0
        headers: dict[str, str] = {}
        if existing_size:
            headers["Range"] = f"bytes={existing_size}-"

        with self._session.get(url, stream=True, timeout=(15, 300), headers=headers) as response:
            if response.status_code in {401, 403}:
                raise DownloadAuthorizationError(
                    "Archive.org denied access to this file. Enter valid Archive.org credentials and try again."
                )
            response.raise_for_status()

            resumed = existing_size > 0 and response.status_code == 206
            if existing_size and not resumed:
                partial_path.unlink(missing_ok=True)
                existing_size = 0

            total_bytes = _resolve_total_bytes(response, existing_size)
            downloaded = existing_size
            mode = "ab" if resumed else "wb"

            if progress_callback:
                progress_callback(downloaded, total_bytes)

            with partial_path.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if controller:
                        controller.wait_if_paused(component_key)
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_bytes)

        partial_path.replace(destination)
        return DownloadResult(
            path=destination,
            bytes_downloaded=downloaded,
            total_bytes=total_bytes,
            resumed=resumed,
        )


def _resolve_total_bytes(response: requests.Response, existing_size: int) -> int | None:
    content_length = response.headers.get("Content-Length")
    if content_length is None:
        return None
    try:
        length = int(content_length)
    except ValueError:
        return None
    if response.status_code == 206:
        return existing_size + length
    return length
