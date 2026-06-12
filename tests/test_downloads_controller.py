from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.settings import AppSettings
from onesauce_companion.ui.downloads_controller import DownloadsController, DownloadsOperationState


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _spec(name: str) -> ComponentSpec:
    return ComponentSpec(
        key=name.lower(),
        display_name=name,
        archive_item="test-item",
        filename=f"{name} v1.0b1.zip",
        download_url=f"https://archive.org/download/test-item/{name} v1.0b1.zip",
        install_root=name,
        version_file_relpath=None,
        available_version="v1.0b1",
    )


class _FakeValue:
    def __init__(self, value) -> None:
        self._value = value

    def value(self):
        return self._value

    def isChecked(self):
        return self._value


class _FakeWindow(QObject):
    """Duck-typed stand-in for the window surface DownloadsController uses."""

    def __init__(self, specs: tuple[ComponentSpec, ...] = (), parallel: int = 2, auto_resume: bool = False) -> None:
        super().__init__()
        self._specs = tuple(specs)
        self.parallel_downloads_spin = _FakeValue(parallel)
        self.auto_resume_downloads_checkbox = _FakeValue(auto_resume)
        self.auto_install_after_download_checkbox = _FakeValue(True)
        self._all_components_by_key = {spec.key: spec for spec in self._specs}
        self._downloads_status_state: dict[str, tuple[str, float]] = {}
        self._cached_download_versions: dict[str, str | None] = {}
        self._cached_downloads_installed_statuses: dict[str, object] = {}
        self.status_updates: list[tuple[str, str, float]] = []
        self.table_refreshes = 0
        self.screen_refreshes = 0

    def _all_download_specs(self) -> tuple[ComponentSpec, ...]:
        return self._specs

    def _set_downloads_status_widget(self, key: str, status: str, percent: float) -> None:
        self.status_updates.append((key, status, percent))

    def _schedule_downloads_table_refresh(self) -> None:
        self.table_refreshes += 1

    def _refresh_downloader_screen(self) -> None:
        self.screen_refreshes += 1


def _controller(window: _FakeWindow, monkeypatch) -> tuple[DownloadsController, list[str], list[str]]:
    """Controller with worker starts stubbed to record keys and occupy lanes."""
    controller = DownloadsController(window)  # type: ignore[arg-type]
    download_starts: list[str] = []
    install_starts: list[str] = []

    def fake_start_download(spec: ComponentSpec) -> None:
        download_starts.append(spec.key)
        controller._download_threads[spec.key] = object()  # type: ignore[assignment]
        controller.operations[spec.key] = DownloadsOperationState(kind="download", status="Downloading")

    def fake_start_install(spec: ComponentSpec) -> None:
        install_starts.append(spec.key)
        controller._install_key = spec.key
        controller._install_thread = object()  # type: ignore[assignment]
        controller.operations[spec.key] = DownloadsOperationState(kind="install", status="Installing")

    monkeypatch.setattr(controller, "_start_download_worker", fake_start_download)
    monkeypatch.setattr(controller, "_start_install_worker", fake_start_install)
    return controller, download_starts, install_starts


def test_schedule_respects_parallel_download_capacity(monkeypatch) -> None:
    _app()
    specs = (_spec("Alpha"), _spec("Bravo"), _spec("Charlie"))
    window = _FakeWindow(specs, parallel=2)
    controller, download_starts, _ = _controller(window, monkeypatch)
    for spec in specs:
        controller.operations[spec.key] = DownloadsOperationState(kind="download", status="Pending Download")

    controller.schedule()

    assert download_starts == ["alpha", "bravo"]
    assert controller.operations["charlie"].status == "Pending Download"


def test_schedule_runs_single_install_lane(monkeypatch) -> None:
    _app()
    specs = (_spec("Alpha"), _spec("Bravo"))
    window = _FakeWindow(specs)
    controller, _, install_starts = _controller(window, monkeypatch)
    for spec in specs:
        controller.operations[spec.key] = DownloadsOperationState(kind="install", status="Pending Install")

    controller.schedule()

    assert install_starts == ["alpha"]
    assert controller.operations["bravo"].status == "Pending Install"

    controller.schedule()
    assert install_starts == ["alpha"]  # lane still occupied


def test_queue_download_sets_pending_and_schedules(monkeypatch) -> None:
    _app()
    spec = _spec("Alpha")
    window = _FakeWindow((spec,))
    controller, download_starts, _ = _controller(window, monkeypatch)

    controller.queue_download(spec)

    assert download_starts == ["alpha"]
    assert ("alpha", "Pending Download", 0.0) in window.status_updates
    assert window.table_refreshes == 1


def test_pause_resume_and_cancel_pending_download() -> None:
    _app()
    spec = _spec("Alpha")
    window = _FakeWindow((spec,), parallel=1)
    controller = DownloadsController(window)  # type: ignore[arg-type]
    controller.operations[spec.key] = DownloadsOperationState(kind="download", status="Pending Download")

    # No lane controller yet -> pausing marks the pending operation paused.
    controller.pause_operation(spec.key, "download")
    assert controller.operations[spec.key].status == "Pending Download (Paused)"

    controller.resume_operation(spec.key)
    assert controller.operations[spec.key].status == "Pending Download"

    controller.cancel_row(spec.key)
    assert spec.key not in controller.operations
    assert window.screen_refreshes == 1


def test_serialized_operations_normalize_active_statuses() -> None:
    _app()
    specs = (_spec("Alpha"), _spec("Bravo"), _spec("Charlie"))
    window = _FakeWindow(specs)
    controller = DownloadsController(window)  # type: ignore[arg-type]
    controller.operations["alpha"] = DownloadsOperationState(kind="download", status="Downloading")
    controller.operations["bravo"] = DownloadsOperationState(kind="install", status="Installing")
    controller.operations["charlie"] = DownloadsOperationState(kind="download", status="Download Paused")

    serialized = controller.serialized_operations()

    by_key = {entry["component_key"]: entry["status"] for entry in serialized}
    assert by_key == {
        "alpha": "Pending Download",
        "bravo": "Pending Install",
        "charlie": "Download Paused",
    }


def test_load_operations_resumes_paused_when_auto_resume_enabled() -> None:
    _app()
    specs = (_spec("Alpha"), _spec("Bravo"))
    window = _FakeWindow(specs, auto_resume=True)
    controller = DownloadsController(window)  # type: ignore[arg-type]
    settings = AppSettings(
        downloads_operations=[
            {"component_key": "alpha", "kind": "download", "status": "Download Paused"},
            {"component_key": "bravo", "kind": "install", "status": "Install Paused"},
            {"component_key": "missing", "kind": "download", "status": "Pending Download"},
            {"component_key": "alpha", "kind": "bogus", "status": "Pending Download"},
        ]
    )

    controller.load_operations(settings)

    assert controller.operations["alpha"].status == "Pending Download"
    assert controller.operations["bravo"].status == "Install Paused"
    assert "missing" not in controller.operations


def test_prune_operations_drops_unknown_components() -> None:
    _app()
    window = _FakeWindow((_spec("Alpha"),))
    controller = DownloadsController(window)  # type: ignore[arg-type]
    controller.operations["alpha"] = DownloadsOperationState(kind="download", status="Pending Download")
    controller.operations["stale"] = DownloadsOperationState(kind="download", status="Pending Download")

    controller.prune_operations()

    assert set(controller.operations) == {"alpha"}
