"""Application stylesheet builder."""
from __future__ import annotations

from pathlib import Path


def build_stylesheet(assets_dir: Path) -> str:
    spin_up_icon = (assets_dir / "chevron_up_white.svg").as_posix()
    spin_down_icon = (assets_dir / "chevron_down_white.svg").as_posix()
    checkbox_check_icon = (assets_dir / "check_white.svg").as_posix()

    return f"""
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
            QWidget#navGroup {{
                background: #1f1f1f;
                border: 1px solid #4f4f4f;
                border-radius: 12px;
            }}
            QWidget#navSectionContainer {{
                background: #222222;
            }}
            QLabel#navSectionLabel {{
                color: #8f8f8f;
                font-size: 9.5pt;
                font-weight: 700;
                background: #222222;
                padding: 0px 6px;
            }}
            QLabel#collectionLinks {{
                color: #69b8ff;
                padding: 0;
            }}
            QLabel#collectionLinks a {{
                color: #69b8ff;
                text-decoration: none;
            }}
            QLabel {{
                background: transparent;
                color: #ffffff;
            }}
            QLineEdit, QPlainTextEdit, QTextEdit {{
                background: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 10px;
            }}
            QComboBox {{
                background: #242424;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 8px 34px 8px 10px;
                min-height: 24px;
            }}
            QComboBox:hover {{
                border-color: #666666;
            }}
            QComboBox:focus {{
                border-color: #2ea3ff;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{
                image: url("{spin_down_icon}");
                width: 10px;
                height: 10px;
            }}
            QComboBox QAbstractItemView {{
                background: #242424;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #0084ff;
                selection-color: #ffffff;
            }}
            QSpinBox {{
                background: #2b2b2b;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 6px 40px 6px 10px;
                min-height: 24px;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
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
                background: #c9b548;
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
            QTableWidget#ComponentsTable, QTableWidget#QueueTable, QTableWidget#GamesTable {{
                gridline-color: #555555;
                alternate-background-color: #242424;
                border: 1px solid #555555;
                border-radius: 4px;
                background: #2b2b2b;
            }}
            QTableWidget#ComponentsTable::item, QTableWidget#QueueTable::item, QTableWidget#GamesTable::item {{
                padding: 4px;
                selection-background-color: #2b2b2b;
                selection-color: #ffffff;
            }}
            QCheckBox#rowSelector {{
                background: transparent;
                spacing: 0px;
            }}
            QCheckBox#rowSelector::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid #555555;
                border-radius: 3px;
                background: #2b2b2b;
            }}
            QCheckBox#rowSelector::indicator:hover {{
                border-color: #2ea3ff;
            }}
            QCheckBox#rowSelector::indicator:checked {{
                border-color: #2ea3ff;
                background: #2ea3ff;
                image: url("{checkbox_check_icon}");
            }}
            QCheckBox#headerSelector {{
                background: transparent;
                spacing: 0px;
            }}
            QCheckBox#headerSelector::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid #d8e6f2;
                border-radius: 3px;
                background: #737b84;
            }}
            QCheckBox#headerSelector::indicator:hover {{
                border-color: #ffffff;
                background: #7f8892;
            }}
            QCheckBox#headerSelector::indicator:checked {{
                border-color: #2ea3ff;
                background: #2ea3ff;
                image: url("{checkbox_check_icon}");
            }}
            QTableCornerButton::section {{
                background: #2b2b2b;
                border: 1px solid #555555;
            }}
            QPushButton {{
                background: #e2cf5a;
                color: #1f1f1f;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #edd96e;
            }}
            QPushButton:pressed {{
                background: #0066cc;
            }}
            QPushButton:disabled {{
                background: #4a4a4a;
                color: #8f8f8f;
            }}
            QPushButton#videoControlButton {{
                background: transparent;
                border: none;
                border-radius: 0px;
                padding: 0px;
                min-width: 0px;
                min-height: 0px;
            }}
            QPushButton#videoControlButton:hover {{
                background: transparent;
            }}
            QPushButton#videoControlButton:pressed {{
                background: transparent;
            }}
            QPushButton#videoControlButton:disabled {{
                background: transparent;
            }}
            QSlider#videoSeekSlider {{
                background: transparent;
                padding: 0px;
            }}
            QSlider#videoSeekSlider::groove:horizontal {{
                background: rgba(255, 255, 255, 0.18);
                height: 6px;
                border-radius: 3px;
            }}
            QSlider#videoSeekSlider::sub-page:horizontal {{
                background: #2ea3ff;
                border-radius: 3px;
            }}
            QSlider#videoSeekSlider::add-page:horizontal {{
                background: rgba(255, 255, 255, 0.18);
                border-radius: 3px;
            }}
            QSlider#videoSeekSlider::handle:horizontal {{
                background: #ffffff;
                width: 12px;
                margin: -4px 0px;
                border-radius: 6px;
            }}
            QSlider#videoSeekSlider::handle:horizontal:hover {{
                background: #d8e6f2;
            }}
            QPushButton#navButton {{
                background: transparent;
                color: #aaaaaa;
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 10px 12px;
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
                background: #e2cf5a;
                color: #1f1f1f;
                border-color: #e2cf5a;
            }}
            QPushButton#logSelectorButton {{
                background: transparent;
                color: #c8c8c8;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 10px 12px;
                text-align: left;
                font-weight: 600;
            }}
            QPushButton#logSelectorButton:hover {{
                background: #343434;
                border-color: #555555;
                color: #ffffff;
            }}
            QPushButton#logSelectorButton:checked {{
                background: #2f2f2f;
                border-color: #6a6a6a;
                color: #ffffff;
            }}
            QFrame#logsViewerFrame {{
                background: #242424;
                border: 1px solid #555555;
                border-radius: 8px;
            }}
            QLabel#sidebarVersion {{
                color: #8f8f8f;
                font-size: 10pt;
                font-weight: 600;
                padding-top: 4px;
            }}
            QWidget#sidebarVersionRow {{
                background: transparent;
            }}
            QLabel#sidebarVersionNote {{
                color: #9a9a9a;
                font-size: 8.5pt;
                padding-top: 0px;
            }}
            QLabel#sidebarVersionNote a {{
                color: #00c4f4;
                text-decoration: underline;
            }}
            QLabel#screenHeader {{
                color: #e2cf5a;
                font-size: 18pt;
                font-weight: 700;
                padding: 0;
            }}
            QLabel#screenIntro {{
                color: #b5b5b5;
                padding: 0;
            }}
            QLabel#gamesPlaceholder {{
                color: #7f8790;
                font-size: 14pt;
                font-weight: 700;
            }}
            QPushButton#gameLink {{
                background: transparent;
                color: #69b8ff;
                border: none;
                border-radius: 0px;
                padding: 0;
                text-align: left;
                font-weight: 600;
            }}
            QPushButton#gameLink:hover {{
                background: transparent;
                color: #8bc9ff;
                text-decoration: underline;
            }}
            QPushButton#gameLink:pressed {{
                background: transparent;
                color: #2ea3ff;
            }}
            QToolButton[queueAction="true"] {{
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
                min-width: 22px;
                min-height: 22px;
            }}
            QToolButton[queueAction="true"]:hover {{
                background: #3a3a3a;
            }}
            QToolButton[queueAction="true"]:pressed {{
                background: #0066cc;
            }}
            QToolButton[queueAction="true"]:disabled {{
                background: transparent;
            }}
            QHeaderView::section {{
                background: #242424;
                color: #ffffff;
                border: none;
                border-right: 1px solid #555555;
                padding: 10px 44px 10px 10px;
                font-weight: 700;
            }}
            QHeaderView::up-arrow {{
                image: url("{spin_up_icon}");
                width: 10px;
                height: 10px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
                right: 10px;
            }}
            QHeaderView::down-arrow {{
                image: url("{spin_down_icon}");
                width: 10px;
                height: 10px;
                subcontrol-origin: padding;
                subcontrol-position: center right;
                right: 10px;
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
            QProgressBar#startupLoading {{
                background: #e2cf5a;
                color: #1f1f1f;
                border: 1px solid #e2cf5a;
            }}
            QProgressBar#startupLoading::chunk {{
                background: #e2cf5a;
            }}
            QLabel#titleLogo {{
                background: transparent;
                padding: 0 0 2px 0;
            }}
            QLabel#signupLink {{
                color: #00c4f4;
                padding-top: 2px;
            }}
            QLabel#parallelNote {{
                color: #aaaaaa;
                padding-top: 2px;
            }}
            QLabel#autostartFirmwareWarning {{
                color: #f2c14e;
                padding-top: 2px;
            }}
            QWidget#warningBanner {{
                background: #3a2f12;
                border: 1px solid #b38a1f;
                border-radius: 8px;
            }}
            QLabel#warningMessage {{
                color: #ffd66b;
                padding: 2px 0;
            }}
            QLabel#installRequiredTitle {{
                color: #f2c14e;
                font-size: 15pt;
                font-weight: 700;
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
            QListWidget#ThemeList {{
                background: #2b2b2b;
                border: 1px solid #444444;
                border-radius: 6px;
                color: #c8c8c8;
                padding: 4px;
                outline: none;
            }}
            QListWidget#ThemeList:focus {{
                border: 1px solid #444444;
            }}
            QListWidget#ThemeList::item {{
                padding: 4px 8px;
                border-radius: 4px;
                outline: none;
            }}
            QListWidget#ThemeList::item:selected {{
                background: #e2cf5a;
                color: #1f1f1f;
            }}
            """
