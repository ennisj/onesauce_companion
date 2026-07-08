"""Companion file server for the cabinet link (Phase 2).

The paired One Saucier cabinet installs components by downloading their ZIPs
from this server (its existing download->verify->extract pipeline, pointed at
a companion URL instead of Archive.org). We serve exactly one route:

    GET /files/<filename>   Bearer-authed, Range-capable

Bulk bytes therefore flow companion -> cabinet as a normal HTTP download the
cabinet already knows how to resume and verify. The server is Qt-free; the UI
starts/stops it and supplies the token + a filename->Path resolver.
"""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

LINK_FILE_PORT = 47656
_CHUNK = 256 * 1024


def local_ip() -> str:
    """This host's LAN IPv4 (the interface that routes outward). No DNS needed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _server(self) -> "LinkFileServer":
        return self.server._link  # type: ignore[attr-defined]

    def _authed(self) -> bool:
        token = self._server.token_provider()
        if not token:
            return False
        return self.headers.get("Authorization") == f"Bearer {token}"

    def _deny(self, code: int, message: str) -> None:
        body = message.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(body=False)

    def _serve(self, *, body: bool) -> None:
        if not self.path.startswith("/files/"):
            self._deny(404, "not found")
            return
        if not self._authed():
            self._deny(401, "unauthorized")
            return
        raw = self.path[len("/files/"):].split("?", 1)[0]
        name = unquote(raw)
        # Only a bare filename is servable — reject any path separators / parent
        # refs so a request can never escape the downloads directory.
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            self._deny(400, "bad filename")
            return
        path = self._server.resolve(name)
        if path is None or not path.is_file():
            self._deny(404, "no such file")
            return

        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            parsed = _parse_range(range_header, size)
            if parsed is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                return
            start, end = parsed
            status = 206

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Connection", "close")
        self.end_headers()
        if not body:
            return
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(_CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # cabinet aborted/paused mid-transfer; it will resume via Range

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - silence default logging
        pass


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse a single ``bytes=start-end`` range. Returns (start, end) or None."""
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    lo, hi = spec.split("-", 1)
    try:
        if lo == "":  # suffix range: bytes=-N (last N bytes)
            n = int(hi)
            if n <= 0:
                return None
            return max(0, size - n), size - 1
        start = int(lo)
        end = int(hi) if hi else size - 1
    except ValueError:
        return None
    if start > end or start >= size:
        return None
    return start, min(end, size - 1)


class LinkFileServer:
    """Owns the background HTTP server thread serving cached component ZIPs."""

    def __init__(
        self,
        resolve: Callable[[str], Path | None],
        token_provider: Callable[[], str],
        port: int = LINK_FILE_PORT,
    ) -> None:
        self.resolve = resolve
        self.token_provider = token_provider
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def base_url(self) -> str:
        return f"http://{local_ip()}:{self.port}"

    def file_url(self, filename: str) -> str:
        # Percent-encode the filename so spaces/unicode form a valid URL that
        # the cabinet's libcurl sends verbatim and the handler unquotes back.
        return f"{self.base_url()}/files/{quote(filename)}"

    def start(self) -> None:
        if self._httpd is not None:
            return
        httpd = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        # Port 0 = OS-assigned (tests); read back the real port so file_url()
        # advertises the address the server is actually bound to.
        self.port = httpd.server_address[1]
        httpd._link = self  # type: ignore[attr-defined]
        thread = threading.Thread(target=httpd.serve_forever, name="link-file-server", daemon=True)
        thread.start()
        self._httpd = httpd
        self._thread = thread

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None
