"""DeviceClient protocol tests against a mock One Saucier control server.

The mock speaks the exact wire format of the device-side link service
(onesauce_dl ``app/link_service.cpp``): JSON over HTTP/1.1, bearer-token auth
on /components, PIN-gated two-step pairing. If either side's format drifts,
these tests are the early warning.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from onesauce_companion.services.device_link import (
    DeviceClient,
    DeviceLinkError,
    DeviceUnauthorizedError,
    PairingRejectedError,
)

TOKEN = "a" * 32
PIN = "483920"


class _MockCabinet(BaseHTTPRequestHandler):
    pairing_active = False

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/info":
            self._send(200, {
                "app": "one_saucier", "proto": 1, "version": "v0.0.5",
                "device_id": "cafe1234cafe1234", "name": "One Saucier",
                "ip": "127.0.0.1", "tcp_port": self.server.server_port,
                "paired": True, "drive_free": 1000, "drive_total": 2000,
            })
            return
        if self.path == "/api/v1/components":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._send(401, {"error": "unauthorized"})
                return
            self._send(200, {"components": [
                {"group": "Base build", "stem": "appdata", "display": "appdata",
                 "installed": "v2.0b51"},
                {"group": "Game packs", "stem": "Atari2600", "display": "Atari 2600",
                 "installed": ""},
            ]})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/v1/pair":
            type(self).pairing_active = True
            self._send(200, {"status": "pin_required", "expires_in": 120})
            return
        if self.path == "/api/v1/pair/confirm":
            if not type(self).pairing_active:
                self._send(403, {"error": "no_pairing"})
                return
            if body.get("pin") != PIN:
                self._send(403, {"error": "bad_pin"})
                return
            type(self).pairing_active = False
            self._send(200, {"token": TOKEN, "device_id": "cafe1234cafe1234",
                             "name": "One Saucier"})
            return
        self._send(404, {"error": "not_found"})

    def log_message(self, *args) -> None:  # silence test output
        pass


@pytest.fixture()
def cabinet():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCabinet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _MockCabinet.pairing_active = False
    try:
        yield DeviceClient("127.0.0.1", port=server.server_port)
    finally:
        server.shutdown()


def test_info(cabinet: DeviceClient) -> None:
    info = cabinet.info()
    assert info.name == "One Saucier"
    assert info.version == "v0.0.5"
    assert info.device_id == "cafe1234cafe1234"
    assert info.paired is True
    assert info.drive_free == 1000
    assert info.drive_total == 2000
    assert info.label == "One Saucier (127.0.0.1)"


def test_pair_flow(cabinet: DeviceClient) -> None:
    assert cabinet.pair_start("test-pc") == 120
    result = cabinet.pair_confirm(PIN, "test-pc")
    assert result.token == TOKEN
    assert result.device_id == "cafe1234cafe1234"
    # The client adopts the token, so authed calls now succeed.
    components = cabinet.components()
    assert [c.stem for c in components] == ["appdata", "Atari2600"]
    assert components[0].installed == "v2.0b51"
    assert components[1].installed == ""


def test_pair_wrong_pin(cabinet: DeviceClient) -> None:
    cabinet.pair_start("test-pc")
    with pytest.raises(PairingRejectedError) as excinfo:
        cabinet.pair_confirm("000000", "test-pc")
    assert excinfo.value.reason == "bad_pin"


def test_pair_confirm_without_start(cabinet: DeviceClient) -> None:
    with pytest.raises(PairingRejectedError) as excinfo:
        cabinet.pair_confirm(PIN, "test-pc")
    assert excinfo.value.reason == "no_pairing"


def test_components_requires_token(cabinet: DeviceClient) -> None:
    with pytest.raises(DeviceUnauthorizedError):
        cabinet.components()


def test_unreachable_host_raises_link_error() -> None:
    client = DeviceClient("127.0.0.1", port=1)  # nothing listens on port 1
    with pytest.raises(DeviceLinkError):
        client.info()
