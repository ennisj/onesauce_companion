"""Cabinet Link panel: discover, pair with, and unlink a One Saucier cabinet.

Shown on the Settings screen (below Local Folders). Owns LAN discovery, PIN
pairing, unlinking, and the status refresh against the cabinet's control API.
The Cabinet screen consumes this panel's signals: `components_received` for
the installed-components list a status refresh returns, and
`link_state_changed` when pairing state changes (paired/unlinked/revoked).
"""
from __future__ import annotations

import socket
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
from onesauce_companion.ui._worker_handle import WorkerHandle

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def _companion_name() -> str:
    try:
        return socket.gethostname() or "OnesaUCE Companion"
    except OSError:
        return "OnesaUCE Companion"


def format_bytes(value: int) -> str:
    if value < 0:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "?"


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


class _ComponentWorker(QObject):
    """Targeted single-component status read (GET /components?stem=...)."""

    finished = Signal(object)  # list[DeviceComponent] (0 or 1 entries)
    unauthorized = Signal()
    error = Signal(str)

    def __init__(self, host: str, token: str, stem: str) -> None:
        super().__init__()
        self._host = host
        self._token = token
        self._stem = stem

    @Slot()
    def run(self) -> None:
        try:
            components = DeviceClient(self._host, token=self._token).components(stem=self._stem)
        except DeviceUnauthorizedError:
            self.unauthorized.emit()
            return
        except Exception as exc:  # pragma: no cover - surfaced to the UI
            self.error.emit(str(exc))
            return
        self.finished.emit(components)


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


class CabinetLinkPanel(QGroupBox):
    """Settings-screen group box that manages the companion↔cabinet link."""

    components_received = Signal(object)  # list[DeviceComponent] | None
    component_updated = Signal(object)  # one DeviceComponent (targeted poll result)
    link_state_changed = Signal()
    refresh_failed = Signal(str)  # a status refresh could not reach the cabinet

    def __init__(self, window: "MainWindow") -> None:
        super().__init__("Cabinet Link")
        self._window = window
        self._discover_handle = WorkerHandle(self)
        # Separate handles for the two pairing steps: reusing one handle while
        # its start-worker thread is still tearing down is the kind of
        # re-entrancy that hangs the GUI. The confirm step also runs from a
        # deferred timer, off the start-worker's finished-signal stack, for
        # the same reason.
        self._pair_start_handle = WorkerHandle(self)
        self._pair_confirm_handle = WorkerHandle(self)
        self._status_handle = WorkerHandle(self)
        self._component_handle = WorkerHandle(self)
        self._pending_component_stems: list[str] = []
        self._pairing_host = ""
        self._build_ui()

    # ---- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        link_layout = QGridLayout(self)
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

        # Inline PIN entry (shown only while a pairing PIN is on the cabinet).
        # Deliberately NOT a modal QInputDialog: a modal spins a nested event
        # loop, which on Windows froze the app when opened from this worker/
        # signal flow. An inline row keeps everything on the normal event loop.
        self.pin_row = QWidget()
        pin_layout = QHBoxLayout(self.pin_row)
        pin_layout.setContentsMargins(0, 0, 0, 0)
        pin_layout.setSpacing(12)
        self.pin_edit = QLineEdit()
        self.pin_edit.setPlaceholderText("6-digit PIN from the cabinet")
        self.pin_edit.setMaxLength(6)
        self.pin_edit.returnPressed.connect(self._confirm_pin)
        self.pin_confirm_button = QPushButton("Confirm PIN")
        self.pin_confirm_button.setMinimumWidth(150)
        self.pin_confirm_button.clicked.connect(self._confirm_pin)
        self.pin_cancel_button = QPushButton("Cancel")
        self.pin_cancel_button.setMinimumWidth(110)
        self.pin_cancel_button.clicked.connect(self._cancel_pin)
        pin_layout.addWidget(QLabel("Enter PIN"))
        pin_layout.addWidget(self.pin_edit, 1)
        pin_layout.addWidget(self.pin_confirm_button)
        pin_layout.addWidget(self.pin_cancel_button)
        self.pin_row.hide()
        link_layout.addWidget(self.pin_row, 3, 0, 1, 3)

    # ---- settings plumbing ----------------------------------------------------

    def load_from_settings(self) -> None:
        self.host_edit.setText(self._window._cabinet_host)
        self._sync_link_controls()
        if self._window._cabinet_host:
            name = self._window._cabinet_name or "One Saucier"
            self.status_label.setText(f"Linked to {name} ({self._window._cabinet_host}).")

    def _token(self) -> str:
        return self._window.settings_store.get_cabinet_token()

    def paired(self) -> bool:
        return bool(self._window._cabinet_host) and bool(self._token())

    def _sync_link_controls(self) -> None:
        paired = self.paired()
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
        self._pairing_host = host
        self.pair_button.setEnabled(False)
        self.pin_row.hide()
        self.status_label.setText(f"Requesting pairing with {host}…")
        worker = _PairStartWorker(host)
        worker.finished.connect(self._show_pin_entry)
        worker.error.connect(self._pair_failed)
        self._pair_start_handle.start(
            worker,
            finish_signals=[worker.finished, worker.error],
            on_cleared=lambda: self.pair_button.setEnabled(True),
        )

    @Slot(int)
    def _show_pin_entry(self, _ttl: int) -> None:
        # Reveal the inline PIN row (no modal). Runs on the GUI thread via a
        # normal queued signal — no nested event loop, so it can't freeze.
        self.status_label.setText("Enter the PIN shown on the cabinet screen, then Confirm PIN.")
        self.pin_edit.clear()
        self.pin_row.show()
        self.pin_edit.setFocus()

    def _cancel_pin(self) -> None:
        self.pin_row.hide()
        self.status_label.setText("Pairing cancelled.")

    def _confirm_pin(self) -> None:
        pin = self.pin_edit.text().strip()
        if not pin:
            self.status_label.setText("Enter the PIN shown on the cabinet, then Confirm PIN.")
            self.pin_edit.setFocus()
            return
        if self._pair_confirm_handle.running:
            return
        host = self._pairing_host
        self.pin_row.hide()
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
        self.link_state_changed.emit()
        self.refresh()

    @Slot(str)
    def _pair_rejected(self, reason: str) -> None:
        messages = {
            "bad_pin": "The PIN did not match — re-check the cabinet screen and enter it again.",
            "expired": "The PIN expired. Start pairing again.",
            "no_pairing": "The cabinet is not in pairing mode (it may have been cancelled on the cabinet).",
            "too_many_attempts": "Too many wrong PINs — start pairing again.",
        }
        self.status_label.setText(messages.get(reason, f"Pairing rejected: {reason}"))
        # A wrong PIN keeps the cabinet's pairing session open, so let the user
        # retry inline; other reasons require restarting from the Pair button.
        if reason == "bad_pin":
            self.pin_edit.clear()
            self.pin_row.show()
            self.pin_edit.setFocus()

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
        self.status_label.setText("Not linked")
        self._window._push_status_message("Cabinet unlinked")
        self.link_state_changed.emit()

    # ---- status refresh ---------------------------------------------------------

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
        free = format_bytes(info.drive_free)
        total = format_bytes(info.drive_total)
        linked = self.paired() and host == self._window._cabinet_host
        state = "Linked to" if linked else "Found"
        self.status_label.setText(
            f"{state} {info.label} — One Saucier {info.version}, drive {free} free of {total}."
        )
        self._sync_link_controls()
        self.components_received.emit(components if isinstance(components, list) else None)

    # ---- targeted single-component status polls ----------------------------------

    def refresh_component(self, stem: str) -> None:
        """Poll one component's cabinet status (cheap targeted read).

        Used after a pushed install completes so the companion converges on
        the new installed version without asking the cabinet for a full drive
        scan. Results arrive via the ``component_updated`` signal; stems queue
        up if a poll is already in flight.
        """
        if not stem or not self.paired():
            return
        if stem not in self._pending_component_stems:
            self._pending_component_stems.append(stem)
        self._start_next_component_poll()

    def _start_next_component_poll(self) -> None:
        if self._component_handle.running or not self._pending_component_stems:
            return
        stem = self._pending_component_stems.pop(0)
        worker = _ComponentWorker(self._window._cabinet_host, self._token(), stem)
        worker.finished.connect(self._component_ready)
        worker.unauthorized.connect(self._status_unauthorized)
        worker.error.connect(self.refresh_failed)
        self._component_handle.start(
            worker,
            finish_signals=[worker.finished, worker.unauthorized, worker.error],
            on_cleared=self._start_next_component_poll,
        )

    @Slot(object)
    def _component_ready(self, components: object) -> None:
        if isinstance(components, list):
            for component in components:
                self.component_updated.emit(component)

    @Slot()
    def _status_unauthorized(self) -> None:
        self.status_label.setText(
            "The cabinet rejected the stored link token (it may have been unlinked "
            "on the cabinet). Pair again to reconnect."
        )
        self._window.settings_store.delete_cabinet_token()
        self._sync_link_controls()
        self.link_state_changed.emit()

    @Slot(str)
    def _status_failed(self, message: str) -> None:
        self.status_label.setText(f"Cabinet unreachable: {message}")
        self.refresh_failed.emit(message)
