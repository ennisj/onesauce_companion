"""Cabinet screen: discover, pair with, and inspect a One Saucier cabinet.

Phase 1 of the companion-device link (docs/plans/companion-device-link-plan.md):
LAN discovery, PIN pairing (the cabinet displays the PIN, the user types it
here), and a live installed-components view served by the cabinet's control
API. The screen is self-contained — MainWindow only provides the settings
store, the persisted cabinet fields, and the status bar.
"""
from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.device_link import (
    DeviceClient,
    DeviceComponent,
    DeviceInfo,
    DeviceUnauthorizedError,
    PairingRejectedError,
    discover_devices,
)
from onesauce_companion.ui._utils import build_screen_header_row
from onesauce_companion.ui._worker_handle import WorkerHandle

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def _companion_name() -> str:
    try:
        return socket.gethostname() or "OnesaUCE Companion"
    except OSError:
        return "OnesaUCE Companion"


class _DiscoverWorker(QObject):
    finished = Signal(object)  # list[DeviceInfo]
    error = Signal(str)

    def __init__(self, known_hosts: list[str]) -> None:
        super().__init__()
        self._known_hosts = known_hosts

    @Slot()
    def run(self) -> None:
        try:
            devices = discover_devices(self._known_hosts)
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(devices)


class _PairStartWorker(QObject):
    finished = Signal(int)  # PIN TTL seconds
    error = Signal(str)

    def __init__(self, host: str) -> None:
        super().__init__()
        self._host = host

    @Slot()
    def run(self) -> None:
        try:
            expires = DeviceClient(self._host).pair_start(_companion_name())
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(expires)


class _PairConfirmWorker(QObject):
    finished = Signal(object)  # PairingResult
    rejected = Signal(str)
    error = Signal(str)

    def __init__(self, host: str, pin: str) -> None:
        super().__init__()
        self._host = host
        self._pin = pin

    @Slot()
    def run(self) -> None:
        try:
            result = DeviceClient(self._host).pair_confirm(self._pin, _companion_name())
        except PairingRejectedError as exc:
            self.rejected.emit(exc.reason)
            return
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(result)


class _StatusWorker(QObject):
    finished = Signal(object, object)  # DeviceInfo, list[DeviceComponent] | None
    unauthorized = Signal()
    error = Signal(str)

    def __init__(self, host: str, token: str) -> None:
        super().__init__()
        self._host = host
        self._token = token

    @Slot()
    def run(self) -> None:
        client = DeviceClient(self._host, token=self._token)
        try:
            info = client.info()
            components: list[DeviceComponent] | None = None
            if self._token:
                components = client.components()
        except DeviceUnauthorizedError:
            self.unauthorized.emit()
            return
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(info, components)


def _format_bytes(value: int) -> str:
    if value < 0:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "?"


class CabinetScreen(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window
        self._discover_handle = WorkerHandle(self)
        # Separate handles for the two pairing steps: reusing one handle while
        # its start-worker thread is still tearing down (the PIN dialog runs a
        # nested event loop during that teardown) is the kind of re-entrancy
        # that hangs the GUI. The confirm step also runs from a deferred timer,
        # off the start-worker's finished-signal stack, for the same reason.
        self._pair_start_handle = WorkerHandle(self)
        self._pair_confirm_handle = WorkerHandle(self)
        self._status_handle = WorkerHandle(self)
        self._build_ui()
        self._load_from_settings()

    # ---- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        container = QScrollArea()
        container.setWidgetResizable(True)
        container.setFrameShape(QFrame.Shape.NoFrame)
        container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(container)

        screen = QWidget()
        container.setWidget(screen)
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(18)
        layout.addWidget(build_screen_header_row("Cabinet"))

        link_group = QGroupBox("Cabinet Link")
        link_layout = QGridLayout(link_group)
        link_layout.setHorizontalSpacing(12)
        link_layout.setVerticalSpacing(10)
        link_layout.setColumnStretch(1, 1)

        self.status_label = QLabel("Not linked")
        self.status_label.setWordWrap(True)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("Cabinet IP address (or use Discover)")
        self.discover_button = QPushButton("Discover")
        self.discover_button.setMinimumWidth(150)
        self.discover_button.clicked.connect(self._start_discover)

        self.pair_button = QPushButton("Pair with Cabinet")
        self.pair_button.setMinimumWidth(150)
        self.pair_button.clicked.connect(self._start_pairing)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMinimumWidth(150)
        self.refresh_button.clicked.connect(self.refresh)
        self.unlink_button = QPushButton("Unlink")
        self.unlink_button.setMinimumWidth(150)
        self.unlink_button.clicked.connect(self._unlink)

        link_layout.addWidget(QLabel("Status"), 0, 0)
        link_layout.addWidget(self.status_label, 0, 1, 1, 2)
        link_layout.addWidget(QLabel("Cabinet IP"), 1, 0)
        link_layout.addWidget(self.host_edit, 1, 1)
        link_layout.addWidget(self.discover_button, 1, 2)
        buttons_row = QWidget()
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        buttons_layout.addWidget(self.pair_button)
        buttons_layout.addWidget(self.refresh_button)
        buttons_layout.addWidget(self.unlink_button)
        buttons_layout.addStretch(1)
        link_layout.addWidget(buttons_row, 2, 0, 1, 3)
        layout.addWidget(link_group)

        components_group = QGroupBox("Installed on Cabinet")
        components_layout = QVBoxLayout(components_group)
        self.components_note = QLabel("Pair with a cabinet to see its installed components.")
        self.components_note.setWordWrap(True)
        components_layout.addWidget(self.components_note)
        self.components_table = QTableWidget(0, 3)
        self.components_table.setHorizontalHeaderLabels(["Category", "Component", "Installed Version"])
        self.components_table.verticalHeader().setVisible(False)
        self.components_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.components_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.components_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.components_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.components_table.setMinimumHeight(420)
        components_layout.addWidget(self.components_table)
        layout.addWidget(components_group, stretch=1)
        layout.addStretch(1)

    # ---- settings plumbing ----------------------------------------------------

    def _load_from_settings(self) -> None:
        self.host_edit.setText(self._window._cabinet_host)
        self._sync_link_controls()
        if self._window._cabinet_host:
            name = self._window._cabinet_name or "One Saucier"
            self.status_label.setText(f"Linked to {name} ({self._window._cabinet_host}) — refreshing…")

    def _token(self) -> str:
        return self._window.settings_store.get_cabinet_token()

    def _paired(self) -> bool:
        return bool(self._window._cabinet_host) and bool(self._token())

    def _sync_link_controls(self) -> None:
        paired = self._paired()
        self.unlink_button.setEnabled(paired)
        self.pair_button.setText("Re-pair with Cabinet" if paired else "Pair with Cabinet")

    def _remember_cabinet(self, host: str, device_id: str, name: str) -> None:
        self._window._cabinet_host = host
        self._window._cabinet_device_id = device_id
        self._window._cabinet_name = name
        self._window._save_settings()

    # ---- discovery ------------------------------------------------------------

    def _start_discover(self) -> None:
        if self._discover_handle.running:
            return
        self.discover_button.setEnabled(False)
        self.status_label.setText("Searching the local network for cabinets…")
        known: list[str] = []
        if self.host_edit.text().strip():
            known.append(self.host_edit.text().strip())
        if self._window._cabinet_host:
            known.append(self._window._cabinet_host)
        worker = _DiscoverWorker(known)
        worker.finished.connect(self._discover_finished)
        worker.error.connect(self._discover_failed)
        self._discover_handle.start(
            worker,
            finish_signals=[worker.finished, worker.error],
            on_cleared=lambda: self.discover_button.setEnabled(True),
        )

    @Slot(object)
    def _discover_finished(self, devices: list[DeviceInfo]) -> None:
        if not devices:
            self.status_label.setText(
                "No cabinet found. Make sure One Saucier is running on the cabinet, "
                "then try again — or type the cabinet's IP address manually "
                "(shown in One Saucier's log as 'device ip')."
            )
            return
        device = devices[0]
        self.host_edit.setText(device.host)
        extra = f" (+{len(devices) - 1} more)" if len(devices) > 1 else ""
        self.status_label.setText(
            f"Found {device.label}, version {device.version}{extra}. "
            + ("Already paired with a companion." if device.paired else "Ready to pair.")
        )
        self._window._push_status_message(f"Discovered {device.label}")

    @Slot(str)
    def _discover_failed(self, message: str) -> None:
        self.status_label.setText(f"Discovery failed: {message}")

    # ---- pairing ----------------------------------------------------------------

    def _start_pairing(self) -> None:
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.information(self, "Pair with Cabinet",
                                    "Enter the cabinet's IP address (or use Discover) first.")
            return
        if self._pair_start_handle.running or self._pair_confirm_handle.running:
            return
        self.pair_button.setEnabled(False)
        self.status_label.setText(f"Requesting pairing with {host}…")
        worker = _PairStartWorker(host)
        # Defer the PIN dialog to a clean stack (QTimer.singleShot) so its nested
        # modal loop never runs inside the worker's finished-signal dispatch.
        worker.finished.connect(lambda _ttl, h=host: QTimer.singleShot(0, lambda: self._prompt_for_pin(h)))
        worker.error.connect(self._pair_failed)
        self._pair_start_handle.start(
            worker,
            finish_signals=[worker.finished, worker.error],
            on_cleared=lambda: self.pair_button.setEnabled(True),
        )

    def _prompt_for_pin(self, host: str) -> None:
        self.status_label.setText("A PIN is now shown on the cabinet screen.")
        pin, accepted = QInputDialog.getText(
            self,
            "Pair with Cabinet",
            "Enter the 6-digit PIN shown on the cabinet:",
            QLineEdit.EchoMode.Normal,
        )
        pin = (pin or "").strip()
        if not accepted or not pin:
            self.status_label.setText("Pairing cancelled.")
            return
        self.status_label.setText("Verifying PIN with the cabinet…")
        worker = _PairConfirmWorker(host, pin)
        worker.finished.connect(lambda result, h=host: self._pair_succeeded(h, result))
        worker.rejected.connect(self._pair_rejected)
        worker.error.connect(self._pair_failed)
        self._pair_confirm_handle.start(
            worker,
            finish_signals=[worker.finished, worker.rejected, worker.error],
            on_cleared=lambda: self.pair_button.setEnabled(True),
        )

    def _pair_succeeded(self, host: str, result: object) -> None:
        token = getattr(result, "token", "")
        device_id = getattr(result, "device_id", "")
        name = getattr(result, "name", "One Saucier")
        if not self._window.settings_store.set_cabinet_token(token):
            self.status_label.setText(
                "Paired, but the link token could not be stored in the system keyring."
            )
            return
        self._remember_cabinet(host, device_id, name)
        self._sync_link_controls()
        self.status_label.setText(f"Linked to {name} ({host}).")
        self._window._push_status_message(f"Paired with {name} ({host})")
        self.refresh()

    @Slot(str)
    def _pair_rejected(self, reason: str) -> None:
        messages = {
            "bad_pin": "The PIN did not match. Start pairing again and re-check the cabinet screen.",
            "expired": "The PIN expired. Start pairing again.",
            "no_pairing": "The cabinet is not in pairing mode (it may have been cancelled on the cabinet).",
            "too_many_attempts": "Too many wrong PINs — start pairing again.",
        }
        self.status_label.setText(messages.get(reason, f"Pairing rejected: {reason}"))

    @Slot(str)
    def _pair_failed(self, message: str) -> None:
        self.status_label.setText(f"Pairing failed: {message}")

    def _unlink(self) -> None:
        name = self._window._cabinet_name or "the cabinet"
        confirm = QMessageBox.question(
            self,
            "Unlink Cabinet",
            f"Forget the link with {name}? You can pair again at any time.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._window.settings_store.delete_cabinet_token()
        self._remember_cabinet("", "", "")
        self._sync_link_controls()
        self.components_table.setRowCount(0)
        self.components_note.setText("Pair with a cabinet to see its installed components.")
        self.components_note.show()
        self.status_label.setText("Not linked")
        self._window._push_status_message("Cabinet unlinked")

    # ---- status / components refresh ---------------------------------------------

    def refresh(self) -> None:
        host = self.host_edit.text().strip() or self._window._cabinet_host
        if not host:
            self.status_label.setText("Not linked — use Discover or enter the cabinet's IP address.")
            return
        if self._status_handle.running:
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText(f"Contacting {host}…")
        worker = _StatusWorker(host, self._token() if host == self._window._cabinet_host else "")
        worker.finished.connect(lambda info, comps, h=host: self._status_ready(h, info, comps))
        worker.unauthorized.connect(self._status_unauthorized)
        worker.error.connect(self._status_failed)
        self._status_handle.start(
            worker,
            finish_signals=[worker.finished, worker.unauthorized, worker.error],
            on_cleared=lambda: self.refresh_button.setEnabled(True),
        )

    def _status_ready(self, host: str, info: DeviceInfo, components: object) -> None:
        free = _format_bytes(info.drive_free)
        total = _format_bytes(info.drive_total)
        linked = self._paired() and host == self._window._cabinet_host
        state = "Linked to" if linked else "Found"
        self.status_label.setText(
            f"{state} {info.label} — One Saucier {info.version}, drive {free} free of {total}."
        )
        self._sync_link_controls()
        if not isinstance(components, list):
            self.components_table.setRowCount(0)
            self.components_note.setText(
                "Pair with this cabinet to see its installed components."
            )
            self.components_note.show()
            return
        self._populate_components(components)

    def _populate_components(self, components: list[DeviceComponent]) -> None:
        installed = [c for c in components if c.installed]
        self.components_note.setText(
            f"{len(installed)} of {len(components)} catalog components installed."
        )
        self.components_table.setRowCount(len(components))
        for row, component in enumerate(
            sorted(components, key=lambda c: (c.group, c.display.lower()))
        ):
            version = component.installed or "Not installed"
            if version == "installed":
                version = "Installed (version unknown)"
            for column, text in enumerate((component.group, component.display, version)):
                item = QTableWidgetItem(text)
                if not component.installed:
                    item.setForeground(Qt.GlobalColor.gray)
                self.components_table.setItem(row, column, item)

    @Slot()
    def _status_unauthorized(self) -> None:
        self.status_label.setText(
            "The cabinet rejected the stored link token (it may have been unlinked "
            "on the cabinet). Pair again to reconnect."
        )
        self._window.settings_store.delete_cabinet_token()
        self._sync_link_controls()

    @Slot(str)
    def _status_failed(self, message: str) -> None:
        self.status_label.setText(f"Cabinet unreachable: {message}")
