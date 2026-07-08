"""Self-update for the packaged Companion build (GitHub releases).

Mirrors One Saucier's updater model: check /releases/latest, download the
platform asset, stage it locally, then apply on restart. Python can't replace
its own running PyInstaller folder, so the Windows apply step is a detached
PowerShell script that waits for the app to exit, mirrors the staged folder
over the install folder, and relaunches the new build.

Windows is the fully-automated path (the packaged build is a onedir folder
that can be mirrored in place). macOS distributes a drag-to-Applications DMG;
replacing a mounted .app from inside itself is not attempted — the updater
downloads and opens the DMG, and the user drags to finish.

Qt-free: the UI drives this from a worker object.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from onesauce_companion.services.github_releases import LATEST_RELEASE_API_URL
from onesauce_companion.services.settings import SettingsStore

WINDOWS_ASSET_SUFFIX = "-windows.zip"
MACOS_ASSET_SUFFIX = "-macos-arm64.dmg"
WINDOWS_EXE_NAME = "OnesaUCECompanion.exe"
_DOWNLOAD_CHUNK = 256 * 1024


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    assets: tuple[ReleaseAsset, ...]


def is_frozen_build() -> bool:
    """True when running the packaged (PyInstaller) build."""
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path | None:
    """The packaged build's install folder, or None when not applicable.

    Guarded: only a folder that actually contains the running executable is
    ever returned, so the apply script can never mirror over a wrong path.
    """
    if not is_frozen_build():
        return None
    exe = Path(sys.executable).resolve()
    root = exe.parent
    if not (root / exe.name).is_file():
        return None
    return root


def updates_dir() -> Path:
    """Staging area for downloaded/extracted updates (user config dir)."""
    return SettingsStore().config_dir / "updates"


def release_from_payload(payload: object) -> ReleaseInfo | None:
    """Parse the GitHub /releases/latest JSON into a ReleaseInfo."""
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name", "")).strip()
    if not tag:
        return None
    assets: list[ReleaseAsset] = []
    raw_assets = payload.get("assets", [])
    if isinstance(raw_assets, list):
        for entry in raw_assets:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            url = str(entry.get("browser_download_url", "")).strip()
            if not name or not url:
                continue
            try:
                size = int(entry.get("size", 0))
            except (TypeError, ValueError):
                size = 0
            assets.append(ReleaseAsset(name=name, url=url, size=size))
    return ReleaseInfo(tag=tag, assets=tuple(assets))


def fetch_latest_release() -> ReleaseInfo | None:
    response = requests.get(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OnesaUCE-Companion-Self-Update",
        },
        timeout=15,
    )
    response.raise_for_status()
    return release_from_payload(response.json())


def select_platform_asset(release: ReleaseInfo, platform: str = sys.platform) -> ReleaseAsset | None:
    """The release asset for this OS (Windows zip / macOS DMG)."""
    suffix = WINDOWS_ASSET_SUFFIX if platform == "win32" else MACOS_ASSET_SUFFIX
    for asset in release.assets:
        if asset.name.endswith(suffix):
            return asset
    return None


def download_asset(
    asset: ReleaseAsset,
    dest: Path,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """Stream ``asset`` to ``dest``; progress_cb receives (got, total) bytes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    got = 0
    with requests.get(asset.url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", asset.size or 0))
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                if not chunk:
                    continue
                handle.write(chunk)
                got += len(chunk)
                if progress_cb is not None:
                    progress_cb(got, total)
    if asset.size and got != asset.size:
        partial.unlink(missing_ok=True)
        raise OSError(f"Update download ended early ({got} of {asset.size} bytes).")
    partial.replace(dest)
    return dest


def stage_windows_zip(zip_path: Path, staging_root: Path, exe_name: str = WINDOWS_EXE_NAME) -> Path:
    """Extract the Windows release zip and return the staged app folder.

    The zip carries the app folder at its root (``OnesaUCECompanion/...``).
    Raises ValueError if the archive does not contain the expected executable
    (never stages something that can't relaunch).
    """
    import shutil

    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        root = staging_root.resolve()
        for member in archive.namelist():
            target = (staging_root / member).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Unsafe path in update archive: {member}")
        archive.extractall(staging_root)
    candidates = [path.parent for path in staging_root.rglob(exe_name)]
    if not candidates:
        raise ValueError(f"Update archive does not contain {exe_name}.")
    # Shallowest match is the app folder.
    return min(candidates, key=lambda path: len(path.parts))


def build_windows_apply_script(staged_dir: Path, install_dir: Path, pid: int,
                               exe_name: str = WINDOWS_EXE_NAME) -> str:
    """PowerShell that swaps in the staged build once the app has exited.

    robocopy /MIR makes the install folder exactly match the staged one (stale
    files from the old version are removed); it retries while lingering file
    locks release. Exit codes < 8 are robocopy success codes. Every step is
    logged next to the script (apply_update.log) so a failed apply can be
    diagnosed after the fact — the app is gone by the time this runs, so there
    is nowhere else to report to. The new build is only relaunched when the
    mirror succeeded and the exe is present, so a half-copied folder is never
    launched.
    """
    return f"""# OnesaUCE Companion self-update (auto-generated; safe to delete).
param()
$ErrorActionPreference = "Continue"
$log = Join-Path $PSScriptRoot "apply_update.log"
function Log($m) {{ "$(Get-Date -Format o)  $m" | Add-Content -LiteralPath $log }}
Log "apply started (waiting on pid {pid})"
try {{ Wait-Process -Id {pid} -Timeout 180 -ErrorAction Stop; Log "target process exited" }}
catch {{ Log "wait-process: $_" }}
$staged  = "{staged_dir}"
$install = "{install_dir}"
$ok = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {{
    robocopy $staged $install /MIR /NJH /NJS /NP /R:2 /W:1 *>> $log
    Log "robocopy attempt $attempt exit $LASTEXITCODE"
    if ($LASTEXITCODE -lt 8) {{ $ok = $true; break }}
    Start-Sleep -Seconds 1
}}
$exe = Join-Path $install "{exe_name}"
if ($ok -and (Test-Path -LiteralPath $exe)) {{
    Log "relaunching $exe"
    Start-Process -FilePath $exe
}} else {{
    Log "NOT relaunching (mirror ok=$ok, exe present=$(Test-Path -LiteralPath $exe))"
}}
Log "apply finished"
"""


def launch_windows_apply(staged_dir: Path, install_dir: Path, pid: int,
                         exe_name: str = WINDOWS_EXE_NAME) -> Path:
    """Write the apply script and launch it detached; returns the script path."""
    script = updates_dir() / "apply_update.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        build_windows_apply_script(staged_dir, install_dir, pid, exe_name),
        encoding="utf-8-sig",  # BOM keeps PowerShell 5.1 reading it as UTF-8
    )
    # Flag choice matters (verified empirically on Windows 11 / PS 5.1):
    #   * DETACHED_PROCESS starves powershell.exe of the console its runtime
    #     needs to initialize, so it dies before running the script — and
    #     Popen does NOT raise, so the app just closes and nothing happens
    #     (the original bug). Do NOT use it here.
    #   * CREATE_NO_WINDOW gives a valid but hidden console (powershell runs,
    #     no visible window) and CREATE_NEW_PROCESS_GROUP puts the child in its
    #     own group so it survives the app's exit. This is the working combo.
    # DEVNULL stdio is also required: the app is built --windowed
    # (console=False), so its std handles are None and inheriting them would
    # hand powershell invalid handles.
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", str(script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )
    return script
