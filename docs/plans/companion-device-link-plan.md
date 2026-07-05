# Companion ↔ One Saucier Peer-to-Peer Link — Feasibility & Implementation Plan

> Status: proposal (2026-07-04). Covers LAN discovery/pairing between the
> OnesaUCE Companion (PC, PySide6) and one_saucier / onesauce_dl (ALU, C++),
> companion-driven remote update management, and device downloads routed
> through the companion instead of Archive.org.

---

## 1. Feasibility verdict

**Feasible, and cheaper than it first looks.** The single most important
design insight: **the device already has a complete, hardware-proven HTTP
download → verify → extract → sync pipeline** (libcurl, range resume,
segmented transfer, free-space pre-check, CP437/ZIP64 extract, `sync()`
durability). If the companion serves component ZIPs over plain HTTP with
`Range` support, *both* requested directions collapse into "the device
downloads from a different URL":

- **Companion manages the device drive** = companion tells the device
  "install component X from `http://<pc>:<port>/files/<name>.zip`" and the
  device runs its normal job pipeline against that URL.
- **Device updates via companion instead of Archive.org** = the same
  mechanism, initiated from the device UI, with the companion also serving
  the catalog (proxying/caching Archive.org metadata and files using the
  PC's credentials).

This avoids the two expensive alternatives evaluated and rejected:

- ❌ *Remote filesystem abstraction in the companion* (refactoring
  `services/archive.py` / `installer.py` / `state.py` off bare `Path` onto a
  storage interface, then implementing a remote backend). Huge refactor; not
  needed when extraction happens on-device.
- ❌ *Raw file-push protocol* (companion streams individual extracted files
  to the device). Reinvents resume/verification/durability the device
  already has for ZIP-based installs.

### What exists today (verified in source)

**Device (`e:\dev\onesauce_dl`, app in `app/`, ~v0.0.1):**
- Outbound HTTPS only via libcurl 7.79 (dynamic, bundled in cart squashfs);
  no server sockets, no mDNS, no JSON library (hand parsing), no checksums
  (size-only verification), no device identity or peer auth.
- Custom `getaddrinfo` interposer (`app/dns_override.cpp`) — raw UDP DNS,
  IPv4 A-records only. Peer connections should use literal IPs to bypass it.
- Threading idiom: one `std::thread` per concern publishing `std::atomic`
  state polled by the ImGui render loop; clean join-on-shutdown. A link
  service thread slots straight into this pattern.
- Runs **as root** inside the retroplayer/scripter context — binding a
  listening socket should be permitted, but must be proven on hardware
  (Phase 0).
- Single-slot job queue (`g_queue`); one download/extract at a time.
- Install state derived from on-drive `version.txt` files
  (`app/version_state.*`); reusable verbatim to answer "what's installed"
  over the link.
- Credentials: Archive.org cookies + base64 password in
  `onesauce_auth.cfg`; prefs in `onesauce_prefs.cfg` (`app/prefs.*`) — the
  natural home for a pairing token.

**Companion (`e:\dev\onesauce_companion`, v0.3.2):**
- Python 3.11+/PySide6; networking = `requests` + `internetarchive` client
  stack only. No server, no zeroconf, no asyncio.
- Full Archive.org download core (`services/downloader.py`: resume,
  segmented, size verification, progress callbacks) + metadata service +
  keyring credential storage.
- Qt worker/`Signal` progress plumbing (`ui/workers.py`,
  `ui/downloads_controller.py`) ready to host new remote operations.
- Settings dataclass (`services/settings.py`) with structured-list
  persistence and a keyring pattern — paired-device records and secrets fit
  naturally.
- `DOCUMENTATION.md` explicitly states the app never contacts Legends
  devices — this project deliberately overturns that; docs must change.

### Discrepancy — RESOLVED (2026-07-04)

The device-side findings above were surveyed against a stale `main`
(v0.0.1). The current tree (`harness-round-5`, since fast-forwarded into
`main` at `c972caf`, v0.0.4) matches the release README: **parallel
component downloads** (prefs `parallel` slot count), **staged crash-safe
installs** (staging dir + move-into-place in `main.cpp`/`unzip.*`),
"Ready to Install" persistence, and **GitHub self-update** from the
`one_saucier` releases repo. Consequences for this plan:

- Phase 2 gets simpler: link-sourced ZIPs reuse the existing staging dir
  and install queue instead of needing new crash-safety work.
- The multi-lane queue means remote job enqueue should target the same
  queue the catalog UI uses (jobs are no longer single-slot), and
  `/jobs/current` becomes `/jobs` (a list).
- A self-update channel already exists (GitHub releases), so the Phase 4
  stretch goal of companion-pushed app updates is even less compelling.
- Single-thread-per-concern architecture, `version_state`, `download_plan`,
  and the prefs/auth file patterns are unchanged and the plan's device
  integration points remain valid; re-verify exact line references against
  v0.0.4 before implementation.

---

## 2. Architecture

```
┌──────────────────────── PC ────────────────────────┐   ┌────────────── ALU ──────────────┐
│ OnesaUCE Companion (PySide6)                       │   │ one_saucier (C++/SDL2/ImGui)    │
│                                                    │   │                                 │
│  DeviceLinkService (new)                           │   │  LinkService thread (new)       │
│   • UDP discovery probe (broadcast :47654) ────────┼──▶│   • UDP responder :47654        │
│   • DeviceClient (requests, Bearer token) ─────────┼──▶│   • HTTP server :47655          │
│   • LinkServer (ThreadingHTTPServer :47656)        │   │     (cpp-httplib, token auth)   │
│     - /catalog        (IA metadata proxy/cache)    │   │                                 │
│     - /files/<name>   (Range-capable ZIP serving,  │◀──┼──  existing libcurl job pipeline│
│        from local download cache or IA streaming   │   │    downloads from LinkServer    │
│        proxy with PC credentials)                  │   │    URLs exactly like archive.org│
└────────────────────────────────────────────────────┘   └─────────────────────────────────┘
```

- **Transport: HTTP/1.1 + JSON over the LAN, IPv4 literal addresses.** No
  TLS in v1 (see §5 threat model); every request carries
  `Authorization: Bearer <pairing-token>`.
- **Two small servers, one per side.** The device server handles control
  (pair/info/components/jobs). The companion server handles bulk data
  (catalog + ZIP bytes). Big transfers therefore always flow
  **companion → device as a device-initiated download**, reusing the proven
  pipeline; the device server never streams large bodies.
- **Discovery: UDP broadcast probe/response** (companion broadcasts
  `OSDL v1 DISCOVER <nonce>`; device replies with JSON: device name, app
  version, HTTP port, drive free/total, paired-state). mDNS rejected —
  nothing on the device supports it, `python-zeroconf` is a new dep, and a
  40-line UDP responder is strictly simpler. **Manual IP entry is a
  first-class fallback** (separate subnets / broadcast-filtering APs).
- **Pairing: PIN on the cabinet screen.** Companion calls
  `POST /pair {nonce}` → device displays a 6-digit PIN → user types it into
  the companion → companion calls `POST /pair/confirm {pin}` → device mints
  a random 32-byte token, stores it (prefs-style file in `APP_DIR`),
  returns it once. Companion stores it in the OS keyring
  (`onesauce_companion` service, key `device_token_<device-id>`) with a
  `paired_devices` record (name, device-id, last IP) in `settings.json`.

### Device HTTP API (v1)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/pair`, `/pair/confirm` | pairing handshake (unauthenticated; PIN-gated) |
| `GET /api/v1/info` | device name, app version, drive free/total, link state |
| `GET /api/v1/components` | installed components + versions (wraps `version_state`) |
| `POST /api/v1/jobs` | enqueue install: `{stem, filename, size, md5, url}` — `url` points at the companion LinkServer |
| `GET /api/v1/jobs/current` | phase/got/total/speed (mirror of `Job` atomics) |
| `POST /api/v1/jobs/current/cancel` | cooperative cancel (sets `g_job.cancel`) |

All JSON bodies flat key/value — writable by hand, parseable with the
existing `json_str()` helper style. No JSON library needed for v1.

### Companion LinkServer (v1)

- `GET /catalog` — the merged catalog (item/stem/filename/size/**md5**/
  version) built from `ArchiveMetadataService`, cached with a TTL.
- `GET /files/<filename>` — component ZIP with full `Range` support
  (single-range is enough — that's all the device pipeline sends per
  handle). Source: the companion download cache if present, else a
  streaming proxy from Archive.org using the PC's `internetarchive`
  session. **Recommended v1 simplification: download-then-serve** (companion
  fetches to its cache first, then serves locally) — a streaming Range proxy
  over a remote origin is the fiddliest part of the whole design and can be
  Phase-3 polish.
- Implementation: stdlib `http.server.ThreadingHTTPServer` on a `QThread`
  (no new dependency), token check on every request, bind `0.0.0.0`,
  configurable port. Windows Firewall will prompt on first listen —
  document it.

---

## 3. Implementation phases

### Phase 0 — hardware spike (small, do first) — ✅ PASSED 2026-07-04

Run on real hardware (onesauce_dl branch `link-phase0`: `app/link_spike.*` +
`scripts/link_spike_pc.py`; device at 192.168.1.233, v0.0.4 spike build):

- **TCP listen/accept works** in the retroplayer/root context — PC fetched
  the device's `/info` JSON from `:47655`. The device-hosted control server
  design stands; no polling fallback needed.
- **UDP discovery replies work, but pure broadcast did not**: the device
  only answered after the PC sent unicast probes (`--device <ip>`).
  Probable AP/WiFi broadcast filtering. Phase 1 discovery must try, in
  order: subnet-directed broadcast (e.g. 192.168.1.255), then a unicast
  sweep of the /24, with manual IP entry as the always-available fallback
  — and the companion should cache the last known device IP.
- **Range GET from the PC by literal IP works** — device pulled
  `bytes=1000-4999` from the PC's HTTP server, got 206 + exactly 4000
  pattern-verified bytes through the normal libcurl stack
  (`dns_override` passes literal IPv4 through untouched).

Spike ports used (keep for the real protocol): UDP 47654 discovery,
TCP 47655 device control, TCP 47656 companion file server.
Prove the two facts everything depends on:
1. The device binary can `bind()`/`listen()`/`accept()` on TCP and receive
   UDP broadcasts in the retroplayer/root context (a 100-line test screen
   in the app that opens both sockets and logs peer probes to `ui_run.log`).
2. The device can download from a PC-hosted HTTP server by literal IP
   (bypassing `dns_override`) with ranges (`python -m http.server` + one
   existing job pointed at it).

Deliverable: log evidence from real hardware. If (1) fails, fall back to a
device-polls-companion design (device is client-only; companion server
carries commands as a job queue the device long-polls) — worse UX, still
viable, and the rest of the plan survives with the arrows reversed.

### Phase 1 — wiring & pairing (the user-visible "connection works") — ✅ PASSED 2026-07-04

Hardware-verified: the companion discovered the cabinet, PIN-paired, and
listed the cabinet's installed components. Device on branch `link-phase1`
(onesauce_dl), companion on branch `cabinet-link` (onesauce_companion).
Notable fixes during bring-up: (a) the device must not hold its state mutex
across the token-file `::sync()` (the render loop polls pairing state every
frame, so a slow USB sync froze the cabinet UI); (b) PIN entry must be an
inline field, not a modal `QInputDialog` — a modal opened from the pairing
worker's signal flow froze the companion GUI on Windows. Regression guard:
`tests/test_cabinet_pairing_flow.py` drives the real screen against a mock
cabinet through a live offscreen-Qt event loop.

Original scope, for reference:
- **Device:** LinkService thread (UDP responder + embedded HTTP server —
  vendor `cpp-httplib` header, MIT; guard behind a prefs toggle
  `companion_link=on/off`); pairing PIN dialog; `/info`, `/components`;
  token persistence in `APP_DIR`; link-status line in the UI.
- **Companion:** `services/device_link.py` (discovery, `DeviceClient`,
  pairing); `paired_devices` in `AppSettings` + keyring token; a new
  **Cabinet** screen: discover/manual-IP, pair, show device info and the
  remote component/version table.
- Exit criteria: companion discovers, pairs, and displays live installed
  versions from a cabinet across the room; survives app restarts on both
  sides (token reuse); unpair works from both ends.

### Phase 2 — companion manages device updates — ⚙️ IMPLEMENTED 2026-07-05 (awaiting hardware test)

Built to the cache-based scope: the companion serves component ZIPs it has
already downloaded (Downloads screen) over a token-gated, Range-capable file
server (`services/link_server.py`, :47656); the cabinet installs them via new
`POST/GET/cancel /api/v1/jobs` routed through its existing
download→verify→extract pipeline, MD5-verified (vendored `app/md5.cpp`) and
Bearer-authed with the pairing token. Cabinet screen gained a "Send a
Component to the Cabinet" panel with off-thread hashing + progress polling.
On-demand Archive.org fetch + `/catalog` remain Phase 3. Verified with an
offscreen-Qt end-to-end test (`test_cabinet_push_flow.py`) where a mock
cabinet downloads the pushed ZIP back through the live file server and
MD5-verifies it. Original scope, for reference:
- **Companion:** LinkServer (`/catalog`, `/files/…` from local cache,
  download-then-serve); Cabinet screen gains install/update actions that
  (a) ensure the ZIP is in the local cache, (b) `POST /jobs` to the device,
  (c) poll `/jobs/current` into the existing progress-widget plumbing.
- **Device:** job source generalization — accept an absolute URL + expected
  `size`/`md5`; skip Archive.org cookies for non-archive hosts and send the
  Bearer token instead; **add MD5 verification** (vendor a small md5.c,
  ~150 lines) for link-sourced downloads (Archive.org metadata already
  carries the MD5s; the companion passes them through). Remote jobs render
  in the normal job UI and are cancellable locally.
- Exit criteria: from the PC, update a stale game pack on the cabinet
  end-to-end with progress visible on both screens, MD5-verified, surviving
  a mid-transfer companion restart (device range-resumes).

### Phase 3 — device-initiated updates via companion
- **Device:** a catalog-source switch (Archive.org ⇄ paired companion).
  When linked, fetch `/catalog` from the companion and download via
  `/files/…` — no Archive.org sign-in needed on the cabinet at all.
  Auto-fallback to Archive.org when the companion is unreachable.
- **Companion:** on-demand cache fill for `/files/…` misses (fetch from IA
  with PC credentials, then serve); optionally upgrade to a true streaming
  Range proxy here.
- Exit criteria: a cabinet with **no** Archive.org credentials installs a
  component picked in the one_saucier catalog UI, sourced through the PC.

### Phase 4 — hardening & docs
- Timeouts/retries on every link call; graceful behavior when the peer
  vanishes mid-job; port-conflict handling; multi-device support in the
  Cabinet screen; concurrent-job coordination if the multi-lane queue from
  the release README materializes.
- Update `DOCUMENTATION.md` (removes the "never connects to devices"
  claim), one_saucier README, and add `docs/specs/companion-device-link.md`
  as the protocol spec once the wire format stabilizes.
- Stretch (explicitly out of v1 scope): companion pushing **one_saucier app
  updates** to `onesauce_dl/` on the drive. Note commit `3fee295` proved
  `.uce` self-deploy infeasible on-device; replacing the *binary* in the
  editable folder + restart is likely viable but needs its own spike.

---

## 4. Effort & risk

| Piece | Size | Risk |
|---|---|---|
| Phase 0 spike | ~1 session | **Key risk retired here**: listener permitted in scripter context? |
| Device LinkService + pairing | 2–3 sessions | cpp-httplib on glibc 2.31/armhf — expected fine (header-only, needs only sockets+pthread), verify in spike build |
| Companion discovery/pairing/Cabinet UI | 2–3 sessions | low; all patterns exist |
| Companion LinkServer (cache-serve) | 1–2 sessions | Range handling correctness; Windows Firewall UX |
| Device job-from-URL + MD5 | 1–2 sessions | low; pipeline unchanged |
| Phase 3 catalog switch | 1–2 sessions | low |

Biggest unknowns, in order: (1) listening sockets on the device,
(2) Windows Firewall/AP isolation
eating discovery (mitigated by manual IP), (3) device HTTP server stability
during a simultaneous heavy download (mitigate: server thread does no disk
I/O beyond version scans; job work stays on the job thread).

---

## 5. Security model (deliberate v1 scope)

- LAN-only, plaintext HTTP, bearer-token auth minted at PIN pairing. The
  token gates everything except the pairing endpoints (PIN-gated, physical
  access to the cabinet screen required).
- Archive.org credentials **never** cross the link in either direction —
  Phase 3 removes the need for them on the device entirely.
- Content integrity via IA-published MD5s end-to-end.
- Consciously deferred: TLS on the link (self-signed + pinning is the
  upgrade path; both cpp-httplib and Python `ssl` support it), replay
  protection, multi-user scenarios. Acceptable for a personal LAN device;
  revisit if this ever ships beyond that.
