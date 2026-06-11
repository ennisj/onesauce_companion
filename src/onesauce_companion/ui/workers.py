from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from onesauce_companion.services.archive_org import ArchiveOrgCredentials, authenticate
from onesauce_companion.services.control import OperationCancelledError, OperationController
from onesauce_companion.services.github_releases import fetch_latest_release_tag, is_newer_release_available
from onesauce_companion.services.installer import Installer


class InstallWorker(QObject):
    finished = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    log = Signal(str)
    component_status = Signal(str, str)
    progress = Signal(object)

    def __init__(
        self,
        installer: Installer,
        target_dir: Path,
        credentials: ArchiveOrgCredentials | None,
        controller: OperationController,
        download_only: bool = False,
        force_component_keys: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.installer = installer
        self.target_dir = target_dir
        self.credentials = credentials
        self.controller = controller
        self.download_only = download_only
        self.force_component_keys = force_component_keys or set()

    @Slot()
    def run(self) -> None:
        try:
            report = self.installer.install_required(
                self.target_dir,
                credentials=self.credentials,
                controller=self.controller,
                status_callback=lambda key, status: self.component_status.emit(key, status),
                log_callback=self.log.emit,
                phase_callback=self.progress.emit,
                download_only=self.download_only,
                force_component_keys=self.force_component_keys,
            )
        except OperationCancelledError as exc:
            self.cancelled.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(report)


class ValidateCredentialsWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, credentials: ArchiveOrgCredentials) -> None:
        super().__init__()
        self.credentials = credentials

    @Slot()
    def run(self) -> None:
        try:
            user = authenticate(self.credentials)
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(user)


class ReleaseCheckWorker(QObject):
    finished = Signal(str, bool)
    error = Signal(str)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version

    @Slot()
    def run(self) -> None:
        try:
            latest_tag = fetch_latest_release_tag()
            is_newer = is_newer_release_available(self.current_version, latest_tag)
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(latest_tag or "", is_newer)


class RemoteSizesWorker(QObject):
    """Fetches archive.org per-file sizes off the GUI thread.

    Each spec is sent through ``ArchiveMetadataService.size_for_spec`` and the
    resulting (size_display, size_bytes) tuple is emitted via ``size_ready``.
    """

    size_ready = Signal(str, str, object)  # spec_key, size_display, size_bytes (int or None)
    finished = Signal()

    def __init__(self, archive_metadata: object, specs: Sequence[object], credentials: object | None) -> None:
        super().__init__()
        self._archive_metadata = archive_metadata
        self._specs = tuple(specs)
        self._credentials = credentials

    @Slot()
    def run(self) -> None:
        for spec in self._specs:
            try:
                size_display, size_bytes = self._archive_metadata.size_for_spec(  # type: ignore[attr-defined]
                    spec, self._credentials
                )
            except Exception:  # pragma: no cover - falls back to spec defaults
                size_display, size_bytes = spec.size_display, spec.size_bytes  # type: ignore[attr-defined]
            self.size_ready.emit(spec.key, size_display, size_bytes)  # type: ignore[attr-defined]
        self.finished.emit()


class ThemeCatalogWorker(QObject):
    """Builds the theme catalog off the GUI thread, emitting per-theme progress.

    Imports are deferred inside ``run`` to avoid pulling the themes service
    into the workers module at import time (themes.py has heavy XML/Lua deps).
    """

    entry_ready = Signal(int, int, object)  # 1-indexed completed, total, ThemeCatalogEntry
    finished = Signal(object, str)  # tuple[ThemeCatalogEntry, ...], target_key

    def __init__(self, target_dir: Path | None, target_key: str) -> None:
        super().__init__()
        self._target_dir = target_dir
        self._target_key = target_key

    @Slot()
    def run(self) -> None:
        from onesauce_companion.services.themes import (
            build_theme_catalog_entry,
            list_theme_directories,
        )

        theme_dirs = list_theme_directories(self._target_dir)
        total = len(theme_dirs)
        entries: list[object] = []
        for index, theme_dir in enumerate(theme_dirs):
            try:
                entry = build_theme_catalog_entry(theme_dir)
            except Exception:  # pragma: no cover - skip broken theme dirs
                continue
            entries.append(entry)
            self.entry_ready.emit(index + 1, total, entry)
        self.finished.emit(tuple(entries), self._target_key)


class LogLoadWorker(QObject):
    """Reads a log file off the GUI thread.

    When ``max_bytes`` is set, only the last ``max_bytes`` of the file are
    read (the leading partial line is discarded). Emits
    ``finished(log_key, content, was_truncated)`` on success or
    ``failed(log_key)`` on read error.
    """

    finished = Signal(str, str, bool)
    failed = Signal(str)

    def __init__(self, log_key: str, log_path: Path, max_bytes: int | None = None) -> None:
        super().__init__()
        self._log_key = log_key
        self._log_path = log_path
        self._max_bytes = max_bytes

    @Slot()
    def run(self) -> None:
        try:
            size = self._log_path.stat().st_size
            if self._max_bytes is None or size <= self._max_bytes:
                content = self._log_path.read_text(encoding="utf-8", errors="replace")
                truncated = False
            else:
                with self._log_path.open("rb") as handle:
                    handle.seek(size - self._max_bytes)
                    data = handle.read()
                newline = data.find(b"\n")
                if newline != -1 and newline + 1 < len(data):
                    data = data[newline + 1:]
                content = data.decode("utf-8", errors="replace")
                truncated = True
        except OSError:
            self.failed.emit(self._log_key)
            return
        self.finished.emit(self._log_key, content, truncated)


class InstalledStatusWorker(QObject):
    """Scans installer targets off the GUI thread.

    Each job is (installer_key, installer, target_dir). Results are emitted
    per-installer via ``statuses_ready(installer_key, dict[spec_key, status])``
    and a final ``finished`` signal fires after all jobs complete.
    """

    statuses_ready = Signal(str, object)  # installer_key, dict[str, ComponentStatus]
    finished = Signal()

    def __init__(self, jobs: Sequence[tuple[str, object, object]]) -> None:
        super().__init__()
        self._jobs = tuple(jobs)

    @Slot()
    def run(self) -> None:
        for key, installer, target in self._jobs:
            statuses: dict[str, object] = {}
            if target is not None:
                try:
                    for status in installer.scan_target(target):  # type: ignore[attr-defined]
                        statuses[status.spec.key] = status  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover - falls back to empty
                    statuses = {}
            self.statuses_ready.emit(key, statuses)
        self.finished.emit()


class CatalogRefreshWorker(QObject):
    """Fetches archive.org catalog specs off the GUI thread.

    Each job is (catalog_key, catalog_service, force_refresh). The catalog
    service must expose a ``specs(force_refresh: bool)`` method. Per-catalog
    results are emitted via ``specs_ready`` as soon as each completes;
    ``refresh_failed`` fires for catalogs that fell back to stale data; a
    final ``finished`` signal fires after all jobs finish.
    """

    specs_ready = Signal(str, object)
    refresh_failed = Signal(str)
    finished = Signal()

    def __init__(self, jobs: Sequence[tuple[str, object, bool]]) -> None:
        super().__init__()
        self._jobs = tuple(jobs)

    @Slot()
    def run(self) -> None:
        for key, catalog, force_refresh in self._jobs:
            try:
                specs = catalog.specs(force_refresh=force_refresh)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - unexpected loader failure
                self.refresh_failed.emit(key)
                self.specs_ready.emit(key, None)
                continue
            if getattr(catalog, "last_refresh_failed", False):
                self.refresh_failed.emit(key)
            self.specs_ready.emit(key, specs)
        self.finished.emit()
