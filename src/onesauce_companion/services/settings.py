from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from onesauce_companion.services.download_cache import DEFAULT_RETENTION_MODE, default_downloads_dir


LOGGER = logging.getLogger(__name__)


@dataclass
class AppSettings:
    install_target: str = ""
    bitlcd_target: str = ""
    downloads_path: str = str(default_downloads_dir())
    downloads_retention_mode: str = DEFAULT_RETENTION_MODE
    downloads_retention_days: int = 30
    downloads_retention_max_gb: float = 5.0
    auto_resume_downloads_on_start: bool = False
    auto_install_components_after_download: bool = True
    segmented_downloads_enabled: bool = False
    segmented_download_min_size_mb: int = 512
    segmented_download_segments: int = 4
    archive_email: str = ""
    archive_password: str = ""
    parallel_downloads: int = 2
    window_width: int = 1280
    window_height: int = 980
    window_x: int | None = None
    window_y: int | None = None
    log_wrap_lines: bool = False
    log_reverse_order: bool = True
    log_highlight_colors: dict[str, str] = field(default_factory=dict)
    queue_entries: list[dict[str, object]] = field(default_factory=list)
    downloads_operations: list[dict[str, str]] = field(default_factory=list)
    # Downloads table layout: column keys in visual order, per-key pixel
    # widths, and the multi-column sort ({"column": key, "direction": "asc"}).
    downloads_column_order: list[str] = field(default_factory=list)
    downloads_column_widths: dict[str, int] = field(default_factory=dict)
    downloads_sort: list[dict[str, str]] = field(default_factory=list)
    enable_themes_preview: bool = False
    theme_selected_theme: str = ""
    theme_selected_collection: str = ""
    theme_selected_game_key: list[str] = field(default_factory=list)
    theme_show_wireframes: bool = True
    theme_show_media: bool = True
    theme_show_text: bool = True
    # Paired One Saucier cabinet (single-device model, mirroring the cabinet's
    # single-PC token). The bearer token itself lives in the OS keyring.
    cabinet_host: str = ""
    cabinet_device_id: str = ""
    cabinet_name: str = ""


KEYRING_SERVICE = "onesauce_companion"
ARCHIVE_PASSWORD_KEY = "archive_org_password"
CABINET_TOKEN_KEY = "cabinet_link_token"


class SettingsStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or _default_config_dir()
        self.config_file = self.config_dir / "settings.json"

    def load(self) -> AppSettings:
        source_file = self.config_file if self.config_file.exists() else _legacy_settings_file(self.config_dir)
        if source_file is None or not source_file.exists():
            return AppSettings()
        try:
            return self._load_from_file(source_file)
        except (ValueError, TypeError, KeyError, OSError):
            LOGGER.exception("Failed to load settings from %s; starting with defaults.", source_file)
            self._quarantine_corrupt_file(source_file)
            return AppSettings(archive_password=self._get_keyring_password())

    def _load_from_file(self, source_file: Path) -> AppSettings:
        data = json.loads(source_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Settings file does not contain a JSON object.")
        legacy_password = str(data.get("archive_password", ""))
        archive_password = self._load_archive_password(legacy_password)
        if legacy_password:
            self._remove_plaintext_archive_password(source_file, data)
        return AppSettings(
            install_target=str(data.get("install_target", "")),
            bitlcd_target=str(data.get("bitlcd_target", "")),
            downloads_path=str(data.get("downloads_path", str(default_downloads_dir()))),
            downloads_retention_mode=str(data.get("downloads_retention_mode", DEFAULT_RETENTION_MODE)),
            downloads_retention_days=max(0, int(data.get("downloads_retention_days", 30))),
            downloads_retention_max_gb=max(0.1, float(data.get("downloads_retention_max_gb", 5.0))),
            auto_resume_downloads_on_start=bool(data.get("auto_resume_downloads_on_start", False)),
            auto_install_components_after_download=bool(data.get("auto_install_components_after_download", True)),
            segmented_downloads_enabled=bool(data.get("segmented_downloads_enabled", False)),
            segmented_download_min_size_mb=max(1, int(data.get("segmented_download_min_size_mb", 512))),
            segmented_download_segments=max(2, min(8, int(data.get("segmented_download_segments", 4)))),
            archive_email=str(data.get("archive_email", "")),
            archive_password=archive_password,
            parallel_downloads=max(1, int(data.get("parallel_downloads", 2))),
            window_width=max(1000, int(data.get("window_width", 1280))),
            window_height=max(720, int(data.get("window_height", 980))),
            window_x=_optional_int(data.get("window_x")),
            window_y=_optional_int(data.get("window_y")),
            log_wrap_lines=bool(data.get("log_wrap_lines", False)),
            log_reverse_order=bool(data.get("log_reverse_order", True)),
            log_highlight_colors=_load_log_highlight_colors(data.get("log_highlight_colors", {})),
            queue_entries=_load_queue_entries(data.get("queue_entries", [])),
            downloads_operations=_load_downloads_operations(data.get("downloads_operations", [])),
            downloads_column_order=_load_downloads_column_order(data.get("downloads_column_order", [])),
            downloads_column_widths=_load_downloads_column_widths(data.get("downloads_column_widths", {})),
            downloads_sort=_load_downloads_sort(data.get("downloads_sort", [])),
            enable_themes_preview=bool(data.get("enable_themes_preview", False)),
            theme_selected_theme=str(data.get("theme_selected_theme", "")),
            theme_selected_collection=str(data.get("theme_selected_collection", "")),
            theme_selected_game_key=_load_string_list(data.get("theme_selected_game_key", [])),
            theme_show_wireframes=bool(data.get("theme_show_wireframes", True)),
            theme_show_media=bool(data.get("theme_show_media", True)),
            theme_show_text=bool(data.get("theme_show_text", True)),
            cabinet_host=str(data.get("cabinet_host", "")),
            cabinet_device_id=str(data.get("cabinet_device_id", "")),
            cabinet_name=str(data.get("cabinet_name", "")),
        )

    def save(self, settings: AppSettings) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._save_archive_password(settings.archive_password)
        data = asdict(settings)
        data.pop("archive_password", None)
        self.config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _quarantine_corrupt_file(self, source_file: Path) -> None:
        backup_path = source_file.with_name(source_file.name + ".corrupt")
        try:
            source_file.replace(backup_path)
        except OSError:
            LOGGER.exception("Failed to move corrupt settings file %s aside.", source_file)
            return
        LOGGER.warning("Corrupt settings file moved to %s.", backup_path)

    def _load_archive_password(self, legacy_password: str) -> str:
        stored_password = self._get_keyring_password()
        if stored_password:
            return stored_password
        if legacy_password and self._set_keyring_password(legacy_password):
            return legacy_password
        return legacy_password

    def _save_archive_password(self, password: str) -> None:
        if password:
            self._set_keyring_password(password)
            return
        self._delete_keyring_password()

    def _get_keyring_password(self) -> str:
        try:
            return keyring.get_password(KEYRING_SERVICE, ARCHIVE_PASSWORD_KEY) or ""
        except KeyringError:
            LOGGER.exception("Failed to read Archive.org password from keyring.")
            return ""

    def _set_keyring_password(self, password: str) -> bool:
        try:
            keyring.set_password(KEYRING_SERVICE, ARCHIVE_PASSWORD_KEY, password)
        except KeyringError:
            LOGGER.exception("Failed to store Archive.org password in keyring.")
            return False
        return True

    def _delete_keyring_password(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, ARCHIVE_PASSWORD_KEY)
        except PasswordDeleteError:
            pass  # No stored password to delete.
        except KeyringError:
            LOGGER.exception("Failed to delete Archive.org password from keyring.")

    # ---- cabinet link token (keyring, mirrors the archive password pattern) ----

    def get_cabinet_token(self) -> str:
        try:
            return keyring.get_password(KEYRING_SERVICE, CABINET_TOKEN_KEY) or ""
        except KeyringError:
            LOGGER.exception("Failed to read the cabinet link token from keyring.")
            return ""

    def set_cabinet_token(self, token: str) -> bool:
        if not token:
            self.delete_cabinet_token()
            return True
        try:
            keyring.set_password(KEYRING_SERVICE, CABINET_TOKEN_KEY, token)
        except KeyringError:
            LOGGER.exception("Failed to store the cabinet link token in keyring.")
            return False
        return True

    def delete_cabinet_token(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, CABINET_TOKEN_KEY)
        except PasswordDeleteError:
            pass  # No stored token to delete.
        except KeyringError:
            LOGGER.exception("Failed to delete the cabinet link token from keyring.")

    def _remove_plaintext_archive_password(self, source_file: Path, data: dict[str, object]) -> None:
        if "archive_password" not in data:
            return
        sanitized = dict(data)
        sanitized.pop("archive_password", None)
        source_file.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")


def _default_config_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / ".onesauce_companion"


def _legacy_settings_file(config_dir: Path) -> Path | None:
    for legacy_dir in _legacy_config_dirs(config_dir.parent):
        candidate = legacy_dir / "settings.json"
        if candidate.exists():
            return candidate
    return None


def _legacy_config_dirs(parent_dir: Path) -> tuple[Path, ...]:
    return (
        parent_dir / ".onesauce",
        parent_dir / ".onesauce_updater",
    )


def _load_queue_entries(raw_entries: object) -> list[dict[str, object]]:
    if not isinstance(raw_entries, list):
        return []
    queue_entries: list[dict[str, object]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("component_key", "")).strip()
        source_label = str(entry.get("source_label", "")).strip()
        target_path = str(entry.get("target_path", "")).strip()
        allow_installed = bool(entry.get("allow_installed", False))
        download_only = bool(entry.get("download_only", False))
        status = str(entry.get("status", "Queued")).strip() or "Queued"
        if not key or not target_path:
            continue
        queue_entries.append(
            {
                "component_key": key,
                "source_label": source_label,
                "target_path": target_path,
                "allow_installed": allow_installed,
                "download_only": download_only,
                "status": status,
            }
        )
    return queue_entries


def _load_log_highlight_colors(raw_colors: object) -> dict[str, str]:
    if not isinstance(raw_colors, dict):
        return {}
    colors: dict[str, str] = {}
    for key, value in raw_colors.items():
        color_key = str(key).strip()
        color_value = str(value).strip()
        if not color_key or not color_value:
            continue
        colors[color_key] = color_value
    return colors


def _load_downloads_operations(raw_entries: object) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list):
        return []
    operations: list[dict[str, str]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        component_key = str(entry.get("component_key", "")).strip()
        kind = str(entry.get("kind", "")).strip()
        status = str(entry.get("status", "")).strip()
        if not component_key or not kind or not status:
            continue
        operations.append(
            {
                "component_key": component_key,
                "kind": kind,
                "status": status,
            }
        )
    return operations



def _load_downloads_column_order(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    order = [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()]
    if len(order) != len(raw) or len(order) != len(set(order)):
        return []
    return order


def _load_downloads_column_widths(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    widths: dict[str, int] = {}
    for key, value in raw.items():
        column_key = str(key).strip()
        if not column_key or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        width = int(value)
        if width > 0:
            widths[column_key] = width
    return widths


def _load_downloads_sort(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        column = str(entry.get("column", "")).strip()
        direction = str(entry.get("direction", "")).strip().lower()
        if not column or column in seen or direction not in {"asc", "desc"}:
            continue
        seen.add(column)
        entries.append({"column": column, "direction": direction})
    return entries


def _load_string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str)]


def _optional_int(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
