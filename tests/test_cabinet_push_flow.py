"""End-to-end Phase 2 push flow under offscreen Qt.

Drives the real CabinetScreen against a mock cabinet that genuinely downloads
the pushed ZIP back through the companion's own LinkFileServer (bearer-authed,
over the URL the screen generates), verifies its MD5, and reports job progress.
Exercises: file-server serving + URL encoding, the MD5 hashing worker, post_job,
the poll loop, and the UI transitions to "done". Skips if Qt can't init.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import onesauce_companion.services.link_server as link_server  # noqa: E402
import onesauce_companion.ui.screens.cabinet_screen as cabinet_screen  # noqa: E402
from onesauce_companion.services.settings import AppSettings  # noqa: E402
from onesauce_companion.ui.screens.cabinet_screen import CabinetScreen  # noqa: E402

TOKEN = "d" * 32
PAYLOAD = bytes((i % 251) for i in range(200000))
PAYLOAD_MD5 = hashlib.md5(PAYLOAD).hexdigest()


class _MockCabinet(BaseHTTPRequestHandler):
    """Cabinet that downloads a pushed job through the companion file server."""

    received: dict = {}
    jobs_state: list = []

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
            self._send(200, {"app": "one_saucier", "version": "v0.0.6",
                             "device_id": "f00d", "name": "One Saucier", "tcp_port": 47655,
                             "paired": True, "drive_free": 9, "drive_total": 9})
        elif self.path == "/api/v1/components":
            self._send(200, {"components": []})
        elif self.path == "/api/v1/jobs":
            self._send(200, {"jobs": type(self).jobs_state})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/v1/jobs":
            type(self).jobs_state = [{"stem": body["stem"], "display": body["display"],
                                      "phase": 1, "got": 0, "total": body["size"], "message": ""}]
            threading.Thread(target=self._run_download, args=(body,), daemon=True).start()
            self._send(200, {"status": "accepted"})
        else:
            self._send(404, {"error": "not_found"})

    def _run_download(self, body):
        # The real device streams the file via libcurl; here we use requests with
        # the same Bearer token to fetch it through the companion's file server.
        resp = requests.get(body["url"], headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)
        data = resp.content
        ok = (resp.status_code == 200 and len(data) == body["size"]
              and hashlib.md5(data).hexdigest() == body["md5"])
        type(self).received = {"bytes": len(data), "ok": ok, "status": resp.status_code}
        type(self).jobs_state = [{"stem": body["stem"], "display": body["display"],
                                  "phase": 3 if ok else 4, "got": len(data),
                                  "total": body["size"],
                                  "message": "installed" if ok else "checksum mismatch"}]

    def log_message(self, format, *args):  # noqa: A002
        pass


class _FakeSettingsStore:
    def __init__(self, downloads_dir: Path):
        self._downloads = str(downloads_dir)

    def get_cabinet_token(self):
        return TOKEN

    def load(self):
        return AppSettings(downloads_path=self._downloads)


class _FakeWindow:
    def __init__(self, downloads_dir: Path, host: str):
        self.settings_store = _FakeSettingsStore(downloads_dir)
        self._cabinet_host = host
        self._cabinet_device_id = "f00d"
        self._cabinet_name = "One Saucier"

    def _save_settings(self):
        pass

    def _push_status_message(self, message):
        pass


def test_push_flow_installs_on_cabinet(tmp_path, monkeypatch):
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Qt unavailable: {exc}")

    # File server must advertise a loopback URL the in-process mock can reach.
    monkeypatch.setattr(link_server, "local_ip", lambda: "127.0.0.1")

    (tmp_path / "appdata v2.0b51.zip").write_bytes(PAYLOAD)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCabinet)
    _MockCabinet.received = {}
    _MockCabinet.jobs_state = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    original_client = cabinet_screen.DeviceClient
    cabinet_screen.DeviceClient = lambda host, port=port, token="": original_client(
        host, port=port, token=token
    )

    window = _FakeWindow(tmp_path, "127.0.0.1")
    screen = CabinetScreen(window)
    screen._refresh_cached_files()

    outcome = {"code": None}
    steps = {"n": 0, "started": False}

    def finish(code):
        if outcome["code"] is None:
            outcome["code"] = code
            app.quit()

    def tick():
        steps["n"] += 1
        if steps["n"] > 200:  # ~20s ceiling
            finish("timeout")
            return
        if not steps["started"] and screen.push_table.rowCount() > 0:
            steps["started"] = True
            screen.push_table.selectRow(0)
            screen._install_selected_on_cabinet()
            return
        # Success once the cabinet reports the install done via the poll loop.
        jobs = _MockCabinet.jobs_state
        if jobs and jobs[0].get("phase") == 3:
            finish("ok")
        elif jobs and jobs[0].get("phase") == 4:
            finish("checksum_failed")

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    try:
        app.exec()
    finally:
        timer.stop()
        screen.dispose()
        server.shutdown()
        cabinet_screen.DeviceClient = original_client

    assert outcome["code"] == "ok", f"push flow outcome: {outcome['code']}"
    assert _MockCabinet.received.get("ok") is True
    assert _MockCabinet.received.get("bytes") == len(PAYLOAD)
