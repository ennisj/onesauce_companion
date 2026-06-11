from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path


LOGGER = logging.getLogger(__name__)


@dataclass
class InstallState:
    versions: dict[str, str] = field(default_factory=dict)
    archive_filenames: dict[str, str] = field(default_factory=dict)
    collection_roots: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, target_dir: Path) -> "InstallState":
        path = state_file_path(target_dir)
        if not path.exists():
            path = legacy_state_file_path(target_dir)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("State file does not contain a JSON object.")
            return cls(
                versions=dict(data.get("versions", {})),
                archive_filenames=dict(data.get("archive_filenames", {})),
                collection_roots=dict(data.get("collection_roots", {})),
            )
        except (ValueError, TypeError, OSError):
            LOGGER.exception(
                "Failed to load install state from %s; version detection falls back to file scanning.", path
            )
            return cls()

    def save(self, target_dir: Path) -> None:
        path = state_file_path(target_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "versions": self.versions,
            "archive_filenames": self.archive_filenames,
            "collection_roots": self.collection_roots,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def state_dir_path(target_dir: Path) -> Path:
    return target_dir / ".onesauce_companion"


def legacy_state_dir_path(target_dir: Path) -> Path:
    return target_dir / ".onesauce_updater"


def state_file_path(target_dir: Path) -> Path:
    return state_dir_path(target_dir) / "state.json"


def legacy_state_file_path(target_dir: Path) -> Path:
    return legacy_state_dir_path(target_dir) / "state.json"


def backups_root_path(target_dir: Path) -> Path:
    return state_dir_path(target_dir) / "backups"

