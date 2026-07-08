"""End-to-end Phase 2 push flow under offscreen Qt.

Drives the real CabinetTransferController (the machinery behind the Downloads
screen's Transfer to Cabinet action) against a mock cabinet that genuinely
downloads the pushed ZIP back through the companion's own LinkFileServer
(bearer-authed, over the URL the controller generates), verifies its MD5, and
reports job progress. Exercises: file-server serving + URL encoding, the MD5
hashing worker, post_job, the poll loop with job-state forwarding to the
window, and the targeted post-install component poll. Skips if Qt can't init.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import onesauce_companion.services.link_server as link_server  # noqa: E402
import onesauce_companion.ui.cabinet_transfer as cabinet_transfer  # noqa: E402
import onesauce_companion.ui.screens.cabinet_link_panel as cabinet_link_panel  # noqa: E402
from onesauce_companion.services.settings import AppSettings  # noqa: E402
from onesauce_companion.ui.cabinet_transfer import CabinetTransferController  # noqa: E402
from onesauce_companion.ui.screens.cabinet_link_panel import CabinetLinkPanel  # noqa: E402

TOKEN = "d" * 32
PAYLOAD = bytes((i % 251) for i in range(200000))
PAYLOAD_MD5 = hashlib.md5(PAYLOAD).hexdigest()


class _MockCabinet(BaseHTTPRequestHandler):
    """Cabinet that downloads a pushed job through the companion file server."""

    received: dict = {}
    jobs_state: list = []
    component_polls: list = []

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        split = urlsplit(self.path)
        if split.path == "/api/v1/info":
            self._send(200, {"app": "one_saucier", "version": "v0.0.6",
                             "device_id": "f00d", "name": "One Saucier", "tcp_port": 47655,
                             "paired": True, "drive_free": 9, "drive_total": 9})
        elif split.path == "/api/v1/components":
            stem = parse_qs(split.query).get("stem", [""])[0]
            if stem:
                # The targeted post-install status poll the companion sends
                # once a pushed job completes.
                type(self).component_polls.append(stem)
                self._send(200, {"components": [
                    {"group": "Base build", "stem": stem, "display": stem,
                     "installed": "v2.0b51"},
                ]})
            else:
                self._send(200, {"components": []})
        elif split.path == "/api/v1/jobs":
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
        self.jobs_updates: list = []
        self.log_lines: list = []
        self.cabinet_link = CabinetLinkPanel(self)

    def _save_settings(self):
        pass

    def _push_status_message(self, message):
        pass

    def _append_downloads_log_line(self, line):
        self.log_lines.append(line)

    def _on_cabinet_jobs_polled(self, jobs):
        # MainWindow mirrors job states into the Downloads table; the fake
        # just records them so the test can assert the forwarding happened.
        self.jobs_updates.append([(job.stem, job.phase) for job in jobs])


def test_push_flow_installs_on_cabinet(tmp_path, monkeypatch):
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Qt unavailable: {exc}")

    # File server must advertise a loopback URL the in-process mock can reach.
    monkeypatch.setattr(link_server, "local_ip", lambda: "127.0.0.1")

    zip_path = tmp_path / "appdata v2.0b51.zip"
    zip_path.write_bytes(PAYLOAD)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCabinet)
    _MockCabinet.received = {}
    _MockCabinet.jobs_state = []
    _MockCabinet.component_polls = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    original_client = cabinet_transfer.DeviceClient
    patched = lambda host, port=port, token="": original_client(host, port=port, token=token)  # noqa: E731
    cabinet_transfer.DeviceClient = patched
    cabinet_link_panel.DeviceClient = patched

    window = _FakeWindow(tmp_path, "127.0.0.1")
    controller = CabinetTransferController(window)
    # Ephemeral port: a running companion app on this machine holds the fixed
    # file-server port (both bind via SO_REUSEADDR and its token would 401 us).
    controller._file_server.port = 0

    assert controller.push_cached_file(zip_path) is True

    outcome = {"code": None}
    steps = {"n": 0}

    def finish(code):
        if outcome["code"] is None:
            outcome["code"] = code
            app.quit()

    def tick():
        steps["n"] += 1
        if steps["n"] > 200:  # ~20s ceiling
            finish("timeout")
            return
        # Success once the cabinet reports the install done AND the companion
        # has sent its targeted post-install component-status poll.
        jobs = _MockCabinet.jobs_state
        if jobs and jobs[0].get("phase") == 3 and _MockCabinet.component_polls:
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
        controller.dispose()
        server.shutdown()
        cabinet_transfer.DeviceClient = original_client
        cabinet_link_panel.DeviceClient = original_client

    assert outcome["code"] == "ok", f"push flow outcome: {outcome['code']}"
    assert _MockCabinet.received.get("ok") is True
    assert _MockCabinet.received.get("bytes") == len(PAYLOAD)
    assert _MockCabinet.component_polls == ["appdata"]
    # Job states were forwarded to the window (Downloads-table mirroring), and
    # the final forwarded state is the completed install.
    assert window.jobs_updates, "no job states were forwarded to the window"
    assert ("appdata", 3) in window.jobs_updates[-1]
