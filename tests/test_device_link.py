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
from urllib.parse import parse_qs, urlsplit

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
    posted_jobs: list = []
    cancelled: list = []
    jobs_state: list = []

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/jobs":
            if not self._authed():
                self._send(401, {"error": "unauthorized"})
                return
            self._send(200, {"jobs": type(self).jobs_state})
            return
        if self.path == "/api/v1/info":
            self._send(200, {
                "app": "one_saucier", "proto": 1, "version": "v0.0.5",
                "device_id": "cafe1234cafe1234", "name": "One Saucier",
                "ip": "127.0.0.1", "tcp_port": self.server.server_port,
                "paired": True, "drive_free": 1000, "drive_total": 2000,
            })
            return
        split = urlsplit(self.path)
        if split.path == "/api/v1/components":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._send(401, {"error": "unauthorized"})
                return
            components = [
                {"group": "Base build", "stem": "appdata", "display": "appdata",
                 "installed": "v2.0b51"},
                {"group": "Game packs", "stem": "Atari2600", "display": "Atari 2600",
                 "installed": ""},
                {"group": "Game packs", "stem": "Bally Astrocade", "display": "Bally Astrocade",
                 "installed": "v2.0b2"},
            ]
            # Same semantics as the device: ?stem= narrows to one component,
            # unknown stems yield an empty list.
            stem = parse_qs(split.query).get("stem", [""])[0]
            if stem:
                components = [c for c in components if c["stem"] == stem]
            self._send(200, {"components": components})
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
        if self.path == "/api/v1/jobs":
            if not self._authed():
                self._send(401, {"error": "unauthorized"})
                return
            type(self).posted_jobs.append(body)
            self._send(200, {"status": "accepted"})
            return
        if self.path == "/api/v1/jobs/cancel":
            if not self._authed():
                self._send(401, {"error": "unauthorized"})
                return
            type(self).cancelled.append(body.get("stem"))
            self._send(200, {"status": "cancelling"})
            return
        self._send(404, {"error": "not_found"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - silence test output
        pass


@pytest.fixture()
def cabinet():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCabinet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _MockCabinet.pairing_active = False
    _MockCabinet.posted_jobs = []
    _MockCabinet.cancelled = []
    _MockCabinet.jobs_state = []
    try:
        yield DeviceClient("127.0.0.1", port=server.server_address[1], token=TOKEN)
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
    assert [c.stem for c in components] == ["appdata", "Atari2600", "Bally Astrocade"]
    assert components[0].installed == "v2.0b51"
    assert components[1].installed == ""


def test_components_single_stem(cabinet: DeviceClient) -> None:
    components = cabinet.components(stem="appdata")
    assert [c.stem for c in components] == ["appdata"]
    assert components[0].installed == "v2.0b51"


def test_components_single_stem_with_space(cabinet: DeviceClient) -> None:
    # Stems like "Bally Astrocade" must survive URL encoding round-trip.
    components = cabinet.components(stem="Bally Astrocade")
    assert [c.stem for c in components] == ["Bally Astrocade"]
    assert components[0].installed == "v2.0b2"


def test_components_unknown_stem(cabinet: DeviceClient) -> None:
    assert cabinet.components(stem="NoSuchStem") == []


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
    cabinet.token = ""  # drop the token the fixture pre-set
    with pytest.raises(DeviceUnauthorizedError):
        cabinet.components()


def test_unreachable_host_raises_link_error() -> None:
    client = DeviceClient("127.0.0.1", port=1)  # nothing listens on port 1
    with pytest.raises(DeviceLinkError):
        client.info()


def test_post_job(cabinet: DeviceClient) -> None:
    cabinet.post_job(stem="appdata", display="appdata", group="Base build",
                     filename="appdata v2.0b51.zip",
                     url="http://192.168.1.21:47656/files/appdata v2.0b51.zip",
                     size=12345, md5="a" * 32, version="v2.0b51")
    assert len(_MockCabinet.posted_jobs) == 1
    job = _MockCabinet.posted_jobs[0]
    assert job["stem"] == "appdata"
    assert job["size"] == 12345
    assert job["md5"] == "a" * 32
    assert job["url"].endswith("/files/appdata v2.0b51.zip")


def test_get_jobs(cabinet: DeviceClient) -> None:
    _MockCabinet.jobs_state = [
        {"stem": "appdata", "display": "appdata", "phase": 1,
         "got": 500, "total": 1000, "message": ""},
    ]
    jobs = cabinet.jobs()
    assert len(jobs) == 1
    assert jobs[0].stem == "appdata"
    assert jobs[0].phase == 1
    assert jobs[0].phase_label == "Downloading"
    assert jobs[0].fraction == 0.5
    assert not jobs[0].is_terminal


def test_cancel_job(cabinet: DeviceClient) -> None:
    assert cabinet.cancel_job("appdata") is True
    assert _MockCabinet.cancelled == ["appdata"]
