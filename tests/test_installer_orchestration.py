from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.control import OperationCancelledError, OperationController
from onesauce_companion.services.installer import Installer
from onesauce_companion.services.state import InstallState


def _spec(name: str = "Component", version: str = "v1.0b1") -> ComponentSpec:
    filename = f"{name} {version}.zip"
    return ComponentSpec(
        key=name.lower(),
        display_name=name,
        archive_item="test-item",
        filename=filename,
        download_url=f"https://archive.org/download/test-item/{filename}",
        install_root=name,
        version_file_relpath=f"{name}/{name} version.txt",
        available_version=version,
    )


def _write_cached_archive(cache_dir: Path, spec: ComponentSpec, payload: bytes = b"data") -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / spec.cache_name
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(spec.version_file_relpath, f"Build {spec.available_version}".encode("utf-16"))
        archive.writestr(f"{spec.install_root}/payload.bin", payload)
    return archive_path


def _installer(tmp_path: Path, *specs: ComponentSpec) -> tuple[Installer, Path]:
    cache_dir = tmp_path / "cache"
    for spec in specs:
        _write_cached_archive(cache_dir, spec)
    return Installer(specs, cache_dir=cache_dir), tmp_path / "target"


def test_install_required_installs_cached_component(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)
    statuses: list[tuple[str, str]] = []

    report = installer.install_required(target, status_callback=lambda key, status: statuses.append((key, status)))

    assert report.installed_components == [spec.key]
    assert (target / spec.install_root / "payload.bin").read_bytes() == b"data"
    assert (spec.key, "Installed") in statuses
    state = InstallState.load(target)
    assert state.versions[spec.key] == spec.available_version
    assert installer.scan_target(target)[0].status == "Installed"


def test_install_required_skips_removed_component(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)
    controller = OperationController()
    controller.skip_component(spec.key)
    statuses: list[tuple[str, str]] = []

    report = installer.install_required(
        target,
        controller=controller,
        status_callback=lambda key, status: statuses.append((key, status)),
    )

    assert report.installed_components == []
    assert (spec.key, "Removed") in statuses
    assert not (target / spec.install_root / "payload.bin").exists()


def test_install_required_pauses_component(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)
    controller = OperationController()
    controller.pause_component(spec.key)
    statuses: list[tuple[str, str]] = []

    report = installer.install_required(
        target,
        controller=controller,
        status_callback=lambda key, status: statuses.append((key, status)),
    )

    assert report.installed_components == []
    assert (spec.key, "Paused") in statuses
    assert not (target / spec.install_root / "payload.bin").exists()


def test_install_required_pause_of_one_component_does_not_block_others(tmp_path: Path) -> None:
    paused_spec = _spec("Alpha")
    active_spec = _spec("Bravo")
    installer, target = _installer(tmp_path, paused_spec, active_spec)
    controller = OperationController()
    controller.pause_component(paused_spec.key)
    statuses: list[tuple[str, str]] = []

    report = installer.install_required(
        target,
        controller=controller,
        status_callback=lambda key, status: statuses.append((key, status)),
    )

    assert report.installed_components == [active_spec.key]
    assert (paused_spec.key, "Paused") in statuses
    assert (active_spec.key, "Installed") in statuses
    assert (target / active_spec.install_root / "payload.bin").exists()
    assert not (target / paused_spec.install_root / "payload.bin").exists()


def test_install_required_raises_when_cancelled(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)
    controller = OperationController()
    controller.cancel()

    with pytest.raises(OperationCancelledError):
        installer.install_required(target, controller=controller)

    assert not (target / spec.install_root / "payload.bin").exists()


def test_install_required_is_noop_when_up_to_date_unless_forced(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)
    first = installer.install_required(target)
    assert first.installed_components == [spec.key]

    second = installer.install_required(target)
    assert second.installed_components == []
    assert second.downloaded_components == []

    forced = installer.install_required(target, force_component_keys={spec.key})
    assert forced.installed_components == [spec.key]


def test_install_required_download_only_does_not_extract(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)

    report = installer.install_required(target, download_only=True)

    assert report.downloaded_components == [spec.key]
    assert report.installed_components == []
    assert not (target / spec.install_root / "payload.bin").exists()


def test_install_required_reports_progress_phases(tmp_path: Path) -> None:
    spec = _spec()
    installer, target = _installer(tmp_path, spec)
    phases: list[str] = []

    installer.install_required(target, phase_callback=lambda progress: phases.append(progress.phase))

    assert "extract" in phases
    assert phases[-1] == "installed"
