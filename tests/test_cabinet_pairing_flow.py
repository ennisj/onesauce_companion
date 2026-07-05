"""End-to-end CabinetScreen pairing flow under an offscreen Qt event loop.

Guards the regression where the PIN entry (previously a modal QInputDialog)
froze the app when opened from the pairing worker's signal flow. This drives
the real screen against a mock cabinet through a live event loop and asserts
the inline-PIN flow reaches "Linked" without hanging.

Skips cleanly if a Qt platform plugin cannot be initialized (headless CI
without offscreen support).
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import onesauce_companion.ui.screens.cabinet_screen as cabinet_screen  # noqa: E402
from onesauce_companion.ui.screens.cabinet_screen import CabinetScreen  # noqa: E402

TOKEN = "b" * 32
PIN = "246813"


class _MockCabinet(BaseHTTPRequestHandler):
    pairing_active = False

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/v1/info":
            self._send(200, {"app": "one_saucier", "proto": 1, "version": "v0.0.5",
                             "device_id": "deadbeefdeadbeef", "name": "One Saucier",
                             "ip": "127.0.0.1", "tcp_port": self.server.server_port,
                             "paired": True, "drive_free": 5_000_000, "drive_total": 9_000_000})
        elif self.path == "/api/v1/components":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._send(401, {"error": "unauthorized"})
                return
            self._send(200, {"components": [
                {"group": "Base build", "stem": "appdata", "display": "appdata", "installed": "v2.0b51"},
                {"group": "Game packs", "stem": "Atari2600", "display": "Atari 2600", "installed": ""},
            ]})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/v1/pair":
            _MockCabinet.pairing_active = True
            self._send(200, {"status": "pin_required", "expires_in": 120})
        elif self.path == "/api/v1/pair/confirm":
            if not _MockCabinet.pairing_active or body.get("pin") != PIN:
                self._send(403, {"error": "bad_pin"})
                return
            _MockCabinet.pairing_active = False
            self._send(200, {"token": TOKEN, "device_id": "deadbeefdeadbeef", "name": "One Saucier"})
        else:
            self._send(404, {"error": "not_found"})

    def log_message(self, format, *args):  # noqa: A002 - silence test output
        pass


class _FakeSettingsStore:
    def __init__(self):
        self._token = ""

    def get_cabinet_token(self):
        return self._token

    def set_cabinet_token(self, token):
        self._token = token
        return True

    def delete_cabinet_token(self):
        self._token = ""


class _FakeWindow:
    def __init__(self):
        self.settings_store = _FakeSettingsStore()
        self._cabinet_host = ""
        self._cabinet_device_id = ""
        self._cabinet_name = ""

    def _save_settings(self):
        pass

    def _push_status_message(self, message):
        pass


def test_inline_pin_pairing_flow_completes_without_freezing():
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover - headless without offscreen
        pytest.skip(f"Qt platform unavailable: {exc}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCabinet)
    _MockCabinet.pairing_active = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port

    # Workers build DeviceClient(host) with the default control port; point them
    # at the mock server's ephemeral port.
    original_client = cabinet_screen.DeviceClient
    cabinet_screen.DeviceClient = lambda host, port=port, token="": original_client(
        host, port=port, token=token
    )

    window = _FakeWindow()
    screen = CabinetScreen(window)
    screen.host_edit.setText("127.0.0.1")

    outcome: dict[str, object] = {"code": None, "msg": ""}
    steps = {"n": 0, "confirmed": False}

    def finish(code, msg):
        if outcome["code"] is None:
            outcome["code"] = code
            outcome["msg"] = msg
            app.quit()

    def tick():
        steps["n"] += 1
        status = screen.status_label.text()
        if steps["n"] > 150:  # ~15s hard ceiling
            finish("timeout", f"last status {status!r}")
            return
        if steps["n"] == 2:
            screen._start_pairing()
            return
        if (not screen.pin_row.isHidden()) and not steps["confirmed"]:
            steps["confirmed"] = True
            screen.pin_edit.setText(PIN)
            screen._confirm_pin()
            return
        if "Linked to" in status and screen.components_table.rowCount() > 0:
            finish("ok", status)
            return
        if any(word in status.lower() for word in ("rejected", "failed", "unreachable")):
            finish("error", status)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    try:
        app.exec()
    finally:
        timer.stop()
        server.shutdown()
        cabinet_screen.DeviceClient = original_client
        screen.deleteLater()

    assert outcome["code"] == "ok", f"pairing flow did not complete: {outcome['msg']}"
    assert window.settings_store.get_cabinet_token() == TOKEN
    assert screen.components_table.rowCount() == 2
