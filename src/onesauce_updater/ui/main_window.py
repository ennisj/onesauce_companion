from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QFont, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QHeaderView,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from onesauce_updater.manifest import REQUIRED_COMPONENTS
from onesauce_updater.models import InstallProgress
from onesauce_updater.services.archive_org import ArchiveOrgCredentials
from onesauce_updater.services.control import OperationController
from onesauce_updater.services.installer import Installer
from onesauce_updater.services.settings import AppSettings, SettingsStore
from onesauce_updater.ui.workers import InstallWorker, ValidateCredentialsWorker


SETTINGS_SCREEN = 0
BASE_COMPONENTS_SCREEN = 1


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.installer = Installer(REQUIRED_COMPONENTS)
        self.settings_store = SettingsStore()
        self._worker_thread: QThread | None = None
        self._worker: InstallWorker | None = None
        self._validate_thread: QThread | None = None
        self._validate_worker: ValidateCredentialsWorker | None = None
        self._controller: OperationController | None = None
        self._loading_settings = False
        self._closing = False
        self._close_after_workers = False
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.setInterval(350)
        self._scan_timer.timeout.connect(self._refresh_table)
        self._status_widgets: dict[str, ComponentStatusCell] = {}
        self._active_components: set[str] = set()
        self._logo_pixmap = QPixmap()

        self.setWindowTitle("OnesaUCE Updater")
        self.resize(1120, 1020)
        self.setMinimumSize(1000, 960)
        self._build_ui()
        self._apply_style()
        self._load_settings()
        self._connect_setting_signals()
        self._refresh_table()
        self._show_initial_screen()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        sidebar = QWidget()
        sidebar.setObjectName("sidebarCard")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 16)
        sidebar_layout.setSpacing(10)

        self.settings_nav_button = QPushButton("Settings")
        self.settings_nav_button.setObjectName("navButton")
        self.settings_nav_button.setCheckable(True)
        self.settings_nav_button.clicked.connect(lambda: self._change_screen(SETTINGS_SCREEN))

        self.base_components_nav_button = QPushButton("Base Components")
        self.base_components_nav_button.setObjectName("navButton")
        self.base_components_nav_button.setCheckable(True)
        self.base_components_nav_button.clicked.connect(lambda: self._change_screen(BASE_COMPONENTS_SCREEN))

        sidebar_layout.addWidget(self.settings_nav_button)
        sidebar_layout.addWidget(self.base_components_nav_button)
        sidebar_layout.addStretch(1)
        main_layout.addWidget(sidebar)

        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        title = QLabel()
        title.setObjectName("titleLogo")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        logo_path = Path(__file__).resolve().parents[3] / "assets" / "onesauce_logo.png"
        self._logo_pixmap = QPixmap(str(logo_path))
        if not self._logo_pixmap.isNull():
            self._title_logo = title
        else:
            title.setText("OnesaUCE")
            self._title_logo = None
        content_layout.addWidget(title)

        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(content_container, stretch=1)

        self.stack.addWidget(self._build_settings_screen())
        self.stack.addWidget(self._build_base_components_screen())

        self.progress_container = QWidget()
        progress_layout = QHBoxLayout(self.progress_container)
        progress_layout.setContentsMargins(0, 10, 0, 0)
        progress_layout.setSpacing(12)

        self.progress_label = QLabel("Idle")
        self.pause_button = QPushButton("Pause")
        self.pause_button.setMinimumWidth(120)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.clicked.connect(self._cancel_install)

        progress_layout.addWidget(self.progress_label)
        progress_layout.addStretch(1)
        progress_layout.addWidget(self.pause_button)
        progress_layout.addWidget(self.cancel_button)
        self.progress_container.setVisible(False)
        content_layout.addWidget(self.progress_container)

        self._set_transfer_controls_enabled(False)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.statusBar().showMessage("Ready")

        file_menu = self.menuBar().addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        QTimer.singleShot(0, self._update_logo_pixmap)

    def _build_settings_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        target_group = QGroupBox("Install Target")
        target_layout = QGridLayout(target_group)
        target_layout.setHorizontalSpacing(12)
        target_layout.setVerticalSpacing(10)
        target_layout.setColumnStretch(1, 1)

        self.target_edit = QLineEdit()
        self.target_edit.setPlaceholderText(r"E:\ or C:\work\OnesaUCE")
        browse_button = QPushButton("Browse")
        browse_button.setMinimumWidth(160)
        browse_button.clicked.connect(self._browse_for_target)
        self.validate_button = QPushButton("Validate")
        self.validate_button.setMinimumWidth(150)
        self.validate_button.clicked.connect(self._start_validate_credentials)
        self.save_settings_button = QPushButton("Save Settings")
        self.save_settings_button.setMinimumWidth(180)
        self.save_settings_button.clicked.connect(self._save_settings_and_notify)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_row.addWidget(self.validate_button)
        save_row.addWidget(self.save_settings_button)

        target_layout.addWidget(QLabel("Target folder"), 0, 0)
        target_layout.addWidget(self.target_edit, 0, 1)
        target_layout.addWidget(browse_button, 0, 2)
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

        auth_layout.addWidget(auth_note, 0, 0, 1, 2)
        auth_layout.addWidget(signup_link, 1, 0, 1, 2)
        auth_layout.addWidget(QLabel("Email"), 2, 0)
        auth_layout.addWidget(self.archive_email_edit, 2, 1)
        auth_layout.addWidget(QLabel("Password"), 3, 0)
        auth_layout.addWidget(self.archive_password_edit, 3, 1)
        auth_layout.addWidget(QLabel("Parallel downloads"), 4, 0)
        auth_layout.addWidget(self.parallel_downloads_spin, 4, 1)
        auth_layout.addWidget(parallel_note, 5, 0, 1, 2)
        layout.addWidget(auth_group)
        layout.addLayout(save_row)
        layout.addStretch(1)
        return screen

    def _build_base_components_screen(self) -> QWidget:
        screen = QWidget()
        layout = QVBoxLayout(screen)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)
        self.base_summary_label = QLabel("Review required components and install or update them.")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMinimumWidth(140)
        self.refresh_button.clicked.connect(self._refresh_table)
        self.install_button = QPushButton("Update")
        self.install_button.setMinimumWidth(220)
        self.install_button.clicked.connect(self._start_install)
        actions_row.addWidget(self.base_summary_label)
        actions_row.addStretch(1)
        actions_row.addWidget(self.refresh_button)
        actions_row.addWidget(self.install_button)
        layout.addLayout(actions_row)

        status_group = QGroupBox("Required Components")
        status_layout = QVBoxLayout(status_group)

        self.table = QTableWidget(len(REQUIRED_COMPONENTS), 4)
        self.table.setHorizontalHeaderLabels(["Component", "Installed", "Available", "Status"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 360)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setMinimumHeight(360)
        status_group.setMinimumHeight(420)
        self._initialize_status_cells()
        status_layout.addWidget(self.table)
        layout.addWidget(status_group, stretch=2)

        layout.addSpacing(14)

        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(2000)
        self.log_output.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_group, stretch=1)
        return screen

    def _apply_style(self) -> None:
        assets_dir = Path(__file__).resolve().parents[3] / "assets"
        spin_up_icon = (assets_dir / "chevron_up_white.svg").as_posix()
        spin_down_icon = (assets_dir / "chevron_down_white.svg").as_posix()
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: #1e1e1e;
            }}
            QWidget {{
                background: #2b2b2b;
                color: #ffffff;
                font-family: "Segoe UI";
                font-size: 11pt;
            }}
            QGroupBox {{
                border: 1px solid #555555;
                border-radius: 10px;
                margin-top: 14px;
                padding: 16px 14px 14px 14px;
                background: #222222;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px 0 6px;
                color: #aaaaaa;
                font-weight: 600;
            }}
            QWidget#sidebarCard {{
                background: #222222;
                border: 1px solid #555555;
                border-radius: 12px;
            }}
            QLabel {{
                background: transparent;
                color: #ffffff;
            }}
            QLineEdit, QPlainTextEdit, QTableWidget {{
                background: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
            }}
            QSpinBox {{
                background: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 6px 40px 6px 10px;
                min-height: 24px;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
                border-color: #2ea3ff;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                subcontrol-origin: border;
                width: 28px;
                background: #222222;
                border-left: 1px solid #555555;
            }}
            QSpinBox::up-button {{
                subcontrol-position: top right;
                border-top-right-radius: 8px;
                border-bottom: 1px solid #555555;
            }}
            QSpinBox::down-button {{
                subcontrol-position: bottom right;
                border-bottom-right-radius: 8px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: #3a3a3a;
            }}
            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
                background: #0066cc;
            }}
            QSpinBox::up-arrow, QSpinBox::down-arrow {{
                width: 10px;
                height: 10px;
            }}
            QSpinBox::up-arrow {{
                image: url("{spin_up_icon}");
            }}
            QSpinBox::down-arrow {{
                image: url("{spin_down_icon}");
            }}
            QTableWidget {{
                gridline-color: #555555;
                alternate-background-color: #242424;
                selection-background-color: #3a3a3a;
            }}
            QTableCornerButton::section {{
                background: #2b2b2b;
                border: 1px solid #555555;
            }}
            QPushButton {{
                background: #2ea3ff;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #1495ff;
            }}
            QPushButton:pressed {{
                background: #0066cc;
            }}
            QPushButton:disabled {{
                background: #4a4a4a;
                color: #8f8f8f;
            }}
            QPushButton#navButton {{
                background: transparent;
                color: #aaaaaa;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 14px 14px;
                text-align: left;
                font-weight: 700;
                font-size: 11.5pt;
            }}
            QPushButton#navButton:hover {{
                background: #3a3a3a;
                color: #ffffff;
                border-color: #555555;
            }}
            QPushButton#navButton:checked {{
                background: #0084ff;
                color: white;
                border-color: #0084ff;
            }}
            QHeaderView::section {{
                background: #242424;
                color: #ffffff;
                border: none;
                border-right: 1px solid #555555;
                padding: 10px;
                font-weight: 700;
            }}
            QProgressBar {{
                border: 1px solid #555555;
                border-radius: 8px;
                background: #3a3a3a;
                text-align: center;
                min-height: 24px;
                color: #ffffff;
                font-weight: 700;
            }}
            QProgressBar::chunk {{
                border-radius: 7px;
                background: #2ea3ff;
            }}
            QLabel#titleLogo {{
                padding: 0 0 8px 0;
                background: transparent;
            }}
            QLabel#signupLink {{
                color: #00c4f4;
                padding-top: 2px;
            }}
            QLabel#parallelNote {{
                color: #aaaaaa;
                padding-top: 2px;
            }}
            QStatusBar {{
                background: #222222;
                color: #aaaaaa;
                border-top: 1px solid #555555;
            }}
            QMenuBar {{
                background: #222222;
                color: #ffffff;
                border-bottom: 1px solid #555555;
            }}
            QMenuBar::item:selected {{
                background: #3a3a3a;
            }}
            QMenu {{
                background: #222222;
                color: #ffffff;
                border: 1px solid #555555;
            }}
            QMenu::item:selected {{
                background: #0084ff;
            }}
            QScrollBar:vertical {{
                background: #2b2b2b;
                width: 12px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #555555;
                min-height: 24px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #666666;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background: #2b2b2b;
                height: 12px;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background: #555555;
                min-width: 24px;
                border-radius: 6px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #666666;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            """
        )

    def _connect_setting_signals(self) -> None:
        self.target_edit.textChanged.connect(self._save_settings)
        self.target_edit.textChanged.connect(self._schedule_scan)
        self.archive_email_edit.textChanged.connect(self._save_settings)
        self.archive_password_edit.textChanged.connect(self._save_settings)
        self.parallel_downloads_spin.valueChanged.connect(self._save_settings)

    def _load_settings(self) -> None:
        self._loading_settings = True
        try:
            settings = self.settings_store.load()
            self.target_edit.setText(settings.install_target)
            self.archive_email_edit.setText(settings.archive_email)
            self.archive_password_edit.setText(settings.archive_password)
            self.parallel_downloads_spin.setValue(settings.parallel_downloads)
            self.installer.max_parallel_downloads = settings.parallel_downloads
        finally:
            self._loading_settings = False

    def _save_settings(self) -> None:
        if self._loading_settings:
            return
        settings = AppSettings(
            install_target=self.target_edit.text().strip(),
            archive_email=self.archive_email_edit.text().strip(),
            archive_password=self.archive_password_edit.text(),
            parallel_downloads=self.parallel_downloads_spin.value(),
        )
        self.settings_store.save(settings)
        self.installer.max_parallel_downloads = settings.parallel_downloads

    def _save_settings_and_notify(self) -> None:
        self._save_settings()
        self._refresh_table()
        QMessageBox.information(self, "Settings saved", "Settings were saved.")

    def _start_validate_credentials(self) -> None:
        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password before validating.",
            )
            return

        self._save_settings()
        self.install_button.setEnabled(False)
        self.validate_button.setEnabled(False)
        self.save_settings_button.setEnabled(False)
        self.statusBar().showMessage("Validating Archive.org credentials...")

        self._validate_thread = QThread(self)
        self._validate_worker = ValidateCredentialsWorker(credentials)
        self._validate_worker.moveToThread(self._validate_thread)

        self._validate_thread.started.connect(self._validate_worker.run)
        self._validate_worker.finished.connect(self._validate_credentials_success)
        self._validate_worker.error.connect(self._validate_credentials_error)
        self._validate_worker.finished.connect(self._validate_thread.quit)
        self._validate_worker.error.connect(self._validate_thread.quit)
        self._validate_thread.finished.connect(self._validate_thread.deleteLater)
        self._validate_thread.finished.connect(self._clear_validate_refs)
        self._validate_thread.start()

    def _show_initial_screen(self) -> None:
        settings = self.settings_store.load()
        has_settings = bool(
            settings.install_target.strip()
            or settings.archive_email.strip()
            or settings.archive_password
        )
        self._change_screen(BASE_COMPONENTS_SCREEN if has_settings else SETTINGS_SCREEN)

    def _change_screen(self, index: int) -> None:
        if index < 0:
            return
        self.stack.setCurrentIndex(index)
        self.settings_nav_button.setChecked(index == SETTINGS_SCREEN)
        self.base_components_nav_button.setChecked(index == BASE_COMPONENTS_SCREEN)
        if index == BASE_COMPONENTS_SCREEN:
            self._refresh_table()

    def _browse_for_target(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose OnesaUCE target folder")
        if directory:
            self.target_edit.setText(directory)
            self._refresh_table()

    def _update_logo_pixmap(self) -> None:
        if self._title_logo is None or self._logo_pixmap.isNull():
            return
        available_width = max(1, self._title_logo.contentsRect().width())
        scaled = self._logo_pixmap.scaledToWidth(
            available_width,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._title_logo.setPixmap(scaled)
        self._title_logo.setFixedHeight(scaled.height())

    def _schedule_scan(self) -> None:
        if self._loading_settings:
            return
        self._scan_timer.start()

    def _refresh_table(self) -> None:
        target = self._target_dir()
        if target is None:
            self._populate_missing_table()
            self._update_primary_action([])
            self.statusBar().showMessage("Select a target folder to scan.")
            return

        statuses = self.installer.scan_target(target)
        for row, status in enumerate(statuses):
            self._set_item(row, 0, status.spec.display_name)
            self._set_item(row, 1, status.installed_version or "Not installed")
            self._set_item(row, 2, status.spec.available_display)
            if status.spec.key not in self._active_components:
                self._set_status_widget(status.spec.key, status.status, 100 if status.status == "Installed" else 0)
        self._update_primary_action(statuses)
        self.statusBar().showMessage(f"Scanned {target}")

    def _populate_missing_table(self) -> None:
        for row, spec in enumerate(REQUIRED_COMPONENTS):
            self._set_item(row, 0, spec.display_name)
            self._set_item(row, 1, "Not scanned")
            self._set_item(row, 2, spec.available_display)
            self._set_status_widget(spec.key, "Pending", 0)

    def _set_item(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, column, item)

    def _initialize_status_cells(self) -> None:
        for row, spec in enumerate(REQUIRED_COMPONENTS):
            widget = ComponentStatusCell()
            self._status_widgets[spec.key] = widget
            self.table.setCellWidget(row, 3, widget)

    def _set_status_widget(self, component_key: str, status: str, percent: int) -> None:
        widget = self._status_widgets[component_key]
        widget.set_status(status, percent)

    def _start_install(self) -> None:
        target = self._target_dir()
        if target is None:
            QMessageBox.warning(self, "Missing target", "Choose a target folder in Settings before installing.")
            self._change_screen(SETTINGS_SCREEN)
            return

        credentials = self._archive_credentials()
        if credentials is None:
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Enter your Archive.org email and password in Settings before downloading.",
            )
            self._change_screen(SETTINGS_SCREEN)
            return

        self._save_settings()
        self._controller = OperationController()
        self._active_components.clear()
        self.install_button.setEnabled(False)
        self.validate_button.setEnabled(False)
        self.save_settings_button.setEnabled(False)
        self.progress_container.setVisible(True)
        self._set_transfer_controls_enabled(True)
        self.pause_button.setText("Pause")
        self.progress_label.setText("Preparing install...")
        self.log_output.appendPlainText(f"Target: {target}")

        self._worker_thread = QThread(self)
        self._worker = InstallWorker(self.installer, target, credentials, self._controller)
        self._worker.moveToThread(self._worker_thread)

        self._worker_thread.started.connect(self._worker.run)
        self._worker.log.connect(self.log_output.appendPlainText)
        self._worker.component_status.connect(self._update_component_status)
        self._worker.progress.connect(self._update_progress)
        self._worker.cancelled.connect(self._install_cancelled)
        self._worker.error.connect(self._install_failed)
        self._worker.finished.connect(self._install_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.cancelled.connect(self._worker_thread.quit)
        self._worker.error.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.finished.connect(self._clear_worker_refs)
        self._worker_thread.start()

    def _toggle_pause(self) -> None:
        if self._controller is None:
            return
        if self._controller.is_paused:
            self._controller.resume()
            self.pause_button.setText("Pause")
            self.progress_label.setText("Resuming transfer...")
        else:
            self._controller.pause()
            self.pause_button.setText("Resume")
            self.progress_label.setText("Paused")

    def _cancel_install(self) -> None:
        if self._controller is None:
            return
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.progress_label.setText("Cancelling...")
        self._controller.cancel()

    def _update_component_status(self, component_key: str, status: str) -> None:
        if status in {"Downloading", "Backing Up", "Installing"}:
            self._active_components.add(component_key)
        else:
            self._active_components.discard(component_key)
        self._set_status_widget(component_key, status, self._status_widgets[component_key].percent())
        for spec in REQUIRED_COMPONENTS:
            if spec.key == component_key:
                self.statusBar().showMessage(f"{spec.display_name}: {status}")
                break

    def _update_progress(self, progress: InstallProgress) -> None:
        if progress.phase == "queued":
            self.progress_label.setText(f"{progress.detail} ({progress.overall_percent}% overall)")
            return
        status_text = {
            "download": "Downloading",
            "download_complete": "Downloaded",
            "backup": "Backing Up",
            "extract": "Installing",
            "installed": "Installed",
        }.get(progress.phase, "Working")
        self._set_status_widget(progress.component_key, status_text, progress.component_percent)
        self.progress_label.setText(f"{progress.detail} ({progress.overall_percent}% overall)")

    def _install_finished(self, report: object) -> None:
        self._finish_install_ui()
        self.progress_label.setText("Install complete")
        self._refresh_table()

        backup_text = ""
        backup_dir = getattr(report, "backup_dir", None)
        if backup_dir:
            backup_text = f"\nBackups stored in:\n{backup_dir}"
            self.log_output.appendPlainText(f"Backup directory: {backup_dir}")

        if not self._closing:
            QMessageBox.information(self, "Install complete", f"Required components installed successfully.{backup_text}")
            self.progress_container.setVisible(False)
        self._finalize_close_if_ready()

    def _install_cancelled(self, message: str) -> None:
        self._finish_install_ui()
        self.progress_label.setText("Install cancelled")
        self.log_output.appendPlainText(message)
        self.statusBar().showMessage("Install cancelled")
        if not self._closing:
            self.progress_container.setVisible(False)
        self._finalize_close_if_ready()

    def _install_failed(self, message: str) -> None:
        self._finish_install_ui()
        self.progress_label.setText("Install failed")
        self.log_output.appendPlainText(f"ERROR: {message}")
        if not self._closing:
            QMessageBox.critical(self, "Install failed", message)
            self.progress_container.setVisible(False)
        self._finalize_close_if_ready()

    def _finish_install_ui(self) -> None:
        self._active_components.clear()
        self.install_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.validate_button.setEnabled(True)
        self.save_settings_button.setEnabled(True)
        self._set_transfer_controls_enabled(False)
        self.pause_button.setText("Pause")
        self._controller = None

    def _set_transfer_controls_enabled(self, enabled: bool) -> None:
        self.pause_button.setEnabled(enabled)
        self.cancel_button.setEnabled(enabled)

    def _clear_worker_refs(self) -> None:
        self._worker = None
        self._worker_thread = None
        self._finalize_close_if_ready()

    def _validate_credentials_success(self, user: str) -> None:
        self.install_button.setEnabled(True)
        self.validate_button.setEnabled(True)
        self.save_settings_button.setEnabled(True)
        self.statusBar().showMessage(f"Archive.org credentials validated for {user}")
        if not self._closing:
            QMessageBox.information(self, "Validation successful", f"Archive.org login succeeded for {user}.")
        self._finalize_close_if_ready()

    def _validate_credentials_error(self, message: str) -> None:
        self.install_button.setEnabled(True)
        self.validate_button.setEnabled(True)
        self.save_settings_button.setEnabled(True)
        self.statusBar().showMessage("Archive.org credential validation failed")
        if not self._closing:
            QMessageBox.critical(self, "Validation failed", message)
        self._finalize_close_if_ready()

    def _clear_validate_refs(self) -> None:
        self._validate_worker = None
        self._validate_thread = None
        self._finalize_close_if_ready()

    def _target_dir(self) -> Path | None:
        raw = self.target_edit.text().strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    def _archive_credentials(self) -> ArchiveOrgCredentials | None:
        email = self.archive_email_edit.text().strip()
        password = self.archive_password_edit.text()
        if not email or not password:
            return None
        return ArchiveOrgCredentials(email=email, password=password)

    def _update_primary_action(self, statuses: list) -> None:
        if self._controller is not None:
            self.install_button.setText("Update")
            self.install_button.setEnabled(False)
            return
        all_installed = bool(statuses) and all(status.status == "Installed" for status in statuses)
        self.install_button.setText("Up to Date" if all_installed else "Update")
        self.install_button.setEnabled(not all_installed)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self._scan_timer.stop()

        if self._controller is not None:
            self._controller.cancel()

        install_running = self._worker_thread is not None and self._worker_thread.isRunning()
        validation_running = self._validate_thread is not None and self._validate_thread.isRunning()

        if install_running or validation_running:
            self._close_after_workers = True
            self.statusBar().showMessage("Stopping background work...")
            event.ignore()
            return

        event.accept()

    def _finalize_close_if_ready(self) -> None:
        if not self._close_after_workers:
            return
        install_running = self._worker_thread is not None and self._worker_thread.isRunning()
        validation_running = self._validate_thread is not None and self._validate_thread.isRunning()
        if install_running or validation_running:
            return
        self._close_after_workers = False
        self.progress_container.setVisible(False)
        self.close()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_logo_pixmap()


class ComponentStatusCell(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)

        self.label = QLabel("Pending")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        self.set_status("Pending", 0)

    def set_status(self, text: str, percent: int) -> None:
        clamped_percent = max(0, min(100, percent))
        active = text in {"Downloading", "Backing Up", "Installing"}

        self.label.setText(text)
        self.label.setVisible(not active)

        self.progress.setVisible(active)
        self.progress.setValue(clamped_percent)
        self.progress.setFormat(f"{text} {clamped_percent}%")

    def percent(self) -> int:
        return self.progress.value()
