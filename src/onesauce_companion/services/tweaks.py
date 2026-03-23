from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil

from onesauce_companion.services.state import backups_root_path
from onesauce_companion.services.versioning import has_nonempty_content, read_version_file


AUTOSTART_STATUS_ENABLED = "Enabled"
AUTOSTART_STATUS_NOT_ENABLED = "Not Enabled"
AUTOSTART_STATUS_PENDING = "Pending Install on next OnesaUCE Start"
MAIN_COLLECTION = "Main"


@dataclass(frozen=True)
class AutostartState:
    onesauce_installed: bool
    status: str
    autostart_dir: Path | None
    install_script_path: Path | None
    fix_script_path: Path | None
    install_script_present: bool = False
    fix_installed: bool = False


@dataclass(frozen=True)
class SettingsTweaksState:
    target_config_path: Path | None
    legends_pinball_micro_rotation_fix_enabled: bool


@dataclass(frozen=True)
class OnesaUCESettingsState:
    available: bool
    settings_path: Path | None
    values: dict[str, str]
    themes: tuple[str, ...]


def detect_autostart_state(target_dir: Path | None) -> AutostartState:
    if target_dir is None:
        return AutostartState(
            onesauce_installed=False,
            status=AUTOSTART_STATUS_NOT_ENABLED,
            autostart_dir=None,
            install_script_path=None,
            fix_script_path=None,
        )

    autostart_dir = target_dir / "autostart"
    install_script_path = target_dir / "OneSauce" / "scripter" / "00_install_autostart.sh"
    fix_script_path = autostart_dir / "00_init_menu.sh"
    onesauce_root = target_dir / "OneSauce"
    onesauce_installed = bool(
        read_version_file(onesauce_root / "OneSauce version.txt") or has_nonempty_content(onesauce_root)
    )
    if not onesauce_installed:
        return AutostartState(
            onesauce_installed=False,
            status=AUTOSTART_STATUS_NOT_ENABLED,
            autostart_dir=autostart_dir,
            install_script_path=install_script_path,
            fix_script_path=fix_script_path,
        )

    autostart_enabled = autostart_dir.exists() and autostart_dir.is_dir()
    install_script_present = install_script_path.exists()
    fix_installed = fix_script_path.exists()
    if autostart_enabled:
        status = AUTOSTART_STATUS_ENABLED
    elif install_script_present:
        status = AUTOSTART_STATUS_PENDING
    else:
        status = AUTOSTART_STATUS_NOT_ENABLED

    return AutostartState(
        onesauce_installed=True,
        status=status,
        autostart_dir=autostart_dir,
        install_script_path=install_script_path,
        fix_script_path=fix_script_path,
        install_script_present=install_script_present,
        fix_installed=fix_installed,
    )


def enable_autostart(target_dir: Path, script_source: Path) -> None:
    destination = target_dir / "OneSauce" / "scripter" / script_source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_source, destination)


def disable_autostart(target_dir: Path) -> Path | None:
    state = detect_autostart_state(target_dir)
    backup_dir: Path | None = None
    if state.autostart_dir is not None and state.autostart_dir.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = backups_root_path(target_dir) / "tweaks" / f"autostart-{timestamp}"
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(state.autostart_dir, backup_dir)
        shutil.rmtree(state.autostart_dir)
    if state.install_script_path is not None and state.install_script_path.exists():
        state.install_script_path.unlink()
    return backup_dir


def install_autostart_fix(target_dir: Path, script_source: Path) -> None:
    autostart_dir = target_dir / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_source, autostart_dir / script_source.name)


ALP_MICRO_SECTION = "# Overrides for ALP Micro"
RESOLUTION_SECTION = "# some platforms may have trouble to switch resolutions reliably. Turn this off in that case."


def detect_settings_tweaks_state(target_dir: Path | None, source_config_path: Path) -> SettingsTweaksState:
    target_config_path = None if target_dir is None else target_dir / "appdata" / "retrofe" / "settings_HA8819.conf"
    if not source_config_path.exists() or target_config_path is None or not target_config_path.exists():
        return SettingsTweaksState(
            target_config_path=target_config_path,
            legends_pinball_micro_rotation_fix_enabled=False,
        )

    required_sections = _required_settings_sections(source_config_path)
    target_sections = _read_settings_sections(target_config_path)
    enabled = all(target_sections.get(header, {}) == values for header, values in required_sections.items())
    return SettingsTweaksState(
        target_config_path=target_config_path,
        legends_pinball_micro_rotation_fix_enabled=enabled,
    )


def enable_legends_pinball_micro_rotation_fix(target_dir: Path, source_config_path: Path) -> None:
    target_config_path = target_dir / "appdata" / "retrofe" / "settings_HA8819.conf"
    target_config_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_config_path.exists():
        shutil.copy2(source_config_path, target_config_path)
        return

    lines = target_config_path.read_text(encoding="utf-8").splitlines()
    for header, values in _required_settings_sections(source_config_path).items():
        lines = _upsert_settings_section(lines, header, values)
    target_config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def detect_onesauce_settings_state(target_dir: Path | None) -> OnesaUCESettingsState:
    if target_dir is None:
        return OnesaUCESettingsState(False, None, {}, tuple())

    appdata_root = target_dir / "appdata"
    base_assets_root = target_dir / "base_assets"
    settings_path = appdata_root / "retrofe" / "settings.conf"
    if not has_nonempty_content(appdata_root) or not has_nonempty_content(base_assets_root) or not settings_path.exists():
        return OnesaUCESettingsState(False, settings_path, {}, tuple())

    values = _read_retrofe_settings(settings_path)
    values = _ensure_main_starting_collection(target_dir, values)
    themes = _installed_themes(target_dir)
    return OnesaUCESettingsState(True, settings_path, values, themes)


def update_onesauce_setting(target_dir: Path, setting_name: str, value: str) -> None:
    settings_path = target_dir / "appdata" / "retrofe" / "settings.conf"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    lines = settings_path.read_text(encoding="utf-8-sig").splitlines() if settings_path.exists() else []
    replacement = f"{setting_name} = {value}"
    matched_indexes: list[int] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("#", ";")):
            line = line[1:].strip()
        if "=" not in line:
            continue
        key, _existing = (part.strip() for part in line.split("=", 1))
        if key != setting_name:
            continue
        matched_indexes.append(index)

    if matched_indexes:
        lines[matched_indexes[0]] = replacement
        for index in reversed(matched_indexes[1:]):
            del lines[index]
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(replacement)
    settings_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _required_settings_sections(source_config_path: Path) -> dict[str, dict[str, str]]:
    source_sections = _read_settings_sections(source_config_path)
    return {
        ALP_MICRO_SECTION: source_sections.get(ALP_MICRO_SECTION, {}),
        RESOLUTION_SECTION: source_sections.get(RESOLUTION_SECTION, {}),
    }


def _read_settings_sections(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current_header: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            current_header = line
            sections.setdefault(current_header, {})
            continue
        if current_header is None or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        sections[current_header][key] = value
    return sections


def _upsert_settings_section(lines: list[str], header: str, values: dict[str, str]) -> list[str]:
    start_index = None
    end_index = len(lines)
    for index, raw_line in enumerate(lines):
        if raw_line.strip() == header:
            start_index = index
            break

    if start_index is not None:
        end_index = len(lines)
        for index in range(start_index + 1, len(lines)):
            if lines[index].strip().startswith("#"):
                end_index = index
                break
    else:
        start_index = len(lines)
        if lines and lines[-1].strip():
            lines = [*lines, ""]

    section_lines = [header, ""]
    section_lines.extend(f"{key} = {value}" for key, value in values.items())
    section_lines.append("")
    return [*lines[:start_index], *section_lines, *lines[end_index:]]


def _read_retrofe_settings(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        values[key] = value
    return values


def _installed_themes(target_dir: Path) -> tuple[str, ...]:
    layouts_root = target_dir / "base_assets" / "layouts"
    if not layouts_root.exists() or not layouts_root.is_dir():
        return tuple()
    names = [
        path.name
        for path in sorted(layouts_root.iterdir(), key=lambda item: item.name.casefold())
        if path.is_dir()
    ]
    return tuple(names)


def _ensure_main_starting_collection(target_dir: Path, values: dict[str, str]) -> dict[str, str]:
    if values.get("firstCollection", "").strip() == MAIN_COLLECTION:
        return values

    update_onesauce_setting(target_dir, "firstCollection", MAIN_COLLECTION)
    normalized = dict(values)
    normalized["firstCollection"] = MAIN_COLLECTION
    return normalized
