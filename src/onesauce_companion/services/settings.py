from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from onesauce_companion.services.download_cache import DEFAULT_RETENTION_MODE, default_downloads_dir


@dataclass
class AppSettings:
    install_target: str = ""
    bitlcd_target: str = ""
    downloads_path: str = str(default_downloads_dir())
    downloads_retention_mode: str = DEFAULT_RETENTION_MODE
    downloads_retention_days: int = 30
    downloads_retention_max_gb: float = 5.0
    auto_resume_downloads_on_start: bool = False
    archive_email: str = ""
    archive_password: str = ""
    parallel_downloads: int = 2
    window_width: int = 1280
    window_height: int = 980
    window_x: int | None = None
    window_y: int | None = None
    queue_entries: list[dict[str, str]] = field(default_factory=list)


KEYRING_SERVICE = "onesauce_companion"
ARCHIVE_PASSWORD_KEY = "archive_org_password"


class SettingsStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or _default_config_dir()
        self.config_file = self.config_dir / "settings.json"

    def load(self) -> AppSettings:
        source_file = self.config_file if self.config_file.exists() else _legacy_settings_file(self.config_dir)
        if source_file is None or not source_file.exists():
            return AppSettings()
        data = json.loads(source_file.read_text(encoding="utf-8"))
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
            archive_email=str(data.get("archive_email", "")),
            archive_password=archive_password,
            parallel_downloads=max(1, int(data.get("parallel_downloads", 2))),
            window_width=max(1000, int(data.get("window_width", 1280))),
            window_height=max(720, int(data.get("window_height", 980))),
            window_x=_optional_int(data.get("window_x")),
            window_y=_optional_int(data.get("window_y")),
            queue_entries=_load_queue_entries(data.get("queue_entries", [])),
        )

    def save(self, settings: AppSettings) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._save_archive_password(settings.archive_password)
        data = asdict(settings)
        data.pop("archive_password", None)
        self.config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
        else:
            self._delete_keyring_password()

    def _get_keyring_password(self) -> str:
        try:
            return keyring.get_password(KEYRING_SERVICE, ARCHIVE_PASSWORD_KEY) or ""
        except KeyringError:
            return ""

    def _set_keyring_password(self, password: str) -> bool:
        try:
            keyring.set_password(KEYRING_SERVICE, ARCHIVE_PASSWORD_KEY, password)
        except KeyringError:
            return False
        return True

    def _delete_keyring_password(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, ARCHIVE_PASSWORD_KEY)
        except KeyringError:
            return

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


def _load_queue_entries(raw_entries: object) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list):
        return []
    queue_entries: list[dict[str, str]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("component_key", "")).strip()
        source_label = str(entry.get("source_label", "")).strip()
        target_path = str(entry.get("target_path", "")).strip()
        if not key or not target_path:
            continue
        queue_entries.append(
            {
                "component_key": key,
                "source_label": source_label,
                "target_path": target_path,
            }
        )
    return queue_entries



def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
