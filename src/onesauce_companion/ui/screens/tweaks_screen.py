"""Tweaks screen: autostart, settings tweaks, OnesaUCE settings."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.tweaks import (
    AUTOSTART_STATUS_ENABLED,
    AUTOSTART_STATUS_NOT_ENABLED,
    AUTOSTART_STATUS_PENDING,
    detect_onesauce_settings_state,
    detect_settings_tweaks_state,
    disable_autostart,
    enable_autostart,
    ensure_main_starting_collection,
    enable_legends_pinball_micro_rotation_fix,
    install_autostart_fix,
    update_onesauce_setting,
)
from onesauce_companion.ui._utils import (
    _conf_dir,
    _default_video_value_to_percent,
    _is_checked_state,
    _percent_to_default_video_value,
    _scripts_dir,
    build_screen_header_row,
)

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_tweaks_screen(self: "MainWindow") -> QWidget:
    container = QScrollArea()
    container.setWidgetResizable(True)
    container.setFrameShape(QFrame.Shape.NoFrame)
    container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    screen = QWidget()
    container.setWidget(screen)
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 12, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("OnesaUCE Settings"))

    autostart_group = QGroupBox("Autostart")
    autostart_layout = QVBoxLayout(autostart_group)
    autostart_layout.setSpacing(12)

    firmware_warning = QLabel(
        "Autostart should only be set if you are running Firmware versions 5.68 or 5.70. "
        "Do not enable this with Firmware version 1.0.17, it will prevent your cabinet from starting up."
    )
    firmware_warning.setWordWrap(True)
    firmware_warning.setObjectName("autostartFirmwareWarning")
    autostart_layout.addWidget(firmware_warning)

    self.tweaks_autostart_warning = self._build_target_warning(
        "The OnesaUCE base component must first be installed before Autostart can be configured."
    )
    autostart_layout.addWidget(self.tweaks_autostart_warning)

    self.tweaks_autostart_status_row = QWidget()
    status_row_layout = QHBoxLayout(self.tweaks_autostart_status_row)
    status_row_layout.setContentsMargins(0, 0, 0, 0)
    status_row_layout.setSpacing(8)
    status_row_layout.addWidget(QLabel("Autostart Status:"))
    self.tweaks_autostart_status_value = QLabel(AUTOSTART_STATUS_NOT_ENABLED)
    self.tweaks_autostart_status_value.setObjectName("sidebarVersion")
    status_row_layout.addWidget(self.tweaks_autostart_status_value)
    status_row_layout.addStretch(1)
    autostart_layout.addWidget(self.tweaks_autostart_status_row)

    self.tweaks_autostart_action_row = QWidget()
    action_row_layout = QHBoxLayout(self.tweaks_autostart_action_row)
    action_row_layout.setContentsMargins(0, 0, 0, 0)
    action_row_layout.setSpacing(10)
    self.tweaks_autostart_primary_button = QPushButton("Enable Autostart")
    self.tweaks_autostart_primary_button.setMinimumWidth(200)
    self.tweaks_autostart_primary_button.clicked.connect(self._handle_autostart_primary_action)
    action_row_layout.addWidget(self.tweaks_autostart_primary_button)
    action_row_layout.addStretch(1)
    autostart_layout.addWidget(self.tweaks_autostart_action_row)

    self.tweaks_autostart_fix_intro = QLabel(
        "Autostart may cause certain Legends cabinets to freeze during startup. If so, you can enable the fix for it."
    )
    self.tweaks_autostart_fix_intro.setWordWrap(True)
    autostart_layout.addWidget(self.tweaks_autostart_fix_intro)

    self.tweaks_autostart_fix_button = QPushButton("Install Freeze Fix")
    self.tweaks_autostart_fix_button.setMinimumWidth(160)
    self.tweaks_autostart_fix_button.clicked.connect(self._handle_install_autostart_fix)
    autostart_layout.addWidget(self.tweaks_autostart_fix_button, 0, Qt.AlignmentFlag.AlignLeft)

    self.tweaks_autostart_fix_disabled_note = QLabel("Autostart must first be enabled before the fix can be applied")
    self.tweaks_autostart_fix_disabled_note.setWordWrap(True)
    self.tweaks_autostart_fix_disabled_note.hide()
    autostart_layout.addWidget(self.tweaks_autostart_fix_disabled_note)

    self.tweaks_autostart_fix_installed_note = QLabel("The fix has been installed")
    self.tweaks_autostart_fix_installed_note.setWordWrap(True)
    self.tweaks_autostart_fix_installed_note.hide()
    autostart_layout.addWidget(self.tweaks_autostart_fix_installed_note)

    self.tweaks_autostart_fix_pending_note = QLabel(
        "OnesaUCE must first be started once with Autostart Enabled.\n"
        "If OnesaUCE starts up successfully, there is no need to install the fix."
    )
    self.tweaks_autostart_fix_pending_note.setWordWrap(True)
    self.tweaks_autostart_fix_pending_note.hide()
    autostart_layout.addWidget(self.tweaks_autostart_fix_pending_note)

    layout.addWidget(autostart_group)

    settings_tweaks_group = QGroupBox("Settings Tweaks")
    settings_tweaks_layout = QVBoxLayout(settings_tweaks_group)
    settings_tweaks_layout.setSpacing(12)
    self.tweaks_legends_micro_fix_checkbox = QCheckBox()
    self.tweaks_legends_micro_fix_checkbox.stateChanged.connect(self._handle_legends_micro_fix_toggled)
    self.tweaks_legends_micro_fix_row = QWidget()
    legends_micro_fix_layout = QHBoxLayout(self.tweaks_legends_micro_fix_row)
    legends_micro_fix_layout.setContentsMargins(0, 0, 0, 0)
    legends_micro_fix_layout.setSpacing(10)
    legends_micro_fix_layout.addWidget(self.tweaks_legends_micro_fix_checkbox)
    legends_micro_fix_layout.addWidget(QLabel("Enable Legends Pinball Micro Rotation Fix"))
    legends_micro_fix_layout.addStretch(1)
    settings_tweaks_layout.addWidget(self.tweaks_legends_micro_fix_row)
    layout.addWidget(settings_tweaks_group)

    onesauce_settings_group = QGroupBox("OnesaUCE Settings")
    onesauce_settings_layout = QGridLayout(onesauce_settings_group)
    onesauce_settings_layout.setHorizontalSpacing(12)
    onesauce_settings_layout.setVerticalSpacing(10)
    onesauce_settings_layout.setColumnStretch(1, 1)

    self.tweaks_onesauce_settings_warning = self._build_target_warning(
        "The appdata and base_assets Base Components must first be installed before settings can be modified."
    )
    onesauce_settings_layout.addWidget(self.tweaks_onesauce_settings_warning, 0, 0, 1, 2)

    self.tweaks_remember_menu_row = QWidget()
    remember_menu_layout = QHBoxLayout(self.tweaks_remember_menu_row)
    remember_menu_layout.setContentsMargins(0, 0, 0, 0)
    remember_menu_layout.setSpacing(10)
    self.tweaks_remember_menu_checkbox = QCheckBox()
    self.tweaks_remember_menu_checkbox.stateChanged.connect(self._handle_remember_menu_toggled)
    remember_menu_layout.addWidget(self.tweaks_remember_menu_checkbox)
    remember_menu_layout.addWidget(QLabel("Remember the last highlighted menu when re-entering a menu"))
    remember_menu_layout.addStretch(1)
    onesauce_settings_layout.addWidget(self.tweaks_remember_menu_row, 1, 0, 1, 2)

    self.tweaks_write_launcher_log_row = QWidget()
    write_launcher_log_layout = QHBoxLayout(self.tweaks_write_launcher_log_row)
    write_launcher_log_layout.setContentsMargins(0, 0, 0, 0)
    write_launcher_log_layout.setSpacing(10)
    self.tweaks_write_launcher_log_checkbox = QCheckBox()
    self.tweaks_write_launcher_log_checkbox.stateChanged.connect(self._handle_write_launcher_log_toggled)
    write_launcher_log_layout.addWidget(self.tweaks_write_launcher_log_checkbox)
    write_launcher_log_layout.addWidget(QLabel("Log output from game launcher"))
    write_launcher_log_layout.addStretch(1)
    onesauce_settings_layout.addWidget(self.tweaks_write_launcher_log_row, 2, 0, 1, 2)

    self.tweaks_video_enable_row = QWidget()
    video_enable_layout = QHBoxLayout(self.tweaks_video_enable_row)
    video_enable_layout.setContentsMargins(0, 0, 0, 0)
    video_enable_layout.setSpacing(10)
    self.tweaks_video_enable_checkbox = QCheckBox()
    self.tweaks_video_enable_checkbox.stateChanged.connect(self._handle_video_enable_toggled)
    video_enable_layout.addWidget(self.tweaks_video_enable_checkbox)
    video_enable_layout.addWidget(QLabel("Enable Video Playback"))
    video_enable_layout.addStretch(1)
    onesauce_settings_layout.addWidget(self.tweaks_video_enable_row, 3, 0, 1, 2)

    self.tweaks_auto_scan_collections_row = QWidget()
    auto_scan_collections_layout = QHBoxLayout(self.tweaks_auto_scan_collections_row)
    auto_scan_collections_layout.setContentsMargins(0, 0, 0, 0)
    auto_scan_collections_layout.setSpacing(10)
    self.tweaks_auto_scan_collections_checkbox = QCheckBox()
    self.tweaks_auto_scan_collections_checkbox.stateChanged.connect(self._handle_auto_scan_collections_toggled)
    auto_scan_collections_layout.addWidget(self.tweaks_auto_scan_collections_checkbox)
    auto_scan_collections_layout.addWidget(QLabel("Auto Scan Collections on Startup (longer startup time)"))
    auto_scan_collections_layout.addStretch(1)
    onesauce_settings_layout.addWidget(self.tweaks_auto_scan_collections_row, 4, 0, 1, 2)

    self.tweaks_default_theme_label = QLabel("Default Theme")
    self.tweaks_default_theme_combo = QComboBox()
    self.tweaks_default_theme_combo.currentIndexChanged.connect(self._handle_default_theme_changed)
    onesauce_settings_layout.addWidget(self.tweaks_default_theme_label, 5, 0)
    onesauce_settings_layout.addWidget(self.tweaks_default_theme_combo, 5, 1)

    self.tweaks_video_loop_label = QLabel("Number of video loops (0 = continuous)")
    self.tweaks_video_loop_edit = QLineEdit()
    self.tweaks_video_loop_edit.setMaxLength(3)
    self.tweaks_video_loop_edit.setFixedWidth(72)
    self.tweaks_video_loop_edit.setValidator(QIntValidator(0, 999, self))
    self.tweaks_video_loop_edit.editingFinished.connect(self._handle_video_loop_changed)
    onesauce_settings_layout.addWidget(self.tweaks_video_loop_label, 6, 0)
    onesauce_settings_layout.addWidget(self.tweaks_video_loop_edit, 6, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)

    self.tweaks_attract_mode_time_label = QLabel("Seconds before entering Attract Mode (0 to disable)")
    self.tweaks_attract_mode_time_edit = QLineEdit()
    self.tweaks_attract_mode_time_edit.setMaxLength(3)
    self.tweaks_attract_mode_time_edit.setFixedWidth(72)
    self.tweaks_attract_mode_time_edit.setValidator(QIntValidator(0, 999, self))
    self.tweaks_attract_mode_time_edit.editingFinished.connect(self._handle_attract_mode_time_changed)
    onesauce_settings_layout.addWidget(self.tweaks_attract_mode_time_label, 7, 0)
    onesauce_settings_layout.addWidget(self.tweaks_attract_mode_time_edit, 7, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)

    self.tweaks_attract_mode_next_time_label = QLabel("Seconds between items in Attract Mode")
    self.tweaks_attract_mode_next_time_edit = QLineEdit()
    self.tweaks_attract_mode_next_time_edit.setMaxLength(3)
    self.tweaks_attract_mode_next_time_edit.setFixedWidth(72)
    self.tweaks_attract_mode_next_time_edit.setValidator(QIntValidator(0, 999, self))
    self.tweaks_attract_mode_next_time_edit.editingFinished.connect(self._handle_attract_mode_next_time_changed)
    onesauce_settings_layout.addWidget(self.tweaks_attract_mode_next_time_label, 8, 0)
    onesauce_settings_layout.addWidget(self.tweaks_attract_mode_next_time_edit, 8, 1, 1, 1, Qt.AlignmentFlag.AlignLeft)

    self.tweaks_default_video_value_label = QLabel("Default Video Volume")
    self.tweaks_default_video_value_row = QWidget()
    default_video_value_layout = QHBoxLayout(self.tweaks_default_video_value_row)
    default_video_value_layout.setContentsMargins(0, 0, 0, 0)
    default_video_value_layout.setSpacing(10)
    self.tweaks_default_video_value_slider = QSlider(Qt.Orientation.Horizontal)
    self.tweaks_default_video_value_slider.setRange(0, 100)
    self.tweaks_default_video_value_slider.valueChanged.connect(self._handle_default_video_value_changed)
    self.tweaks_default_video_value_percent_label = QLabel("0%")
    self.tweaks_default_video_value_percent_label.setMinimumWidth(48)
    default_video_value_layout.addWidget(self.tweaks_default_video_value_slider, stretch=1)
    default_video_value_layout.addWidget(self.tweaks_default_video_value_percent_label)
    onesauce_settings_layout.addWidget(self.tweaks_default_video_value_label, 9, 0)
    onesauce_settings_layout.addWidget(self.tweaks_default_video_value_row, 9, 1)

    layout.addWidget(onesauce_settings_group)
    layout.addStretch(1)
    return container


def refresh_tweaks_screen(self: "MainWindow") -> None:
    state = self._autostart_state()
    target_dir = self._target_dir()
    settings_tweaks_state = detect_settings_tweaks_state(target_dir, _conf_dir() / "settings_HA8819.conf")
    if ensure_main_starting_collection(target_dir):
        self._push_status_message("Reset OnesaUCE starting collection to Main (required by OnesaUCE).")
    onesauce_settings_state = detect_onesauce_settings_state(target_dir)
    available = state.onesauce_installed
    self.tweaks_autostart_warning.setVisible(not available)
    self.tweaks_autostart_status_row.setVisible(available)
    self.tweaks_autostart_action_row.setVisible(available)
    self.tweaks_autostart_fix_intro.setVisible(available)
    self.tweaks_autostart_fix_button.setVisible(available)
    if not available:
        self.tweaks_autostart_fix_disabled_note.hide()
        self.tweaks_autostart_fix_installed_note.hide()
        self.tweaks_autostart_fix_pending_note.hide()
        return

    self.tweaks_autostart_status_value.setText(state.status)
    if state.status == AUTOSTART_STATUS_NOT_ENABLED:
        self.tweaks_autostart_primary_button.setText("Enable Autostart")
        self.tweaks_autostart_primary_button.setEnabled(True)
    elif state.status == AUTOSTART_STATUS_ENABLED:
        self.tweaks_autostart_primary_button.setText("Disable Autostart")
        self.tweaks_autostart_primary_button.setEnabled(True)
    else:
        self.tweaks_autostart_primary_button.setText("Pending...")
        self.tweaks_autostart_primary_button.setEnabled(False)

    fix_button_enabled = state.status == AUTOSTART_STATUS_ENABLED and not state.fix_installed
    self.tweaks_autostart_fix_button.setEnabled(fix_button_enabled)
    self.tweaks_autostart_fix_disabled_note.setVisible(state.status == AUTOSTART_STATUS_NOT_ENABLED)
    self.tweaks_autostart_fix_installed_note.setVisible(state.fix_installed)
    self.tweaks_autostart_fix_pending_note.setVisible(state.status == AUTOSTART_STATUS_PENDING)
    self.tweaks_legends_micro_fix_checkbox.blockSignals(True)
    self.tweaks_legends_micro_fix_checkbox.setChecked(settings_tweaks_state.legends_pinball_micro_rotation_fix_enabled)
    self.tweaks_legends_micro_fix_checkbox.setEnabled(
        target_dir is not None and not settings_tweaks_state.legends_pinball_micro_rotation_fix_enabled
    )
    self.tweaks_legends_micro_fix_checkbox.blockSignals(False)

    self._loading_tweaks_settings = True
    try:
        settings_available = onesauce_settings_state.available
        self.tweaks_onesauce_settings_warning.setVisible(not settings_available)
        self.tweaks_default_theme_label.setVisible(settings_available)
        self.tweaks_default_theme_combo.setVisible(settings_available)
        self.tweaks_remember_menu_row.setVisible(settings_available)
        self.tweaks_write_launcher_log_row.setVisible(settings_available)
        self.tweaks_video_enable_row.setVisible(settings_available)
        self.tweaks_auto_scan_collections_row.setVisible(settings_available)
        self.tweaks_video_loop_label.setVisible(settings_available)
        self.tweaks_video_loop_edit.setVisible(settings_available)
        self.tweaks_attract_mode_time_label.setVisible(settings_available)
        self.tweaks_attract_mode_time_edit.setVisible(settings_available)
        self.tweaks_attract_mode_next_time_label.setVisible(settings_available)
        self.tweaks_attract_mode_next_time_edit.setVisible(settings_available)
        self.tweaks_default_video_value_label.setVisible(settings_available)
        self.tweaks_default_video_value_row.setVisible(settings_available)
        self.tweaks_default_theme_combo.clear()
        if settings_available:
            for theme in onesauce_settings_state.themes:
                self.tweaks_default_theme_combo.addItem(theme)
            current_theme = onesauce_settings_state.values.get("layout", "")
            if current_theme and self.tweaks_default_theme_combo.findText(current_theme) == -1:
                self.tweaks_default_theme_combo.addItem(current_theme)
            if current_theme:
                self.tweaks_default_theme_combo.setCurrentIndex(
                    max(0, self.tweaks_default_theme_combo.findText(current_theme))
                )

            self.tweaks_remember_menu_checkbox.setChecked(
                onesauce_settings_state.values.get("rememberMenu", "").strip().casefold() == "yes"
            )
            self.tweaks_write_launcher_log_checkbox.setChecked(
                onesauce_settings_state.values.get("writeLauncherLog", "").strip().casefold() == "yes"
            )
            self.tweaks_video_enable_checkbox.setChecked(
                onesauce_settings_state.values.get("videoEnable", "").strip().casefold() == "yes"
            )
            self.tweaks_auto_scan_collections_checkbox.setChecked(
                onesauce_settings_state.values.get("autoScanCollections", "").strip().casefold() == "true"
            )
            current_video_loop = onesauce_settings_state.values.get("videoLoop", "0").strip() or "0"
            self._last_video_loop_value = current_video_loop
            self.tweaks_video_loop_edit.setText(current_video_loop)
            current_attract_mode_time = onesauce_settings_state.values.get("attractModeTime", "0").strip() or "0"
            self._last_attract_mode_time_value = current_attract_mode_time
            self.tweaks_attract_mode_time_edit.setText(current_attract_mode_time)
            current_attract_mode_next_time = onesauce_settings_state.values.get("attractModeNextTime", "0").strip() or "0"
            self._last_attract_mode_next_time_value = current_attract_mode_next_time
            self.tweaks_attract_mode_next_time_edit.setText(current_attract_mode_next_time)
            slider_value = _default_video_value_to_percent(onesauce_settings_state.values.get("defaultVolume", "0"))
            self.tweaks_default_video_value_slider.setValue(slider_value)
            self.tweaks_default_video_value_percent_label.setText(f"{slider_value}%")
        else:
            self.tweaks_remember_menu_checkbox.setChecked(False)
            self.tweaks_write_launcher_log_checkbox.setChecked(False)
            self.tweaks_video_enable_checkbox.setChecked(False)
            self.tweaks_auto_scan_collections_checkbox.setChecked(False)
            self._last_video_loop_value = "0"
            self._last_attract_mode_time_value = "0"
            self._last_attract_mode_next_time_value = "0"
            self.tweaks_video_loop_edit.clear()
            self.tweaks_attract_mode_time_edit.clear()
            self.tweaks_attract_mode_next_time_edit.clear()
            self.tweaks_default_video_value_slider.setValue(0)
            self.tweaks_default_video_value_percent_label.setText("0%")
    finally:
        self._loading_tweaks_settings = False


def handle_autostart_primary_action(self: "MainWindow") -> None:
    state = self._autostart_state()
    target_dir = self._target_dir()
    if target_dir is None or not state.onesauce_installed:
        self._refresh_tweaks_screen()
        return

    if state.status == AUTOSTART_STATUS_NOT_ENABLED:
        script_source = _scripts_dir() / "00_install_autostart.sh"
        if not script_source.exists():
            QMessageBox.critical(self, "Autostart unavailable", f"Missing script: {script_source}")
            return
        self.tweaks_autostart_primary_button.setText("Pending...")
        self.tweaks_autostart_primary_button.setEnabled(False)
        QApplication.processEvents()
        enable_autostart(target_dir, script_source)
        self._push_status_message("Autostart will be enabled on next OnesaUCE start")
        self._refresh_tweaks_screen()
        return

    if state.status == AUTOSTART_STATUS_ENABLED:
        confirm = QMessageBox.question(
            self,
            "Disable Autostart",
            "Disable Autostart and remove the current autostart folder? A backup will be created first.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        backup_dir = disable_autostart(target_dir)
        if backup_dir is not None:
            self._push_status_message(f"Autostart disabled. Backup stored in {backup_dir}")
        else:
            self._push_status_message("Autostart disabled")
        self._refresh_tweaks_screen()


def handle_install_autostart_fix(self: "MainWindow") -> None:
    state = self._autostart_state()
    target_dir = self._target_dir()
    if target_dir is None or state.status != AUTOSTART_STATUS_ENABLED or state.fix_installed:
        self._refresh_tweaks_screen()
        return

    script_source = _scripts_dir() / "00_init_menu.sh"
    if not script_source.exists():
        QMessageBox.critical(self, "Fix unavailable", f"Missing script: {script_source}")
        return
    install_autostart_fix(target_dir, script_source)
    self._push_status_message("Autostart fix installed")
    self._refresh_tweaks_screen()


def handle_legends_micro_fix_toggled(self: "MainWindow", state: int) -> None:
    if not _is_checked_state(state):
        self.tweaks_legends_micro_fix_checkbox.blockSignals(True)
        self.tweaks_legends_micro_fix_checkbox.setChecked(
            detect_settings_tweaks_state(self._target_dir(), _conf_dir() / "settings_HA8819.conf").legends_pinball_micro_rotation_fix_enabled
        )
        self.tweaks_legends_micro_fix_checkbox.blockSignals(False)
        return

    target_dir = self._target_dir()
    if target_dir is None:
        self._refresh_tweaks_screen()
        return

    source_config_path = _conf_dir() / "settings_HA8819.conf"
    if not source_config_path.exists():
        QMessageBox.critical(self, "Settings tweak unavailable", f"Missing config: {source_config_path}")
        self._refresh_tweaks_screen()
        return

    enable_legends_pinball_micro_rotation_fix(target_dir, source_config_path)
    self._push_status_message("Legends Pinball Micro rotation fix enabled")
    self._refresh_tweaks_screen()


def handle_default_theme_changed(self: "MainWindow", index: int) -> None:
    if self._loading_tweaks_settings or index < 0:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    value = self.tweaks_default_theme_combo.currentText().strip()
    if not value:
        return
    update_onesauce_setting(target_dir, "layout", value)
    self._push_status_message("Default theme updated")


def handle_remember_menu_toggled(self: "MainWindow", state: int) -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    update_onesauce_setting(target_dir, "rememberMenu", "yes" if _is_checked_state(state) else "no")
    self._push_status_message("Remember menu setting updated")


def handle_write_launcher_log_toggled(self: "MainWindow", state: int) -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    update_onesauce_setting(target_dir, "writeLauncherLog", "yes" if _is_checked_state(state) else "no")
    self._push_status_message("Launcher log setting updated")


def handle_video_enable_toggled(self: "MainWindow", state: int) -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    update_onesauce_setting(target_dir, "videoEnable", "yes" if _is_checked_state(state) else "no")
    self._push_status_message("Video playback setting updated")


def handle_video_loop_changed(self: "MainWindow") -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    value = self.tweaks_video_loop_edit.text().strip()
    if not value:
        self.tweaks_video_loop_edit.setText(self._last_video_loop_value)
        return
    update_onesauce_setting(target_dir, "videoLoop", value)
    self._last_video_loop_value = value
    self._push_status_message("Video loop setting updated")


def handle_auto_scan_collections_toggled(self: "MainWindow", state: int) -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    update_onesauce_setting(target_dir, "autoScanCollections", "true" if _is_checked_state(state) else "false")
    self._push_status_message("Auto scan collections setting updated")


def handle_attract_mode_time_changed(self: "MainWindow") -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    value = self.tweaks_attract_mode_time_edit.text().strip()
    if not value:
        self.tweaks_attract_mode_time_edit.setText(self._last_attract_mode_time_value)
        return
    update_onesauce_setting(target_dir, "attractModeTime", value)
    self._last_attract_mode_time_value = value
    self._push_status_message("Attract mode delay updated")


def handle_attract_mode_next_time_changed(self: "MainWindow") -> None:
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    value = self.tweaks_attract_mode_next_time_edit.text().strip()
    if not value:
        self.tweaks_attract_mode_next_time_edit.setText(self._last_attract_mode_next_time_value)
        return
    update_onesauce_setting(target_dir, "attractModeNextTime", value)
    self._last_attract_mode_next_time_value = value
    self._push_status_message("Attract mode item interval updated")


def handle_default_video_value_changed(self: "MainWindow", value: int) -> None:
    self.tweaks_default_video_value_percent_label.setText(f"{value}%")
    if self._loading_tweaks_settings:
        return
    target_dir = self._target_dir()
    if target_dir is None:
        return
    update_onesauce_setting(target_dir, "defaultVolume", _percent_to_default_video_value(value))
    self._push_status_message("Default video volume updated")
