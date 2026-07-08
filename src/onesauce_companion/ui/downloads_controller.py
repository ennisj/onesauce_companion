"""Controller owning the Downloads screen's operation state machine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Qt, Slot

from onesauce_companion.models import ComponentSpec, InstallProgress
from onesauce_companion.services.control import OperationController
from onesauce_companion.services.download_cache import cached_download_version
from onesauce_companion.services.installer import Installer
from onesauce_companion.services.settings import AppSettings
from onesauce_companion.ui.workers import InstallWorker

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


@dataclass
class DownloadsOperationState:
    kind: str  # "download" | "install"
    status: str


#: Operation statuses that survive an application restart.
PERSISTED_OPERATION_STATUSES = frozenset(
    {"Pending Download", "Pending Download (Paused)", "Pending Install", "Download Paused", "Install Paused"}
)


class DownloadsController(QObject):
    """Owns the Downloads screen's per-component operations and worker lanes.

    Responsibilities: the operation state machine (pending, active, and
    paused downloads/installs), the parallel download lanes and the single
    install lane, scheduling, pause/resume/cancel, auto-install chaining
    after downloads, and persistence of pending operations across restarts.

    Lane cleanup deliberately happens when a worker *reports* its outcome
    (finished/cancelled/error signals), not when its thread finishes — the
    scheduler keys parallel capacity off the lane dictionaries, and freeing
    a lane at report time lets the next operation start immediately.

    The window collaborator supplies the view and environment surface the
    controller calls back into: status widgets and table refreshes
    (``_set_downloads_status_widget``, ``_schedule_downloads_table_refresh``,
    ``_refresh_downloader_screen``, ``_downloads_status_state``), logging and
    status bar (``_append_downloads_log_line``, ``_push_status_message``),
    persistence and shutdown (``_save_settings``, ``_finalize_close_if_ready``),
    and catalogs/settings (``_all_download_specs``, ``_all_components_by_key``,
    ``_cached_download_versions``, ``_cached_downloads_installed_statuses``,
    ``_downloads_install_target_for_spec``, ``_downloads_dir``,
    ``_archive_credentials``, ``_shared_downloader``,
    ``parallel_downloads_spin``, ``auto_install_after_download_checkbox``,
    ``auto_resume_downloads_checkbox``). UI rendering stays in MainWindow.
    """

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.operations: dict[str, DownloadsOperationState] = {}
        self._download_threads: dict[str, QThread] = {}
        self._download_workers: dict[str, InstallWorker] = {}
        self._download_controllers: dict[str, OperationController] = {}
        self._install_key: str | None = None
        self._install_thread: QThread | None = None
        self._install_worker: InstallWorker | None = None
        self._install_controller: OperationController | None = None

    # ------------------------------------------------------------------
    # Public operation surface
    # ------------------------------------------------------------------

    def operation_status(self, component_key: str) -> str | None:
        operation = self.operations.get(component_key)
        return operation.status if operation is not None else None

    def queue_download(self, spec: ComponentSpec) -> None:
        self.operations[spec.key] = DownloadsOperationState(kind="download", status="Pending Download")
        self._window._set_downloads_status_widget(spec.key, "Pending Download", 0.0)
        self._window._schedule_downloads_table_refresh()
        self.schedule()

    def queue_install(self, spec: ComponentSpec) -> None:
        self.operations[spec.key] = DownloadsOperationState(kind="install", status="Pending Install")
        self._window._set_downloads_status_widget(spec.key, "Pending Install", 0.0)
        self._window._schedule_downloads_table_refresh()
        self.schedule()

    def toggle_row_pause(self, component_key: str) -> None:
        operation = self.operations.get(component_key)
        if operation is None:
            return
        if operation.status in {"Pending Download (Paused)", "Download Paused"}:
            operation.status = "Pending Download"
        elif operation.status == "Install Paused":
            operation.status = "Pending Install"
        elif operation.kind == "download":
            self.pause_operation(component_key, "download")
        else:
            self.pause_operation(component_key, "install")
        self._window._schedule_downloads_table_refresh()
        self.schedule()

    def pause_operation(self, component_key: str, kind: str) -> None:
        operation = self.operations.get(component_key)
        if operation is None:
            return
        if kind == "download":
            controller = self._download_controllers.get(component_key)
            if controller is None:
                operation.status = "Pending Download (Paused)"
                self._window._set_downloads_status_widget(component_key, "Pending Download (Paused)", 0.0)
                return
            operation.status = "Download Paused"
        else:
            controller = self._install_controller if self._install_key == component_key else None
            if controller is None:
                self._window._set_downloads_status_widget(component_key, "Pending Install", 0.0)
                return
            operation.status = "Install Paused"
        _, percent = self._window._downloads_status_state.get(component_key, (operation.status, 0.0))
        self._window._set_downloads_status_widget(component_key, operation.status, percent)
        controller.pause_component(component_key)

    def resume_operation(self, component_key: str) -> None:
        operation = self.operations.get(component_key)
        if operation is None:
            return
        if operation.status in {"Pending Download (Paused)", "Download Paused"}:
            operation.status = "Pending Download"
        elif operation.status == "Install Paused":
            operation.status = "Pending Install"

    def cancel_row(self, component_key: str, *, refresh: bool = True) -> None:
        operation = self.operations.pop(component_key, None)
        if operation is None:
            return
        if operation.kind == "download":
            controller = self._download_controllers.get(component_key)
        else:
            controller = self._install_controller if self._install_key == component_key else None
        if controller is not None:
            controller.skip_component(component_key)
        if refresh:
            self._window._refresh_downloader_screen()

    def cancel_active_work(self) -> None:
        """Cancel every running lane controller (used during shutdown)."""
        for controller in list(self._download_controllers.values()):
            controller.cancel()
        if self._install_controller is not None:
            self._install_controller.cancel()

    def has_active_work(self) -> bool:
        if self._install_thread is not None and self._install_thread.isRunning():
            return True
        return any(thread.isRunning() for thread in self._download_threads.values())

    def schedule(self) -> None:
        parallel_downloads = max(1, self._window.parallel_downloads_spin.value())
        for spec in self._window._all_download_specs():
            if len(self._download_threads) >= parallel_downloads:
                break
            operation = self.operations.get(spec.key)
            if operation is None or operation.status != "Pending Download":
                continue
            self._start_download_worker(spec)
        if self._install_thread is None:
            for spec in self._window._all_download_specs():
                operation = self.operations.get(spec.key)
                if operation is None or operation.status != "Pending Install":
                    continue
                self._start_install_worker(spec)
                break

    def should_auto_install(self, spec: ComponentSpec) -> bool:
        if not self._window.auto_install_after_download_checkbox.isChecked():
            return False
        if self._window._downloads_install_target_for_spec(spec) is None:
            return False
        installed_status = self._window._cached_downloads_installed_statuses.get(spec.key)
        return installed_status is None or installed_status.status != "Installed"

    def remove_partial_download(self, spec: ComponentSpec) -> None:
        archive_path = self._window._downloads_dir() / spec.cache_name
        partial_paths = {
            archive_path.with_suffix(archive_path.suffix + ".part"),
            self._window._downloads_dir() / f"{spec.cache_name}.part",
        }
        for partial_path in partial_paths:
            partial_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def serialized_operations(self) -> list[dict[str, str]]:
        serialized: list[dict[str, str]] = []
        for spec in self._window._all_download_specs():
            operation = self.operations.get(spec.key)
            if operation is None:
                continue
            status = operation.status
            if status == "Downloading":
                status = "Pending Download"
            elif status == "Installing":
                status = "Pending Install"
            if status not in PERSISTED_OPERATION_STATUSES:
                continue
            serialized.append({"component_key": spec.key, "kind": operation.kind, "status": status})
        return serialized

    def load_operations(self, settings: AppSettings) -> None:
        self.operations.clear()
        for raw_operation in settings.downloads_operations:
            component_key = raw_operation.get("component_key", "")
            spec = self._window._all_components_by_key.get(component_key)
            if spec is None:
                continue
            kind = str(raw_operation.get("kind", "")).strip()
            status = str(raw_operation.get("status", "")).strip()
            if kind not in {"download", "install"}:
                continue
            if status in {"Pending Download (Paused)", "Download Paused"} and self._window.auto_resume_downloads_checkbox.isChecked():
                status = "Pending Download"
            if status not in PERSISTED_OPERATION_STATUSES:
                continue
            self.operations[component_key] = DownloadsOperationState(kind=kind, status=status)

    def prune_operations(self) -> None:
        valid_keys = {spec.key for spec in self._window._all_download_specs()}
        for component_key in list(self.operations):
            if component_key not in valid_keys:
                self.operations.pop(component_key, None)

    # ------------------------------------------------------------------
    # Worker lanes
    # ------------------------------------------------------------------

    def _start_download_worker(self, spec: ComponentSpec) -> None:
        window = self._window
        # Downloads only need the Downloads folder. The install target is used
        # as the worker's scan root, so fall back when it is unset or points at
        # an unplugged/nonexistent drive — the installer would otherwise fail
        # the whole download trying to create/scan it.
        target_dir = window._downloads_install_target_for_spec(spec) or window._downloads_dir()
        controller = OperationController()
        installer = Installer(
            (spec,),
            cache_dir=window._downloads_dir(),
            max_parallel_downloads=1,
            downloader=window._shared_downloader,
        )
        worker = InstallWorker(
            installer=installer,
            target_dir=target_dir,
            credentials=window._archive_credentials(),
            controller=controller,
            download_only=True,
            force_component_keys={spec.key},
        )
        thread = QThread(self)
        worker.setProperty("component_key", spec.key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.component_status.connect(self._handle_download_worker_status, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(self._handle_download_worker_progress, Qt.ConnectionType.QueuedConnection)
        worker.log.connect(window._append_downloads_log_line, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._handle_download_worker_finished_report, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(self._handle_download_worker_cancelled_message, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._handle_download_worker_error_message, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        self._download_threads[spec.key] = thread
        self._download_workers[spec.key] = worker
        self._download_controllers[spec.key] = controller
        self.operations[spec.key] = DownloadsOperationState(kind="download", status="Downloading")
        window._schedule_downloads_table_refresh()
        thread.start()

    def _start_install_worker(self, spec: ComponentSpec) -> None:
        window = self._window
        target_dir = window._downloads_install_target_for_spec(spec)
        if target_dir is None:
            # No usable install folder: resolve the operation as download-only
            # instead of leaving it stuck in "Pending Install".
            self.operations.pop(spec.key, None)
            window._append_downloads_log_line(
                f"Skipped installing {spec.display_name}: no valid install folder is configured."
            )
            window._schedule_downloads_table_refresh()
            return
        controller = OperationController()
        installer = Installer(
            (spec,),
            cache_dir=window._downloads_dir(),
            max_parallel_downloads=1,
            downloader=window._shared_downloader,
        )
        worker = InstallWorker(
            installer=installer,
            target_dir=target_dir,
            credentials=window._archive_credentials(),
            controller=controller,
            download_only=False,
            force_component_keys={spec.key},
        )
        thread = QThread(self)
        worker.setProperty("component_key", spec.key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.component_status.connect(self._handle_install_worker_status, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(self._handle_install_worker_progress, Qt.ConnectionType.QueuedConnection)
        worker.log.connect(window._append_downloads_log_line, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._handle_install_worker_finished_report, Qt.ConnectionType.QueuedConnection)
        worker.cancelled.connect(self._handle_install_worker_cancelled_message, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._handle_install_worker_error_message, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        self._install_key = spec.key
        self._install_thread = thread
        self._install_worker = worker
        self._install_controller = controller
        self.operations[spec.key] = DownloadsOperationState(kind="install", status="Installing")
        window._schedule_downloads_table_refresh()
        thread.start()

    def _cleanup_download_worker(self, component_key: str) -> None:
        self._download_threads.pop(component_key, None)
        self._download_workers.pop(component_key, None)
        self._download_controllers.pop(component_key, None)

    def _cleanup_install_worker(self, component_key: str) -> None:
        if self._install_key == component_key:
            self._install_key = None
            self._install_thread = None
            self._install_worker = None
            self._install_controller = None

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    def _sender_component_key(self) -> str | None:
        sender = self.sender()
        if sender is None:
            return None
        component_key = sender.property("component_key")
        if isinstance(component_key, str) and component_key:
            return component_key
        return None

    @Slot(object)
    def _handle_download_worker_finished_report(self, report: object) -> None:
        component_key = self._sender_component_key()
        if component_key is None:
            return
        self._handle_download_worker_finished(component_key, report)

    @Slot(str)
    def _handle_download_worker_cancelled_message(self, message: str) -> None:
        component_key = self._sender_component_key()
        if component_key is None:
            return
        self._handle_download_worker_cancelled(component_key, message)

    @Slot(str)
    def _handle_download_worker_error_message(self, message: str) -> None:
        component_key = self._sender_component_key()
        if component_key is None:
            return
        self._handle_download_worker_error(component_key, message)

    @Slot(object)
    def _handle_install_worker_finished_report(self, report: object) -> None:
        component_key = self._sender_component_key()
        if component_key is None:
            return
        self._handle_install_worker_finished(component_key, report)

    @Slot(str)
    def _handle_install_worker_cancelled_message(self, message: str) -> None:
        component_key = self._sender_component_key()
        if component_key is None:
            return
        self._handle_install_worker_cancelled(component_key, message)

    @Slot(str)
    def _handle_install_worker_error_message(self, message: str) -> None:
        component_key = self._sender_component_key()
        if component_key is None:
            return
        self._handle_install_worker_error(component_key, message)

    @Slot(str, str)
    def _handle_download_worker_status(self, component_key: str, _status: str) -> None:
        operation = self.operations.get(component_key)
        if operation is None:
            return
        if operation.status != "Download Paused":
            operation.status = "Downloading"
        _, percent = self._window._downloads_status_state.get(component_key, ("Downloading", 0.0))
        self._window._set_downloads_status_widget(component_key, operation.status, percent)

    @Slot(str, str)
    def _handle_install_worker_status(self, component_key: str, _status: str) -> None:
        operation = self.operations.get(component_key)
        if operation is None:
            return
        if operation.status != "Install Paused":
            operation.status = "Installing"
        _, percent = self._window._downloads_status_state.get(component_key, ("Installing", 0.0))
        self._window._set_downloads_status_widget(component_key, operation.status, percent)

    @Slot(object)
    def _handle_download_worker_progress(self, progress: InstallProgress) -> None:
        if progress.phase == "queued":
            return
        status_text = {
            "download": "Downloading",
            "download_complete": "Downloading",
        }.get(progress.phase, "Downloading")
        current_status = self.operations.get(progress.component_key)
        if current_status is not None and current_status.status == "Download Paused":
            status_text = "Download Paused"
        self._window._set_downloads_status_widget(progress.component_key, status_text, progress.component_percent)

    @Slot(object)
    def _handle_install_worker_progress(self, progress: InstallProgress) -> None:
        if progress.phase == "queued":
            return
        status_text = {
            "download": "Downloading",
            "download_complete": "Downloading",
            "prepare": "Preparing",
            "backup": "Backing Up",
            "extract": "Installing",
            "installed": "Installing",
        }.get(progress.phase, "Installing")
        current_status = self.operations.get(progress.component_key)
        if current_status is not None and current_status.status == "Install Paused":
            status_text = "Install Paused"
        self._window._set_downloads_status_widget(progress.component_key, status_text, progress.component_percent)

    def _handle_download_worker_finished(self, component_key: str, _report: object) -> None:
        window = self._window
        operation = self.operations.get(component_key)
        self._cleanup_download_worker(component_key)
        if operation is None:
            window._refresh_downloader_screen()
            self.schedule()
            window._finalize_close_if_ready()
            return
        if operation.status == "Download Paused":
            window._set_downloads_status_widget(
                component_key, "Download Paused", window._downloads_status_state.get(component_key, ("", 0.0))[1]
            )
            window._schedule_downloads_table_refresh()
            window._save_settings()
            self.schedule()
            window._finalize_close_if_ready()
            return
        self.operations.pop(component_key, None)
        spec = window._all_components_by_key.get(component_key)
        if spec is not None:
            window._cached_download_versions[spec.key] = cached_download_version(window._downloads_dir(), spec)
            if self.should_auto_install(spec):
                self.operations[component_key] = DownloadsOperationState(kind="install", status="Pending Install")
        window._refresh_downloader_screen()
        window._save_settings()
        self.schedule()
        window._finalize_close_if_ready()

    def _handle_download_worker_cancelled(self, component_key: str, message: str) -> None:
        window = self._window
        self._cleanup_download_worker(component_key)
        self.operations.pop(component_key, None)
        spec = window._all_components_by_key.get(component_key)
        if spec is not None:
            self.remove_partial_download(spec)
            window._cached_download_versions.pop(spec.key, None)
        window._append_downloads_log_line(message)
        window._refresh_downloader_screen()
        window._save_settings()
        self.schedule()
        window._finalize_close_if_ready()

    def _handle_download_worker_error(self, component_key: str, message: str) -> None:
        window = self._window
        self._cleanup_download_worker(component_key)
        self.operations.pop(component_key, None)
        window._append_downloads_log_line(message)
        window._push_status_message(message, minimum_ms=3000)
        window._refresh_downloader_screen()
        window._save_settings()
        self.schedule()
        window._finalize_close_if_ready()

    def _handle_install_worker_finished(self, component_key: str, _report: object) -> None:
        window = self._window
        operation = self.operations.get(component_key)
        self._cleanup_install_worker(component_key)
        if operation is not None and operation.status == "Install Paused":
            window._set_downloads_status_widget(
                component_key, "Install Paused", window._downloads_status_state.get(component_key, ("", 0.0))[1]
            )
            window._schedule_downloads_table_refresh()
            window._save_settings()
            self.schedule()
            window._finalize_close_if_ready()
            return
        self.operations.pop(component_key, None)
        window._refresh_downloader_screen()
        window._save_settings()
        self.schedule()
        window._finalize_close_if_ready()

    def _handle_install_worker_cancelled(self, component_key: str, message: str) -> None:
        window = self._window
        self._cleanup_install_worker(component_key)
        self.operations.pop(component_key, None)
        window._append_downloads_log_line(message)
        window._refresh_downloader_screen()
        window._save_settings()
        self.schedule()
        window._finalize_close_if_ready()

    def _handle_install_worker_error(self, component_key: str, message: str) -> None:
        window = self._window
        self._cleanup_install_worker(component_key)
        self.operations.pop(component_key, None)
        window._append_downloads_log_line(message)
        window._push_status_message(message, minimum_ms=3000)
        window._refresh_downloader_screen()
        window._save_settings()
        self.schedule()
        window._finalize_close_if_ready()
