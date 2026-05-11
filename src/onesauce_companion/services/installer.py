from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from threading import Lock

from onesauce_companion.manifest import BITLCD_ARCHIVE_ITEM, GAME_PACKS_ARCHIVE_ITEM, REQUIRED_COMPONENTS
from onesauce_companion.models import ComponentSpec, ComponentStatus, InstallProgress
from onesauce_companion.services.collections import matching_collection_names
from onesauce_companion.services.archive import (
    backup_existing_files,
    changed_files_for_archive,
    extract_archive,
    inspect_archive,
    primary_collection_root_for_archive,
)
from onesauce_companion.services.archive_org import ArchiveOrgCredentials
from onesauce_companion.services.control import (
    OperationComponentPausedError,
    OperationComponentSkippedError,
    OperationController,
)
from onesauce_companion.services.download_cache import find_cached_download, list_cached_archive_files
from onesauce_companion.services.downloader import Downloader
from onesauce_companion.services.state import InstallState, backups_root_path
from onesauce_companion.services.versioning import (
    has_nonempty_content,
    read_version_file,
    read_version_from_install_root,
    read_version_from_named_subfolders,
)


StatusCallback = Callable[[str, str], None]
LogCallback = Callable[[str], None]
PhaseCallback = Callable[[InstallProgress], None]


@dataclass(frozen=True)
class InstallReport:
    backup_dir: Path | None
    downloaded_components: list[str]
    installed_components: list[str]


class Installer:
    def __init__(
        self,
        components: Iterable[ComponentSpec] = REQUIRED_COMPONENTS,
        cache_dir: Path | None = None,
        max_parallel_downloads: int = 2,
        downloader: Downloader | None = None,
    ) -> None:
        self.components = tuple(components)
        self.downloader = downloader if downloader is not None else Downloader()
        self.cache_dir = cache_dir or Path.home() / ".onesauce_companion" / "downloads"
        self.max_parallel_downloads = max(1, max_parallel_downloads)

    def scan_target(self, target_dir: Path) -> list[ComponentStatus]:
        state = InstallState.load(target_dir)
        statuses: list[ComponentStatus] = []
        for spec in self.components:
            installed_version = self._installed_version(target_dir, spec, state)
            if installed_version is None:
                statuses.append(
                    ComponentStatus(
                        spec=spec,
                        installed_version=None,
                        available_version=spec.available_version,
                        status="Missing",
                        detail="Component not detected.",
                    )
                )
                continue

            if spec.versionless and not _optional_component_tracks_version(spec):
                status = "Installed"
                detail = "Installed content detected from the expected folder location."
            elif installed_version == "installed":
                status = "Installed"
                detail = "Installed content detected from the expected folder location."
            elif _version_at_least(installed_version, spec.available_version):
                status = "Installed"
                detail = "Installed version matches or exceeds the current manifest."
            else:
                status = "Update Available"
                detail = f"Installed {installed_version}, available {spec.available_version}."

            statuses.append(
                ComponentStatus(
                    spec=spec,
                    installed_version=installed_version,
                    available_version=spec.available_version,
                    status=status,
                    detail=detail,
                )
            )
        return statuses

    def install_required(
        self,
        target_dir: Path,
        credentials: ArchiveOrgCredentials | None = None,
        controller: OperationController | None = None,
        status_callback: StatusCallback | None = None,
        log_callback: LogCallback | None = None,
        phase_callback: PhaseCallback | None = None,
        download_only: bool = False,
        force_component_keys: set[str] | None = None,
    ) -> InstallReport:
        controller = controller or OperationController()
        target_dir.mkdir(parents=True, exist_ok=True)
        state = InstallState.load(target_dir)
        current_statuses = self.scan_target(target_dir)
        forced_keys = force_component_keys or set()
        pending_specs = [
            status.spec for status in current_statuses if status.status != "Installed" or status.spec.key in forced_keys
        ]
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backup_dir = backups_root_path(target_dir) / timestamp
        downloaded_keys: list[str] = []
        installed_keys: list[str] = []
        backup_used = False

        if not pending_specs:
            self._emit_log(log_callback, "All required components are already up to date.")
            return InstallReport(backup_dir=None, downloaded_components=[], installed_components=[])

        if credentials is not None:
            user = self.downloader.authenticate_with_archive_org(credentials)
            self._emit_log(log_callback, f"Authenticated with Archive.org as {user}.")

        progress_values = {spec.key: 0.0 for spec in pending_specs}
        progress_lock = Lock()

        def emit_progress(
            component_key: str,
            phase: str,
            current: int,
            total: int,
            detail: str,
        ) -> None:
            fraction = _phase_fraction(phase, current, total)
            component_percent = _phase_percent(phase, current, total)
            with progress_lock:
                progress_values[component_key] = max(progress_values[component_key], fraction)
                overall_percent = int(sum(progress_values.values()) / len(progress_values) * 100)
            if phase_callback:
                phase_callback(
                    InstallProgress(
                        component_key=component_key,
                        phase=phase,
                        current=current,
                        total=total,
                        component_percent=component_percent,
                        overall_percent=max(0, min(100, overall_percent)),
                        detail=detail,
                    )
                )

        cache_files = list_cached_archive_files(self.cache_dir)

        if len(pending_specs) == 1 and self.max_parallel_downloads == 1:
            spec = pending_specs[0]
            try:
                emit_progress(spec.key, "queued", 0, 0, f"Queued {spec.display_name}")
                controller.wait_if_paused(spec.key)
                archive_path = self._download_component(
                    spec,
                    credentials,
                    controller,
                    log_callback,
                    status_callback,
                    emit_progress,
                    cache_files,
                )
                backup_used = self._finalize_downloaded_spec(
                    spec,
                    archive_path,
                    target_dir,
                    state,
                    controller,
                    status_callback,
                    log_callback,
                    emit_progress,
                    download_only,
                    len(pending_specs),
                    1,
                    downloaded_keys,
                    installed_keys,
                    backup_dir,
                    backup_used,
                )
            except OperationComponentSkippedError:
                if status_callback:
                    status_callback(spec.key, "Removed")
                self._emit_log(log_callback, f"Removed {spec.display_name} from the queue before install.")
            except OperationComponentPausedError:
                if status_callback:
                    status_callback(spec.key, "Paused")
                self._emit_log(log_callback, f"Paused {spec.display_name}.")
            return InstallReport(
                backup_dir=backup_dir if backup_used else None,
                downloaded_components=downloaded_keys,
                installed_components=installed_keys,
            )

        futures: dict[Future[Path], ComponentSpec] = {}
        executor = ThreadPoolExecutor(max_workers=min(self.max_parallel_downloads, len(pending_specs)))
        try:
            for spec in pending_specs:
                emit_progress(spec.key, "queued", 0, 0, f"Queued {spec.display_name}")
                future = executor.submit(
                    self._download_component,
                    spec,
                    credentials,
                    controller,
                    log_callback,
                    status_callback,
                    emit_progress,
                    cache_files,
                )
                futures[future] = spec

            for index, future in enumerate(as_completed(futures), start=1):
                spec = futures[future]
                try:
                    controller.wait_if_paused(spec.key)
                    archive_path = future.result()
                    backup_used = self._finalize_downloaded_spec(
                        spec,
                        archive_path,
                        target_dir,
                        state,
                        controller,
                        status_callback,
                        log_callback,
                        emit_progress,
                        download_only,
                        len(pending_specs),
                        index,
                        downloaded_keys,
                        installed_keys,
                        backup_dir,
                        backup_used,
                    )
                except OperationComponentSkippedError:
                    if status_callback:
                        status_callback(spec.key, "Removed")
                    self._emit_log(log_callback, f"Removed {spec.display_name} from the queue before install.")
                    continue
                except OperationComponentPausedError:
                    if status_callback:
                        status_callback(spec.key, "Paused")
                    self._emit_log(log_callback, f"Paused {spec.display_name}.")
                    continue
        except Exception:
            controller.cancel()
            for future in futures:
                future.cancel()
            raise
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        return InstallReport(
            backup_dir=backup_dir if backup_used else None,
            downloaded_components=downloaded_keys,
            installed_components=installed_keys,
        )

    def _finalize_downloaded_spec(
        self,
        spec: ComponentSpec,
        archive_path: Path,
        target_dir: Path,
        state: InstallState,
        controller: OperationController,
        status_callback: StatusCallback | None,
        log_callback: LogCallback | None,
        emit_progress: Callable[[str, str, int, int, str], None],
        download_only: bool,
        total_pending: int,
        index: int,
        downloaded_keys: list[str],
        installed_keys: list[str],
        backup_dir: Path,
        backup_used: bool,
    ) -> bool:
        downloaded_keys.append(spec.key)
        if download_only:
            if status_callback:
                status_callback(spec.key, "Downloaded")
            self._emit_log(log_callback, f"Downloaded {spec.display_name}.")
            return backup_used

        self._emit_log(log_callback, f"[{index}/{total_pending}] Processing {spec.display_name}")
        inspection = inspect_archive(archive_path, spec)
        available_version = inspection.embedded_version or spec.available_version

        if status_callback:
            status_callback(spec.key, "Preparing")
        self._emit_log(log_callback, f"Checking existing files for {spec.display_name}...")
        changed_paths = changed_files_for_archive(
            archive_path,
            target_dir,
            controller=controller,
            component_key=spec.key,
            progress_callback=lambda current, total, key=spec.key, label=spec.display_name: emit_progress(
                key,
                "prepare",
                current,
                total,
                f"Preparing {label}",
            ),
        )
        if changed_paths:
            if status_callback:
                status_callback(spec.key, "Backing Up")
            copied = backup_existing_files(
                target_dir,
                backup_dir,
                changed_paths,
                controller=controller,
                component_key=spec.key,
                progress_callback=lambda current, total, key=spec.key, label=spec.display_name: emit_progress(
                    key,
                    "backup",
                    current,
                    total,
                    f"Backing up {label}",
                ),
            )
            backup_used = backup_used or copied > 0
            self._emit_log(log_callback, f"Backed up {copied} changed files for {spec.display_name}.")
        else:
            self._emit_log(log_callback, f"No changed files to back up for {spec.display_name}.")

        if status_callback:
            status_callback(spec.key, "Installing")
        extract_archive(
            archive_path,
            target_dir,
            controller=controller,
            component_key=spec.key,
            progress_callback=lambda current, total, name, key=spec.key, label=spec.display_name: emit_progress(
                key,
                "extract",
                current,
                total,
                f"Extracting {label}",
            ),
        )

        if spec.archive_item == GAME_PACKS_ARCHIVE_ITEM:
            collection_root = primary_collection_root_for_archive(archive_path)
            if collection_root:
                state.collection_roots[spec.key] = collection_root

        stored_version = available_version or inspection.release_version or spec.available_version
        self._ensure_installed_version_file(target_dir, spec, stored_version)
        state.versions[spec.key] = stored_version
        state.archive_filenames[spec.key] = spec.filename
        state.save(target_dir)
        installed_keys.append(spec.key)

        if status_callback:
            status_callback(spec.key, "Installed")
        emit_progress(spec.key, "installed", 1, 1, f"Installed {spec.display_name}")
        self._emit_log(log_callback, f"Installed {spec.display_name} {stored_version}.")
        return backup_used

    def cached_archive_path(self, spec: ComponentSpec, *, files: list[Path] | None = None) -> Path | None:
        return find_cached_download(self.cache_dir, spec, files=files)

    def _download_component(
        self,
        spec: ComponentSpec,
        credentials: ArchiveOrgCredentials | None,
        controller: OperationController,
        log_callback: LogCallback | None,
        status_callback: StatusCallback | None,
        emit_progress: Callable[[str, str, int, int, str], None],
        cache_files: list[Path] | None = None,
    ) -> Path:
        controller.wait_if_paused(spec.key)
        cached_archive = self.cached_archive_path(spec, files=cache_files)
        if cached_archive is not None:
            cached_size = cached_archive.stat().st_size
            if status_callback:
                status_callback(spec.key, "Using Cache")
            emit_progress(
                spec.key,
                "download",
                cached_size,
                cached_size or 1,
                f"Using cached {spec.display_name}",
            )
            emit_progress(spec.key, "download_complete", 1, 1, f"Using cached {spec.display_name}")
            self._emit_log(log_callback, f"Using cached download for {spec.display_name}: {cached_archive.name}.")
            return cached_archive

        downloader = self.downloader.clone()
        if credentials is not None and downloader.authenticated_user is None:
            downloader.authenticate_with_archive_org(credentials)

        if status_callback:
            status_callback(spec.key, "Downloading")
        archive_path = self.cache_dir / spec.cache_name
        partial_path = archive_path.with_suffix(archive_path.suffix + ".part")
        existing_size = partial_path.stat().st_size if partial_path.exists() else 0
        if existing_size:
            size_note = _format_bytes(existing_size)
            total_note = _format_bytes(spec.size_bytes) if spec.size_bytes else "unknown size"
            self._emit_log(
                log_callback,
                f"Resuming {spec.display_name} from {size_note} of {total_note}.",
            )
        else:
            self._emit_log(log_callback, f"Downloading {spec.display_name}...")

        result = downloader.download(
            spec,
            archive_path,
            controller=controller,
            component_key=spec.key,
            progress_callback=lambda current, total, key=spec.key, label=spec.display_name: emit_progress(
                key,
                "download",
                current,
                total or 0,
                f"Downloading {label}",
            ),
        )
        emit_progress(spec.key, "download_complete", 1, 1, f"Downloaded {spec.display_name}")
        if result.resumed and existing_size:
            self._emit_log(log_callback, f"Resumed download complete for {spec.display_name}.")
        else:
            self._emit_log(log_callback, f"Download ready for {spec.display_name}.")
        return archive_path

    def _installed_version(self, target_dir: Path, spec: ComponentSpec, state: InstallState) -> str | None:
        install_root = state.collection_roots.get(spec.key, spec.install_root)
        direct_root = target_dir / install_root
        collection_roots = [target_dir / "content" / "retrofe" / "collections" / install_root]
        for collection_name in matching_collection_names(target_dir, install_root):
            candidate = target_dir / "content" / "retrofe" / "collections" / collection_name
            if candidate not in collection_roots:
                collection_roots.append(candidate)

        if _is_optional_video_component(spec):
            return self._installed_optional_video_version(target_dir, spec, state)

        if _is_optional_theme_component(spec):
            return self._installed_optional_theme_version(target_dir, spec, state, direct_root)

        if _optional_component_tracks_version(spec):
            detected = read_version_from_install_root(direct_root)
            if detected:
                return detected
            if has_nonempty_content(direct_root):
                inferred = state.versions.get(spec.key) or spec.available_version
                self._ensure_installed_version_file(target_dir, spec, inferred)
                return inferred

        if spec.versionless:
            if has_nonempty_content(direct_root):
                return spec.available_version
            for root in collection_roots:
                if has_nonempty_content(root):
                    return spec.available_version
            return None

        if spec.version_file_relpath:
            detected = read_version_file(target_dir / spec.version_file_relpath)
            if detected:
                return detected

        detected = read_version_from_install_root(direct_root)
        if detected:
            return detected

        for collection_name in matching_collection_names(target_dir, install_root):
            candidate = target_dir / "content" / "retrofe" / "collections" / collection_name
            if candidate not in collection_roots:
                collection_roots.append(candidate)

        for root in collection_roots:
            detected = read_version_from_install_root(root)
            if detected:
                return detected

        if spec.archive_item == BITLCD_ARCHIVE_ITEM:
            detected = read_version_from_named_subfolders(target_dir, spec.install_root)
            if detected:
                return detected

        detected = _legacy_collection_version_fallback(spec, direct_root, collection_roots)
        if detected:
            return detected

        if has_nonempty_content(direct_root):
            return "installed"
        for root in collection_roots:
            if has_nonempty_content(root):
                return "installed"

        return state.versions.get(spec.key)

    def _ensure_installed_version_file(self, target_dir: Path, spec: ComponentSpec, version: str | None) -> None:
        if not _optional_component_tracks_version(spec) or not version:
            return
        version_path = _optional_component_version_file_path(target_dir, spec)
        if version_path is None:
            install_root = target_dir / spec.install_root
            if not install_root.exists() or not install_root.is_dir():
                return
            version_path = install_root / f"{Path(spec.install_root).name} version.txt"
        else:
            install_root = version_path.parent
            if not install_root.exists() or not install_root.is_dir():
                return
        if version_path.exists():
            return
        version_path.parent.mkdir(parents=True, exist_ok=True)
        version_path.write_bytes(f"Build {version}".encode("utf-16"))

    def _installed_optional_video_version(
        self,
        target_dir: Path,
        spec: ComponentSpec,
        state: InstallState,
    ) -> str | None:
        screensaver_root = target_dir / "ha8800_screensaver"
        if not screensaver_root.exists() or not screensaver_root.is_dir():
            return None
        version_path = _optional_component_version_file_path(target_dir, spec)
        if not _optional_video_content_installed(screensaver_root, spec):
            if version_path is not None and version_path.exists():
                try:
                    version_path.unlink()
                except OSError:
                    pass
            return None

        if version_path is not None:
            detected = read_version_file(version_path)
            if detected:
                return detected

        inferred = state.versions.get(spec.key) or spec.available_version
        self._ensure_installed_version_file(target_dir, spec, inferred)
        return inferred

    def _installed_optional_theme_version(
        self,
        target_dir: Path,
        spec: ComponentSpec,
        state: InstallState,
        direct_root: Path,
    ) -> str | None:
        if spec.version_file_relpath:
            detected = read_version_file(target_dir / spec.version_file_relpath)
            if detected:
                return detected

        if not has_nonempty_content(direct_root):
            return None

        base_assets_version = read_version_file(target_dir / "base_assets" / "base_assets version.txt")
        if base_assets_version:
            return base_assets_version

        return state.versions.get("base_assets") or state.versions.get(spec.key) or "installed"

    @staticmethod
    def _emit_log(callback: LogCallback | None, message: str) -> None:
        if callback:
            callback(message)


def _phase_fraction(phase: str, current: int, total: int) -> float:
    if phase == "queued":
        return 0.0
    if phase == "download":
        if total <= 0:
            return 0.05
        return min(0.6, 0.6 * (current / total))
    if phase == "download_complete":
        return 0.6
    if phase == "prepare":
        if total <= 0:
            return 0.65
        return min(0.7, 0.6 + 0.1 * (current / total))
    if phase == "backup":
        return 0.7
    if phase == "extract":
        if total <= 0:
            return 0.72
        return min(0.98, 0.7 + 0.28 * (current / total))
    if phase == "installed":
        return 1.0
    return 0.0


def _phase_percent(phase: str, current: int, total: int) -> float:
    if phase in {"queued"}:
        return 0.0
    if phase in {"download_complete", "installed"}:
        return 100.0
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, round((current / total) * 100, 1)))


def _format_bytes(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown size"
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"



def _version_at_least(installed_version: str, available_version: str) -> bool:
    if installed_version == available_version:
        return True
    return _version_sort_key(installed_version) >= _version_sort_key(available_version)


def _version_sort_key(value: str) -> tuple[int, int, int, str]:
    match = re.match(r"v(\d+)\.(\d+)b(\d+)", value, re.IGNORECASE)
    if not match:
        return (0, 0, 0, value.casefold())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), value.casefold())


def _optional_component_tracks_version(spec: ComponentSpec) -> bool:
    return spec.versionless and spec.key.startswith("optional_") and spec.version_file_relpath is None


def _is_optional_video_component(spec: ComponentSpec) -> bool:
    return _optional_component_tracks_version(spec) and spec.component_type == "Videos"


def _is_optional_theme_component(spec: ComponentSpec) -> bool:
    return spec.key.startswith("optional_") and spec.component_type == "Theme"


def _optional_component_version_file_path(target_dir: Path, spec: ComponentSpec) -> Path | None:
    if not _optional_component_tracks_version(spec):
        return None
    if _is_optional_video_component(spec):
        return target_dir / "ha8800_screensaver" / f"{spec.install_root} Version.txt"
    return target_dir / spec.install_root / f"{Path(spec.install_root).name} version.txt"


def _optional_video_content_installed(root: Path, spec: ComponentSpec) -> bool:
    if not root.exists() or not root.is_dir():
        return False
    matcher = _optional_video_matcher(spec)
    if matcher is None:
        return False
    for path in root.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".mp4":
            continue
        if matcher(path.name):
            return True
    return False


def _optional_video_matcher(spec: ComponentSpec):
    name = spec.display_name
    if name == "Attract Mode Videos":
        return _is_attract_mode_video
    if not name.startswith("Jukebox Videos "):
        return None
    range_name = name.removeprefix("Jukebox Videos ").strip()
    if range_name == "#-A":
        return _is_num_a_jukebox_video
    if range_name == "B-C":
        return lambda filename: _matches_letter_range(filename, "b", "c")
    if range_name == "D-F":
        return lambda filename: _matches_letter_range(filename, "d", "f")
    if range_name == "G-J":
        return lambda filename: _matches_letter_range(filename, "g", "j")
    if range_name == "K-Mg":
        return _matches_k_mg_range
    if range_name == "Mi-O":
        return _matches_mi_o_range
    if range_name == "P-S":
        return lambda filename: _matches_letter_range(filename, "p", "s")
    if range_name == "T-Z":
        return lambda filename: _matches_letter_range(filename, "t", "z")
    return None


def _legacy_collection_version_fallback(spec: ComponentSpec, direct_root: Path, collection_roots: list[Path]) -> str | None:
    if spec.key != "gamepack_daphne":
        return None
    if has_nonempty_content(direct_root):
        return "v2.0b2"
    for root in collection_roots:
        if has_nonempty_content(root):
            return "v2.0b2"
    return None


_ATTRACT_VIDEO_PATTERN = re.compile(r"^\d{3}\s*-\s*.+\.mp4$", re.IGNORECASE)


def _is_attract_mode_video(filename: str) -> bool:
    return bool(_ATTRACT_VIDEO_PATTERN.match(filename))


def _is_num_a_jukebox_video(filename: str) -> bool:
    stem = Path(filename).stem.casefold()
    if not stem:
        return False
    if stem[0].isdigit():
        return False
    return stem.startswith("a")


def _matches_letter_range(filename: str, start: str, end: str) -> bool:
    stem = Path(filename).stem.casefold()
    if not stem or not stem[0].isalpha():
        return False
    return start <= stem[0] <= end


def _matches_k_mg_range(filename: str) -> bool:
    stem = Path(filename).stem.casefold()
    if not stem or not stem[0].isalpha():
        return False
    if stem[0] in {"k", "l"}:
        return True
    return stem.startswith(("ma", "mb", "mc", "md", "me", "mf", "mg"))


def _matches_mi_o_range(filename: str) -> bool:
    stem = Path(filename).stem.casefold()
    if not stem or not stem[0].isalpha():
        return False
    if stem.startswith("mi") or stem.startswith("mj") or stem.startswith("mk") or stem.startswith("ml") or stem.startswith("mm") or stem.startswith("mn") or stem.startswith("mo") or stem.startswith("mp") or stem.startswith("mq") or stem.startswith("mr") or stem.startswith("ms") or stem.startswith("mt") or stem.startswith("mu") or stem.startswith("mv") or stem.startswith("mw") or stem.startswith("mx") or stem.startswith("my") or stem.startswith("mz"):
        return True
    return stem[0] in {"n", "o"}
