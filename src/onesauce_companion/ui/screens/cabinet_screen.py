"""Cabinet screen: discover, pair with, inspect, and update a One Saucier cabinet.

Phase 1 (docs/plans/companion-device-link-plan.md): LAN discovery, PIN pairing,
and a live installed-components view served by the cabinet's control API.
Phase 2: push a cached component ZIP to the cabinet — the companion serves it
over its token-gated file server and the cabinet installs it through its own
download->verify->extract pipeline, with progress polled back here. The screen
is self-contained — MainWindow provides the settings store, the persisted
cabinet fields, and the status bar.
"""
from __future__ import annotations

import hashlib
import socket
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
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
    DeviceJob,
    DeviceUnauthorizedError,
    PairingRejectedError,
    discover_devices,
)
from onesauce_companion.services.download_cache import default_downloads_dir
from onesauce_companion.services.link_server import LinkFileServer
from onesauce_companion.services.versioning import parse_version_from_filename
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
        self._push_handle = WorkerHandle(self)
        self._jobs_poll_handle = WorkerHandle(self)
        self._pairing_host = ""
        self._cabinet_component_groups: dict[str, str] = {}
        # Phase 2: the file server that streams cached ZIPs to the cabinet, and a
        # poll timer that tracks remote install progress while jobs are active.
        self._file_server = LinkFileServer(self._resolve_cached_file, self._token)
        self._jobs_timer = QTimer(self)
        self._jobs_timer.setInterval(1500)
        self._jobs_timer.timeout.connect(self._poll_jobs)
        self._build_ui()
        self._load_from_settings()

    def dispose(self) -> None:
        """Stop the file server + poll timer (called when the app closes)."""
        self._jobs_timer.stop()
        self._file_server.stop()

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
        self.components_table.setMinimumHeight(280)
        components_layout.addWidget(self.components_table)
        layout.addWidget(components_group, stretch=1)

        # ---- Phase 2: push a cached component ZIP to the cabinet ----
        push_group = QGroupBox("Send a Component to the Cabinet")
        push_layout = QVBoxLayout(push_group)
        self.push_note = QLabel(
            "Components you have downloaded on this PC (Downloads screen) can be "
            "installed on the paired cabinet over the network."
        )
        self.push_note.setWordWrap(True)
        push_layout.addWidget(self.push_note)

        self.push_table = QTableWidget(0, 3)
        self.push_table.setHorizontalHeaderLabels(["Cached Component", "Version", "Size"])
        self.push_table.verticalHeader().setVisible(False)
        self.push_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.push_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.push_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        push_header = self.push_table.horizontalHeader()
        push_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        push_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        push_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.push_table.setMinimumHeight(180)
        self.push_table.itemSelectionChanged.connect(self._sync_push_controls)
        push_layout.addWidget(self.push_table)

        push_buttons = QHBoxLayout()
        push_buttons.setContentsMargins(0, 0, 0, 0)
        self.push_refresh_button = QPushButton("Refresh List")
        self.push_refresh_button.setMinimumWidth(150)
        self.push_refresh_button.clicked.connect(self._refresh_cached_files)
        self.install_on_cabinet_button = QPushButton("Install on Cabinet")
        self.install_on_cabinet_button.setMinimumWidth(180)
        self.install_on_cabinet_button.clicked.connect(self._install_selected_on_cabinet)
        push_buttons.addWidget(self.push_refresh_button)
        push_buttons.addWidget(self.install_on_cabinet_button)
        push_buttons.addStretch(1)
        push_layout.addLayout(push_buttons)

        self.jobs_label = QLabel("")
        self.jobs_label.setWordWrap(True)
        self.jobs_label.hide()
        push_layout.addWidget(self.jobs_label)
        self.jobs_progress = QProgressBar()
        self.jobs_progress.setTextVisible(True)
        self.jobs_progress.hide()
        push_layout.addWidget(self.jobs_progress)

        layout.addWidget(push_group, stretch=1)
        layout.addStretch(1)

    # ---- settings plumbing ----------------------------------------------------

    def _load_from_settings(self) -> None:
        self.host_edit.setText(self._window._cabinet_host)
        self._sync_link_controls()
        self._refresh_cached_files()
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
        self._sync_push_controls()

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
        self._cabinet_component_groups = {c.stem: c.group for c in components if c.stem}
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

    # ---- Phase 2: push cached components to the cabinet -------------------------

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

    @staticmethod
    def _parse_cached(name: str) -> tuple[str, str]:
        version = parse_version_from_filename(name) or ""
        stem = name[:-4] if name.lower().endswith(".zip") else name
        if version and stem.endswith(" " + version):
            stem = stem[: -(len(version) + 1)]
        return stem.strip(), version

    def _refresh_cached_files(self) -> None:
        downloads = self._downloads_dir()
        files = sorted(downloads.glob("*.zip")) if downloads.is_dir() else []
        self.push_table.setRowCount(len(files))
        for row, path in enumerate(files):
            stem, version = self._parse_cached(path.name)
            size = _format_bytes(path.stat().st_size)
            cells = (path.name, version or "—", size)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.push_table.setItem(row, column, item)
        if not files:
            self.push_note.setText(
                f"No cached components in {downloads}. Download components on the "
                "Downloads screen first, then refresh this list."
            )
        else:
            self.push_note.setText(
                "Select a component and choose Install on Cabinet to send it over "
                "the network. The cabinet downloads, verifies, and installs it."
            )
        self._sync_push_controls()

    def _sync_push_controls(self) -> None:
        can_push = self._paired() and self.push_table.currentRow() >= 0 and not self._push_handle.running
        self.install_on_cabinet_button.setEnabled(bool(can_push))

    def _selected_cached_path(self) -> Path | None:
        row = self.push_table.currentRow()
        if row < 0:
            return None
        item = self.push_table.item(row, 0)
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return Path(str(raw)) if raw else None

    def _install_selected_on_cabinet(self) -> None:
        if not self._paired():
            QMessageBox.information(self, "Install on Cabinet",
                                    "Pair with a cabinet first.")
            return
        path = self._selected_cached_path()
        if path is None or not path.is_file():
            QMessageBox.information(self, "Install on Cabinet",
                                    "Select a cached component to send.")
            return
        if self._push_handle.running:
            return
        host = self._window._cabinet_host
        stem, version = self._parse_cached(path.name)
        display = stem or path.name
        group = self._cabinet_component_groups.get(stem, "")
        try:
            self._file_server.start()
        except OSError as exc:
            self.jobs_label.setText(f"Could not start the file server: {exc}")
            self.jobs_label.show()
            return
        file_url = self._file_server.file_url(path.name)
        self.install_on_cabinet_button.setEnabled(False)
        self.jobs_label.setText(f"Preparing {display} (hashing {path.name})…")
        self.jobs_label.show()
        self.jobs_progress.hide()
        worker = _PushJobWorker(host, self._token(), path, file_url,
                                stem, display, group, version)
        worker.finished.connect(self._on_push_posted)
        worker.error.connect(self._on_push_failed)
        self._push_handle.start(
            worker,
            finish_signals=[worker.finished, worker.error],
            on_cleared=self._sync_push_controls,
        )

    @Slot(str)
    def _on_push_posted(self, stem: str) -> None:
        self.jobs_label.setText("Install requested — the cabinet is downloading…")
        self._window._push_status_message(f"Sent {stem} to the cabinet")
        if not self._jobs_timer.isActive():
            self._jobs_timer.start()
        self._poll_jobs()

    @Slot(str)
    def _on_push_failed(self, message: str) -> None:
        self.jobs_label.setText(f"Could not start the install: {message}")
        self.jobs_progress.hide()

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
        active = [j for j in jobs if isinstance(j, DeviceJob) and not j.is_terminal]
        lines = []
        for job in jobs:
            if not isinstance(job, DeviceJob):
                continue
            if job.phase == 1 and job.total > 0:
                detail = f"{_format_bytes(job.got)} / {_format_bytes(job.total)}"
            else:
                detail = job.message or ""
            lines.append(f"{job.display}: {job.phase_label}"
                         + (f" — {detail}" if detail else ""))
        self.jobs_label.setText("\n".join(lines))
        self.jobs_label.show()
        if active:
            lead = active[0]
            self.jobs_progress.setRange(0, 100)
            self.jobs_progress.setValue(int(lead.fraction * 100))
            self.jobs_progress.setFormat(f"{lead.display} — {lead.phase_label} %p%")
            self.jobs_progress.show()
            if not self._jobs_timer.isActive():
                self._jobs_timer.start()
        else:
            self.jobs_progress.hide()
            self._jobs_timer.stop()
            self._window._push_status_message("Cabinet install finished")
            self.refresh()  # refresh the installed-components view

    @Slot(str)
    def _on_jobs_poll_failed(self, message: str) -> None:
        # Transient poll failure: keep the timer running for the next tick.
        pass
