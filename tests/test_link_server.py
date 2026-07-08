"""LinkFileServer: token-gated, range-capable serving of cached component ZIPs."""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from onesauce_companion.services.link_server import LinkFileServer, _parse_range

TOKEN = "c" * 32


@pytest.fixture()
def served(tmp_path: Path):
    payload = bytes((i % 251) for i in range(50000))
    (tmp_path / "appdata v2.0b51.zip").write_bytes(payload)

    def resolve(name: str) -> Path | None:
        candidate = tmp_path / name
        return candidate if candidate.is_file() else None

    server = LinkFileServer(resolve, lambda: TOKEN, port=0)
    # port=0 -> ephemeral; start() binds it, read back the real port.
    server.start()
    real_port = server._httpd.server_address[1]  # type: ignore[union-attr]
    server.port = real_port
    try:
        yield server, payload, real_port
    finally:
        server.stop()


def _get(port: int, path: str, headers: dict | None = None):
    return requests.get(f"http://127.0.0.1:{port}{path}", headers=headers, timeout=5)


def test_requires_token(served):
    _server, _payload, port = served
    resp = _get(port, "/files/appdata v2.0b51.zip")
    assert resp.status_code == 401


def test_full_download(served):
    _server, payload, port = served
    resp = _get(port, "/files/appdata v2.0b51.zip", {"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["Accept-Ranges"] == "bytes"


def test_range_download(served):
    _server, payload, port = served
    resp = _get(port, "/files/appdata v2.0b51.zip",
                {"Authorization": f"Bearer {TOKEN}", "Range": "bytes=1000-4999"})
    assert resp.status_code == 206
    assert resp.content == payload[1000:5000]
    assert resp.headers["Content-Range"] == f"bytes 1000-4999/{len(payload)}"


def test_open_ended_range(served):
    _server, payload, port = served
    resp = _get(port, "/files/appdata v2.0b51.zip",
                {"Authorization": f"Bearer {TOKEN}", "Range": "bytes=49000-"})
    assert resp.status_code == 206
    assert resp.content == payload[49000:]


def test_unsatisfiable_range(served):
    _server, payload, port = served
    resp = _get(port, "/files/appdata v2.0b51.zip",
                {"Authorization": f"Bearer {TOKEN}", "Range": f"bytes={len(payload)}-"})
    assert resp.status_code == 416


def test_path_traversal_rejected(served):
    _server, _payload, port = served
    resp = _get(port, "/files/..%2f..%2fsecret",
                {"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code in (400, 404)


def test_missing_file(served):
    _server, _payload, port = served
    resp = _get(port, "/files/nope.zip", {"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 404


def test_parse_range_unit():
    assert _parse_range("bytes=0-99", 1000) == (0, 99)
    assert _parse_range("bytes=500-", 1000) == (500, 999)
    assert _parse_range("bytes=-100", 1000) == (900, 999)
    assert _parse_range("bytes=2000-3000", 1000) is None  # past end
    assert _parse_range("items=0-1", 1000) is None
