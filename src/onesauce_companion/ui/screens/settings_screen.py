"""Settings screen: install target, Archive.org credentials, downloads."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.services.download_cache import default_downloads_dir
from onesauce_companion.ui._utils import build_screen_header_row

if TYPE_CHECKING:
    from onesauce_companion.ui.main_window import MainWindow


def build_settings_screen(self: "MainWindow") -> QWidget:
    container = QScrollArea()
    container.setWidgetResizable(True)
    container.setFrameShape(QFrame.Shape.NoFrame)
    container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    screen = QWidget()
    container.setWidget(screen)
    layout = QVBoxLayout(screen)
    layout.setContentsMargins(0, 0, 12, 0)
    layout.setSpacing(18)
    layout.addWidget(build_screen_header_row("Settings"))

    target_group = QGroupBox("Install Target")
    target_layout = QGridLayout(target_group)
    target_layout.setHorizontalSpacing(12)
    target_layout.setVerticalSpacing(10)
    target_layout.setColumnStretch(1, 1)

    self.target_edit = QLineEdit()
    self.target_edit.setPlaceholderText(r"E:\ or another NTFS drive root")
    browse_button = QPushButton("Browse")
    browse_button.setMinimumWidth(160)
    browse_button.clicked.connect(self._browse_for_target)
    self.bitlcd_target_edit = QLineEdit()
    self.bitlcd_target_edit.setPlaceholderText(r"Choose a BitLCD image folder")
    bitlcd_browse_button = QPushButton("Browse")
    bitlcd_browse_button.setMinimumWidth(160)
    bitlcd_browse_button.clicked.connect(self._browse_for_bitlcd_target)
    self.validate_button = QPushButton("Validate")
    self.validate_button.setMinimumWidth(150)
    self.validate_button.clicked.connect(self._start_validate_credentials)

    target_layout.addWidget(QLabel("Target folder"), 0, 0)
    target_layout.addWidget(self.target_edit, 0, 1)
    target_layout.addWidget(browse_button, 0, 2)
    self.root_warning = self._build_target_warning(
        "OnesaUCE will not run unless it is installed to the root of the drive."
    )
    self.ntfs_warning = self._build_target_warning(
        "OnesaUCE will not run unless the drive has been formatted NTFS."
    )
    self.bitlcd_warning = self._build_target_warning(
        r"BitLCD will not see marquees that are not within the \bitlcd\thirdparty folder structure."
    )
    target_layout.addWidget(self.root_warning, 1, 0, 1, 3)
    target_layout.addWidget(self.ntfs_warning, 2, 0, 1, 3)
    target_layout.addWidget(QLabel("BitLCD folder"), 3, 0)
    target_layout.addWidget(self.bitlcd_target_edit, 3, 1)
    target_layout.addWidget(bitlcd_browse_button, 3, 2)
    target_layout.addWidget(self.bitlcd_warning, 4, 0, 1, 3)
    layout.addWidget(target_group)

    auth_group = QGroupBox("Archive.org Credentials")
    auth_layout = QGridLayout(auth_group)
    auth_layout.setHorizontalSpacing(12)
    auth_layout.setVerticalSpacing(10)
    auth_layout.setColumnStretch(1, 1)

    auth_note = QLabel("These downloads currently require Archive.org authentication.")
    auth_note.setWordWrap(True)
    signup_link = QLabel(
        '<a href="https://archive.org/account/signup">Sign up for an Internet Archive account</a>'
    )
    signup_link.setObjectName("signupLink")
    signup_link.setOpenExternalLinks(True)
    self.archive_email_edit = QLineEdit()
    self.archive_email_edit.setPlaceholderText("Archive.org email")
    self.archive_email_edit.setMinimumHeight(44)
    self.archive_password_edit = QLineEdit()
    self.archive_password_edit.setPlaceholderText("Archive.org password")
    self.archive_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
    self.archive_password_edit.setMinimumHeight(44)
    self.parallel_downloads_spin = QSpinBox()
    self.parallel_downloads_spin.setMinimum(1)
    self.parallel_downloads_spin.setMaximum(8)
    self.parallel_downloads_spin.setValue(2)
    self.parallel_downloads_spin.setMinimumHeight(36)
    parallel_note = QLabel("Higher values allow more simultaneous downloads while another component installs.")
    parallel_note.setWordWrap(True)
    parallel_note.setObjectName("parallelNote")
    auth_actions_row = QHBoxLayout()
    auth_actions_row.addStretch(1)
    auth_actions_row.addWidget(self.validate_button)

    auth_layout.addWidget(auth_note, 0, 0, 1, 2)
    auth_layout.addWidget(signup_link, 1, 0, 1, 2)
    auth_layout.addWidget(QLabel("Email"), 2, 0)
    auth_layout.addWidget(self.archive_email_edit, 2, 1)
    auth_layout.addWidget(QLabel("Password"), 3, 0)
    auth_layout.addWidget(self.archive_password_edit, 3, 1)
    auth_layout.addWidget(QLabel("Parallel downloads"), 4, 0)
    auth_layout.addWidget(self.parallel_downloads_spin, 4, 1)
    auth_layout.addWidget(parallel_note, 5, 0, 1, 2)
    auth_layout.addLayout(auth_actions_row, 6, 0, 1, 2)
    layout.addWidget(auth_group)

    downloads_group = QGroupBox("Downloads")
    downloads_layout = QGridLayout(downloads_group)
    downloads_layout.setHorizontalSpacing(12)
    downloads_layout.setVerticalSpacing(10)
    downloads_layout.setColumnStretch(1, 1)

    self.downloads_path_edit = QLineEdit()
    self.downloads_path_edit.setPlaceholderText(str(default_downloads_dir()))
    downloads_browse_button = QPushButton("Browse")
    downloads_browse_button.setMinimumWidth(160)
    downloads_browse_button.clicked.connect(self._browse_for_downloads_path)
    self.downloads_retention_combo = QComboBox()
    self.downloads_retention_combo.addItem("Delete immediately after install", "delete")
    self.downloads_retention_combo.addItem("Keep latest version of each component", "latest")
    self.downloads_retention_combo.addItem("Keep zips up to a number of days", "days")
    self.downloads_retention_combo.addItem("Keep zips up to a max amount of space (GB)", "space")
    self.downloads_retention_days_spin = QSpinBox()
    self.downloads_retention_days_spin.setMinimum(1)
    self.downloads_retention_days_spin.setMaximum(3650)
    self.downloads_retention_days_spin.setValue(30)
    self.downloads_retention_days_spin.setFixedWidth(120)
    self.downloads_retention_max_gb_spin = QDoubleSpinBox()
    self.downloads_retention_max_gb_spin.setMinimum(0.1)
    self.downloads_retention_max_gb_spin.setMaximum(10000.0)
    self.downloads_retention_max_gb_spin.setDecimals(1)
    self.downloads_retention_max_gb_spin.setSingleStep(0.5)
    self.downloads_retention_max_gb_spin.setValue(5.0)
    self.downloads_retention_max_gb_spin.setSuffix(" GB")
    self.downloads_retention_max_gb_spin.setFixedWidth(120)
    self.auto_resume_downloads_checkbox = QCheckBox()
    self.auto_resume_downloads_checkbox.setChecked(False)
    auto_resume_label = QLabel("Automatically Resume Downloads on Start")
    auto_resume_row = QWidget()
    auto_resume_layout = QHBoxLayout(auto_resume_row)
    auto_resume_layout.setContentsMargins(0, 0, 0, 0)
    auto_resume_layout.setSpacing(6)
    auto_resume_layout.addWidget(self.auto_resume_downloads_checkbox)
    auto_resume_layout.addWidget(auto_resume_label)
    auto_resume_layout.addStretch(1)
    self.auto_install_after_download_checkbox = QCheckBox()
    self.auto_install_after_download_checkbox.setChecked(True)
    auto_install_after_download_label = QLabel("Automatically Install Components After Download")
    auto_install_after_download_row = QWidget()
    auto_install_after_download_layout = QHBoxLayout(auto_install_after_download_row)
    auto_install_after_download_layout.setContentsMargins(0, 0, 0, 0)
    auto_install_after_download_layout.setSpacing(6)
    auto_install_after_download_layout.addWidget(self.auto_install_after_download_checkbox)
    auto_install_after_download_layout.addWidget(auto_install_after_download_label)
    auto_install_after_download_layout.addStretch(1)
    self.segmented_downloads_checkbox = QCheckBox()
    self.segmented_downloads_checkbox.setChecked(False)
    segmented_downloads_label = QLabel("Use Segmented Downloads for Large Archives")
    segmented_downloads_row = QWidget()
    segmented_downloads_layout = QHBoxLayout(segmented_downloads_row)
    segmented_downloads_layout.setContentsMargins(0, 0, 0, 0)
    segmented_downloads_layout.setSpacing(6)
    segmented_downloads_layout.addWidget(self.segmented_downloads_checkbox)
    segmented_downloads_layout.addWidget(segmented_downloads_label)
    segmented_downloads_layout.addStretch(1)
    self.segmented_download_min_size_spin = QSpinBox()
    self.segmented_download_min_size_spin.setMinimum(1)
    self.segmented_download_min_size_spin.setMaximum(1024 * 1024)
    self.segmented_download_min_size_spin.setValue(512)
    self.segmented_download_min_size_spin.setSuffix(" MB")
    self.segmented_download_min_size_spin.setFixedWidth(140)
    self.segmented_download_segments_spin = QSpinBox()
    self.segmented_download_segments_spin.setMinimum(2)
    self.segmented_download_segments_spin.setMaximum(8)
    self.segmented_download_segments_spin.setValue(4)
    self.segmented_download_segments_spin.setFixedWidth(120)
    self.clear_downloads_button = QPushButton("Clear Downloads Now")
    self.clear_downloads_button.setMinimumWidth(200)
    self.clear_downloads_button.clicked.connect(self._clear_downloads_now)
    downloads_note = QLabel("Downloaded archives are cached here before extraction and can be reused across installs.")
    downloads_note.setWordWrap(True)
    downloads_note.setObjectName("parallelNote")
    downloads_actions_row = QHBoxLayout()
    downloads_actions_row.addStretch(1)
    downloads_actions_row.addWidget(self.clear_downloads_button)
    self.downloads_retention_days_label = QLabel("Days to keep")
    self.downloads_retention_max_gb_label = QLabel("Max space")

    downloads_layout.addWidget(QLabel("Downloads folder"), 0, 0)
    downloads_layout.addWidget(self.downloads_path_edit, 0, 1)
    downloads_layout.addWidget(downloads_browse_button, 0, 2)
    downloads_layout.addWidget(QLabel("Retention"), 1, 0)
    downloads_layout.addWidget(self.downloads_retention_combo, 1, 1, 1, 2)
    downloads_layout.addWidget(self.downloads_retention_days_label, 2, 0)
    downloads_layout.addWidget(self.downloads_retention_days_spin, 2, 1)
    downloads_layout.addWidget(self.downloads_retention_max_gb_label, 3, 0)
    downloads_layout.addWidget(self.downloads_retention_max_gb_spin, 3, 1)
    downloads_layout.addWidget(auto_resume_row, 4, 0, 1, 3)
    downloads_layout.addWidget(auto_install_after_download_row, 5, 0, 1, 3)
    downloads_layout.addWidget(segmented_downloads_row, 6, 0, 1, 3)
    downloads_layout.addWidget(QLabel("Segmented minimum size"), 7, 0)
    downloads_layout.addWidget(self.segmented_download_min_size_spin, 7, 1)
    downloads_layout.addWidget(QLabel("Segments per archive"), 8, 0)
    downloads_layout.addWidget(self.segmented_download_segments_spin, 8, 1)
    downloads_layout.addWidget(downloads_note, 9, 0, 1, 3)
    downloads_layout.addLayout(downloads_actions_row, 10, 0, 1, 3)
    layout.addWidget(downloads_group)
    feature_flags_group = QGroupBox("Feature Flags")
    feature_flags_layout = QVBoxLayout(feature_flags_group)
    feature_flags_layout.setSpacing(10)
    self.enable_themes_preview_checkbox = QCheckBox()
    self.enable_themes_preview_checkbox.setChecked(False)
    enable_themes_preview_row = QWidget()
    enable_themes_preview_layout = QHBoxLayout(enable_themes_preview_row)
    enable_themes_preview_layout.setContentsMargins(0, 0, 0, 0)
    enable_themes_preview_layout.setSpacing(6)
    enable_themes_preview_layout.addWidget(self.enable_themes_preview_checkbox)
    enable_themes_preview_layout.addWidget(QLabel("Enable Themes (Pre-release preview)"))
    enable_themes_preview_layout.addStretch(1)
    feature_flags_layout.addWidget(enable_themes_preview_row)
    layout.addWidget(feature_flags_group)
    layout.addStretch(1)
    return container
