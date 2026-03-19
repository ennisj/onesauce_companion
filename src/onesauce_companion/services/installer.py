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
from onesauce_companion.services.control import OperationComponentSkippedError, OperationController
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
    installed_components: list[str]


class Installer:
    def __init__(
        self,
        components: Iterable[ComponentSpec] = REQUIRED_COMPONENTS,
        cache_dir: Path | None = None,
        max_parallel_downloads: int = 2,
    ) -> None:
        self.components = tuple(components)
        self.downloader = Downloader()
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

            if spec.versionless:
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
    ) -> InstallReport:
        controller = controller or OperationController()
        target_dir.mkdir(parents=True, exist_ok=True)
        state = InstallState.load(target_dir)
        current_statuses = self.scan_target(target_dir)
        pending_specs = [status.spec for status in current_statuses if status.status != "Installed"]
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backup_dir = backups_root_path(target_dir) / timestamp
        installed_keys: list[str] = []
        backup_used = False

        if not pending_specs:
            self._emit_log(log_callback, "All required components are already up to date.")
            return InstallReport(backup_dir=None, installed_components=[])

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
                )
                futures[future] = spec

            for index, future in enumerate(as_completed(futures), start=1):
                spec = futures[future]
                try:
                    controller.wait_if_paused(spec.key)
                    archive_path = future.result()
                    self._emit_log(log_callback, f"[{index}/{len(pending_specs)}] Processing {spec.display_name}")
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
                    state.versions[spec.key] = stored_version
                    state.archive_filenames[spec.key] = spec.filename
                    state.save(target_dir)
                    installed_keys.append(spec.key)

                    if status_callback:
                        status_callback(spec.key, "Installed")
                    emit_progress(spec.key, "installed", 1, 1, f"Installed {spec.display_name}")
                    self._emit_log(log_callback, f"Installed {spec.display_name} {stored_version}.")
                except OperationComponentSkippedError:
                    if status_callback:
                        status_callback(spec.key, "Removed")
                    self._emit_log(log_callback, f"Removed {spec.display_name} from the queue before install.")
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
            installed_components=installed_keys,
        )

    def _download_component(
        self,
        spec: ComponentSpec,
        credentials: ArchiveOrgCredentials | None,
        controller: OperationController,
        log_callback: LogCallback | None,
        status_callback: StatusCallback | None,
        emit_progress: Callable[[str, str, int, int, str], None],
    ) -> Path:
        controller.wait_if_paused(spec.key)
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

        if has_nonempty_content(direct_root):
            return "installed"
        for root in collection_roots:
            if has_nonempty_content(root):
                return "installed"

        return state.versions.get(spec.key)

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
