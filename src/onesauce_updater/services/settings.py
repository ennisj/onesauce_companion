from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    install_target: str = ""
    bitlcd_target: str = ""
    archive_email: str = ""
    archive_password: str = ""
    parallel_downloads: int = 2
    window_width: int = 1280
    window_height: int = 1020


class SettingsStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or _default_config_dir()
        self.config_file = self.config_dir / "settings.json"

    def load(self) -> AppSettings:
        if not self.config_file.exists():
            return AppSettings()
        data = json.loads(self.config_file.read_text(encoding="utf-8"))
        return AppSettings(
            install_target=str(data.get("install_target", "")),
            bitlcd_target=str(data.get("bitlcd_target", "")),
            archive_email=str(data.get("archive_email", "")),
            archive_password=str(data.get("archive_password", "")),
            parallel_downloads=max(1, int(data.get("parallel_downloads", 2))),
            window_width=max(1000, int(data.get("window_width", 1280))),
            window_height=max(960, int(data.get("window_height", 1020))),
        )

    def save(self, settings: AppSettings) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def _default_config_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / ".onesauce"
