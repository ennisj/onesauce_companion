from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from onesauce_companion.services.archive_org import ArchiveOrgCredentials, authenticate
from onesauce_companion.services.control import OperationCancelledError, OperationController
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
    ) -> None:
        super().__init__()
        self.installer = installer
        self.target_dir = target_dir
        self.credentials = credentials
        self.controller = controller

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
