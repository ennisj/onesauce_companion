"""Cabinet transfer controller: push cached component ZIPs to the cabinet.

The machinery behind the Downloads screen's "Transfer to Cabinet" action
(formerly owned by the retired Cabinet screen). Owns the token-gated
LinkFileServer that streams cached ZIPs to the cabinet, the push worker
(off-thread MD5 hash + POST /api/v1/jobs), and the 1.5 s job poll loop whose
snapshots MainWindow mirrors into the Downloads table
(``_on_cabinet_jobs_polled``: Sending/Receiving/Installing states and the
Download Log lifecycle lines). When a job finishes, the affected components
are re-polled individually through the Cabinet Link panel so the table
converges on the cabinet's new installed versions.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from onesauce_companion.services.device_link import DeviceClient, DeviceJob
from onesauce_companion.services.download_cache import default_downloads_dir
from onesauce_companion.services.link_server import LinkFileServer
from onesauce_companion.services.versioning import parse_component_filename
from onesauce_companion.ui._worker_handle import WorkerHandle

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


class _PushJobWorker(QObject):
    """Hashes a cached ZIP (off the GUI thread) and POSTs an install job."""

    finished = Signal(str)  # stem
    error = Signal(str)

    def __init__(self, host: str, token: str, file_path: Path, file_url: str,
                 stem: str, display: str, group: str, version: str) -> None:
        super().__init__()
        self._host = host
        self._token = token
        self._path = file_path
        self._url = file_url
        self._stem = stem
        self._display = display
        self._group = group
        self._version = version

    @Slot()
    def run(self) -> None:
        try:
            size = self._path.stat().st_size
            md5 = _hash_file_md5(self._path)
            DeviceClient(self._host, token=self._token).post_job(
                stem=self._stem, display=self._display, group=self._group,
                filename=self._path.name, url=self._url, size=size, md5=md5,
                version=self._version,
            )
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(self._stem)


class _JobsPollWorker(QObject):
    """One poll of the cabinet's job list (off the GUI thread)."""

    finished = Signal(object)  # list[DeviceJob]
    error = Signal(str)

    def __init__(self, host: str, token: str) -> None:
        super().__init__()
        self._host = host
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            jobs = DeviceClient(self._host, token=self._token).jobs()
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(jobs)


def _hash_file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class CabinetTransferController(QObject):
    def __init__(self, window: "MainWindow") -> None:
        # Not parented to the window: MainWindow holds the reference, and the
        # tests drive this with a duck-typed (non-QObject) window stand-in.
        super().__init__()
        self._window = window
        self._push_handle = WorkerHandle(self)
        self._jobs_poll_handle = WorkerHandle(self)
        # stem -> group from the cabinet's component list; posted with a job so
        # the cabinet routes the install like its own catalog would.
        self._cabinet_component_groups: dict[str, str] = {}
        self._file_server = LinkFileServer(self._resolve_cached_file, self._token)
        self._jobs_timer = QTimer(self)
        self._jobs_timer.setInterval(1500)
        self._jobs_timer.timeout.connect(self._poll_jobs)
        window.cabinet_link.components_received.connect(self._on_components_received)

    def dispose(self) -> None:
        """Stop the file server + poll timer (called when the app closes)."""
        self._jobs_timer.stop()
        self._file_server.stop()

    # ---- link plumbing ----------------------------------------------------------

    def _token(self) -> str:
        return self._window.settings_store.get_cabinet_token()

    def _paired(self) -> bool:
        return bool(self._window._cabinet_host) and bool(self._token())

    @Slot(object)
    def _on_components_received(self, components: object) -> None:
        if isinstance(components, list):
            self._cabinet_component_groups.update(
                {c.stem: c.group for c in components if getattr(c, "stem", "")}
            )

    def _downloads_dir(self) -> Path:
        raw = ""
        try:
            raw = self._window.settings_store.load().downloads_path
        except Exception:  # pragma: no cover - settings unreadable
            raw = ""
        return Path(raw).expanduser() if raw else default_downloads_dir()

    def _resolve_cached_file(self, filename: str) -> Path | None:
        candidate = self._downloads_dir() / filename
        return candidate if candidate.is_file() else None

    # ---- push a cached component ZIP to the cabinet ------------------------------

    def push_cached_file(self, path: Path) -> bool:
        """Send a cached component ZIP to the paired cabinet.

        Returns True if the push was started; failures are reported through
        the Download Log.
        """
        if not self._paired() or self._push_handle.running or not path.is_file():
            return False
        host = self._window._cabinet_host
        stem, version = parse_component_filename(path.name)
        display = stem or path.name
        group = self._cabinet_component_groups.get(stem, "")
        try:
            self._file_server.start()
        except OSError as exc:
            self._window._append_downloads_log_line(
                f"Cabinet transfer failed: could not start the file server ({exc})."
            )
            return False
        file_url = self._file_server.file_url(path.name)
        worker = _PushJobWorker(host, self._token(), path, file_url,
                                stem, display, group, version)
        worker.finished.connect(self._on_push_posted)
        worker.error.connect(self._on_push_failed)
        self._push_handle.start(worker, finish_signals=[worker.finished, worker.error])
        return True

    @Slot(str)
    def _on_push_posted(self, stem: str) -> None:
        self._window._push_status_message(f"Sent {stem} to the cabinet")
        if not self._jobs_timer.isActive():
            self._jobs_timer.start()
        self._poll_jobs()

    @Slot(str)
    def _on_push_failed(self, message: str) -> None:
        self._window._append_downloads_log_line(
            f"Cabinet transfer failed to start: {message}"
        )
        self._window._push_status_message("Cabinet transfer failed — see the Download Log.")

    # ---- job progress polling -----------------------------------------------------

    def _poll_jobs(self) -> None:
        if not self._paired() or self._jobs_poll_handle.running:
            return
        worker = _JobsPollWorker(self._window._cabinet_host, self._token())
        worker.finished.connect(self._on_jobs_polled)
        worker.error.connect(self._on_jobs_poll_failed)
        self._jobs_poll_handle.start(worker, finish_signals=[worker.finished, worker.error])

    @Slot(object)
    def _on_jobs_polled(self, jobs: object) -> None:
        if not isinstance(jobs, list) or not jobs:
            # No link-originated jobs on the cabinet: nothing in flight.
            self._jobs_timer.stop()
            return
        device_jobs = [j for j in jobs if isinstance(j, DeviceJob)]
        # MainWindow mirrors these into the Downloads table (Sending/Receiving/
        # Installing states) and writes the Download Log lifecycle lines.
        self._window._on_cabinet_jobs_polled(device_jobs)
        if any(not job.is_terminal for job in device_jobs):
            if not self._jobs_timer.isActive():
                self._jobs_timer.start()
            return
        self._jobs_timer.stop()
        self._window._push_status_message("Cabinet install finished")
        # Targeted per-component polls (cheap on the cabinet) confirm the
        # installed version of exactly what this push touched, instead of
        # asking the cabinet for a full drive rescan.
        for job in device_jobs:
            if job.stem:
                self._window.cabinet_link.refresh_component(job.stem)

    @Slot(str)
    def _on_jobs_poll_failed(self, message: str) -> None:
        # Transient poll failure: keep the timer running for the next tick.
        pass
