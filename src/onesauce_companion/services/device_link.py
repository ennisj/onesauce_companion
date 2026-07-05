"""LAN link to a One Saucier cabinet (Phase 1: discovery, pairing, status).

Counterpart of the device-side link service in the onesauce_dl repo
(``app/link_service.{h,cpp}``). Wire protocol:

* Discovery: UDP probes ``OSDL1 DISCOVER`` to :47654. The Phase-0 hardware
  spike showed global broadcast (255.255.255.255) does not reach the cabinet
  on some LANs, so :func:`discover_devices` probes the subnet-directed
  broadcast **and** unicasts to any known/last-seen IPs; manual IP entry is
  the always-available fallback.
* Control: HTTP/1.1 JSON on :47655 —
  ``GET /api/v1/info`` (open), ``POST /api/v1/pair`` (open, shows a PIN on
  the cabinet), ``POST /api/v1/pair/confirm`` (open, PIN-gated, returns the
  bearer token exactly once), ``GET /api/v1/components`` (Bearer token).

This module is Qt-free; the UI drives it from worker objects.
"""
from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field

import requests

DISCOVERY_PORT = 47654
CONTROL_PORT = 47655
PROBE = b"OSDL1 DISCOVER"
HTTP_TIMEOUT_S = 6.0


class DeviceLinkError(Exception):
    """Base error for cabinet-link failures (network, protocol)."""


class DeviceUnauthorizedError(DeviceLinkError):
    """The stored token was rejected — the cabinet was unlinked/re-paired."""


class PairingRejectedError(DeviceLinkError):
    """Pairing failed: wrong PIN, expired, cancelled on the cabinet, ..."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Pairing rejected: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class DeviceInfo:
    host: str
    name: str = "One Saucier"
    version: str = ""
    device_id: str = ""
    tcp_port: int = CONTROL_PORT
    paired: bool = False
    drive_free: int = -1
    drive_total: int = -1

    @property
    def label(self) -> str:
        return f"{self.name} ({self.host})"


@dataclass(frozen=True)
class DeviceComponent:
    group: str
    stem: str
    display: str
    installed: str  # "" = not installed; "installed" = present, version unknown


@dataclass(frozen=True)
class PairingResult:
    token: str
    device_id: str
    name: str


def _device_info_from_json(host: str, data: dict[str, object]) -> DeviceInfo:
    return DeviceInfo(
        host=host,
        name=str(data.get("name", "One Saucier")),
        version=str(data.get("version", "")),
        device_id=str(data.get("device_id", "")),
        tcp_port=int(data.get("tcp_port", CONTROL_PORT)),
        paired=bool(data.get("paired", False)),
        drive_free=int(data.get("drive_free", -1)),
        drive_total=int(data.get("drive_total", -1)),
    )


def _local_subnet_broadcasts() -> list[str]:
    """Directed broadcast addresses (/24 assumed) for every local IPv4."""
    addresses: set[str] = set()
    try:
        host_name = socket.gethostname()
        for info in socket.getaddrinfo(host_name, None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    # The interface that actually routes to the LAN (works without DNS).
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 53))
            addresses.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    broadcasts: list[str] = []
    for address in addresses:
        parts = address.split(".")
        if len(parts) == 4 and not address.startswith("127."):
            broadcasts.append(".".join(parts[:3]) + ".255")
    return sorted(set(broadcasts))


def discover_devices(
    known_hosts: list[str] | None = None,
    timeout_s: float = 3.0,
    probes: int = 2,
) -> list[DeviceInfo]:
    """Probe the LAN for cabinets; returns every distinct responder.

    Sends the probe to each subnet-directed broadcast, 255.255.255.255, and
    each ``known_hosts`` entry (unicast — the path Phase 0 proved reliable),
    then collects replies until ``timeout_s`` expires.
    """
    targets = set(_local_subnet_broadcasts())
    targets.add("255.255.255.255")
    for host in known_hosts or []:
        host = host.strip()
        if host:
            targets.add(host)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.25)
    found: dict[str, DeviceInfo] = {}
    try:
        deadline_budget = max(1, int(timeout_s / 0.25))
        for round_no in range(probes):
            for target in targets:
                try:
                    sock.sendto(PROBE, (target, DISCOVERY_PORT))
                except OSError:
                    continue
            for _ in range(deadline_budget // probes or 1):
                try:
                    data, addr = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    payload = json.loads(data.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if not isinstance(payload, dict) or payload.get("app") != "one_saucier":
                    continue
                found[addr[0]] = _device_info_from_json(addr[0], payload)
    finally:
        sock.close()
    return list(found.values())


class DeviceClient:
    """HTTP client for one cabinet's control API."""

    def __init__(self, host: str, port: int = CONTROL_PORT, token: str = "") -> None:
        self.host = host.strip()
        self.port = port
        self.token = token

    def _url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"

    def _headers(self, authed: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if authed and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, *, authed: bool = False,
                 body: dict[str, object] | None = None) -> dict[str, object]:
        try:
            response = requests.request(
                method,
                self._url(path),
                headers=self._headers(authed),
                json=body,
                timeout=HTTP_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            raise DeviceLinkError(f"Cabinet unreachable at {self.host}:{self.port} ({exc})") from exc
        if response.status_code == 401:
            raise DeviceUnauthorizedError("The cabinet rejected the stored link token.")
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            reason = str(data.get("error", f"HTTP {response.status_code}"))
            if path.endswith("/pair/confirm"):
                raise PairingRejectedError(reason)
            raise DeviceLinkError(f"Cabinet error on {path}: {reason}")
        if not isinstance(data, dict):
            raise DeviceLinkError(f"Malformed response from {path}.")
        return data

    def info(self) -> DeviceInfo:
        return _device_info_from_json(self.host, self._request("GET", "/api/v1/info"))

    def pair_start(self, companion_name: str) -> int:
        """Ask the cabinet to show a pairing PIN; returns the PIN TTL seconds."""
        data = self._request("POST", "/api/v1/pair", body={"name": companion_name})
        if data.get("status") != "pin_required":
            raise DeviceLinkError("Cabinet did not enter pairing mode.")
        return int(data.get("expires_in", 120))

    def pair_confirm(self, pin: str, companion_name: str) -> PairingResult:
        data = self._request(
            "POST", "/api/v1/pair/confirm",
            body={"pin": pin.strip(), "name": companion_name},
        )
        token = str(data.get("token", ""))
        if not token:
            raise DeviceLinkError("Cabinet returned no token.")
        self.token = token
        return PairingResult(
            token=token,
            device_id=str(data.get("device_id", "")),
            name=str(data.get("name", "One Saucier")),
        )

    def components(self) -> list[DeviceComponent]:
        data = self._request("GET", "/api/v1/components", authed=True)
        raw = data.get("components", [])
        components: list[DeviceComponent] = []
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                components.append(
                    DeviceComponent(
                        group=str(entry.get("group", "")),
                        stem=str(entry.get("stem", "")),
                        display=str(entry.get("display", "")),
                        installed=str(entry.get("installed", "")),
                    )
                )
        return components
