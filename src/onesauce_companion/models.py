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
    size_label: str | None = None
    size_bytes: int | None = None
    component_type: str | None = None
    versionless: bool = False

    @property
    def cache_name(self) -> str:
        return self.filename

    @property
    def available_display(self) -> str:
        return self.available_version

    @property
    def size_display(self) -> str:
        return self.size_label or "Unknown"


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
    component_percent: float
    overall_percent: int
    detail: str


@dataclass
class QueueEntry:
    spec: ComponentSpec
    source_label: str
    target_path: str
    status: str = "Queued"
    percent: float = 0.0
