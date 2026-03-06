from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ComponentSpec:
    key: str
    display_name: str
    archive_item: str
    filename: str
    download_url: str
    install_root: str
    version_file_relpath: str | None
    available_version: str
    required: bool = True
    release_label: str | None = None

    @property
    def cache_name(self) -> str:
        return self.filename

    @property
    def available_display(self) -> str:
        if self.release_label and self.release_label != self.available_version:
            return f"{self.available_version} ({self.release_label})"
        return self.available_version


@dataclass(frozen=True)
class ComponentStatus:
    spec: ComponentSpec
    installed_version: str | None
    available_version: str
    status: str
    detail: str


@dataclass(frozen=True)
class ArchiveInspection:
    archive_path: Path
    release_version: str | None
    embedded_version: str | None
    version_file_path: str | None
    entry_count: int


@dataclass(frozen=True)
class InstallProgress:
    component_key: str
    phase: str
    current: int
    total: int
    component_percent: int
    overall_percent: int
    detail: str
