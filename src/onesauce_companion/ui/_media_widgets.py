"""Shared media widgets: scalable image labels and video overlay containers."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from onesauce_companion.ui._utils import _assets_dir

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    HAS_QT_MULTIMEDIA = True
except ImportError:  # pragma: no cover - optional runtime dependency in some environments
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None
    HAS_QT_MULTIMEDIA = False


class ScaledImageLabel(QLabel):
    _active_expanded_label: "ScaledImageLabel | None" = None
    folderRequested = Signal()
    uploadRequested = Signal()
    deleteRequested = Signal()

    def __init__(self, max_height: int, minimum_width: int = 220) -> None:
        super().__init__()
        self._pixmap = QPixmap()
        self._max_height = max_height
        self._action_strip_height = 30
        self._action_padding = 6
        self._action_gap = 6
        self._action_button_size = 20
        self._action_icon_size = 18
        self._expanded = False
        self._window_filter_target: QWidget | None = None
        self._app_filter_target: QApplication | None = None
        self._floating_preview: QLabel | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setContentsMargins(0, 0, 0, self._action_strip_height)
        self.setMinimumHeight(max_height)
        self.setMaximumHeight(max_height)
        self.setMinimumWidth(minimum_width)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._folder_button = QPushButton(self)
        self._folder_button.setObjectName("videoControlButton")
        self._folder_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._folder_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._folder_button.setIcon(QIcon(str(_assets_dir() / "folder-white.svg")))
        self._folder_button.clicked.connect(self.folderRequested.emit)
        self._folder_button.hide()

        self._upload_button = QPushButton(self)
        self._upload_button.setObjectName("videoControlButton")
        self._upload_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._upload_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._upload_button.setIcon(QIcon(str(_assets_dir() / "upload-white.svg")))
        self._upload_button.clicked.connect(self.uploadRequested.emit)
        self._upload_button.hide()

        self._delete_button = QPushButton(self)
        self._delete_button.setObjectName("videoControlButton")
        self._delete_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._delete_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._delete_button.setIcon(QIcon(str(_assets_dir() / "delete-white.svg")))
        self._delete_button.clicked.connect(self.deleteRequested.emit)
        self._delete_button.hide()

        self._expand_button = QPushButton(self)
        self._expand_button.setObjectName("videoControlButton")
        self._expand_button.setFixedSize(self._action_button_size, self._action_button_size)
        self._expand_button.setIconSize(QSize(self._action_icon_size, self._action_icon_size))
        self._expand_button.clicked.connect(self._toggle_expanded)
        self._expand_button.hide()
        self._sync_expand_button()

    def set_image(self, image_path: Path | None, placeholder: str) -> None:
        if self._expanded:
            self._set_expanded(False)
        if image_path is None or not image_path.exists():
            self._pixmap = QPixmap()
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setPixmap(QPixmap())
            self.setText(placeholder)
            self._expand_button.hide()
            self._position_action_buttons()
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._pixmap = QPixmap()
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setPixmap(QPixmap())
            self.setText(placeholder)
            self._expand_button.hide()
            self._position_action_buttons()
            return
        self._pixmap = pixmap
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setText("")
        self._expand_button.show()
        self._sync_expand_button()
        self._apply_scaled_pixmap()
        self._position_action_buttons()
        self._position_expand_button()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_scaled_pixmap()
        self._position_action_buttons()
        self._position_expand_button()
        if self._expanded:
            self._update_floating_preview()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._attach_window_filter()
        self._position_action_buttons()
        self._position_expand_button()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched == self._window_filter_target and self._expanded and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            self._update_floating_preview()
        elif self._expanded and self._app_filter_target is not None and event.type() == QEvent.Type.MouseButtonPress:
            self._handle_global_mouse_press(event)
        return super().eventFilter(watched, event)

    def _apply_scaled_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        available_height = max(1, self._max_height - self._action_strip_height)
        scaled = self._pixmap.scaled(
            max(1, self.width()),
            available_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)


    def set_action_buttons_enabled(self, folder_enabled: bool, upload_enabled: bool, delete_enabled: bool) -> None:
        self._folder_button.setEnabled(folder_enabled)
        self._upload_button.setEnabled(upload_enabled)
        self._delete_button.setEnabled(delete_enabled)
        self._set_action_buttons_visible(folder_enabled, upload_enabled, delete_enabled)

    def _set_action_buttons_visible(self, folder_visible: bool, upload_visible: bool, delete_visible: bool) -> None:
        self._folder_button.setVisible(folder_visible)
        self._upload_button.setVisible(upload_visible)
        self._delete_button.setVisible(delete_visible)
        self._position_action_buttons()

    def _position_action_buttons(self) -> None:
        y_pos = max(0, self.height() - self._action_padding - self._folder_button.height())
        x_pos = self._action_padding
        for widget in (self._folder_button, self._upload_button, self._delete_button):
            if not widget.isVisible():
                continue
            widget.move(x_pos, y_pos)
            widget.raise_()
            x_pos += widget.width() + self._action_gap

    def _position_expand_button(self) -> None:
        if not self._expand_button.isVisible():
            return
        x_pos = max(0, self.width() - self._expand_button.width() - self._action_padding)
        y_pos = max(0, self.height() - self._expand_button.height() - self._action_padding)
        self._expand_button.move(x_pos, y_pos)
        self._expand_button.raise_()

    def _attach_window_filter(self) -> None:
        window = self.window()
        if not isinstance(window, QWidget) or window is self._window_filter_target:
            return
        if self._window_filter_target is not None:
            self._window_filter_target.removeEventFilter(self)
        self._window_filter_target = window
        self._window_filter_target.installEventFilter(self)

    def _attach_app_filter(self) -> None:
        app = QApplication.instance()
        if app is None or app is self._app_filter_target:
            return
        if self._app_filter_target is not None:
            self._app_filter_target.removeEventFilter(self)
        self._app_filter_target = app
        self._app_filter_target.installEventFilter(self)

    def _detach_app_filter(self) -> None:
        if self._app_filter_target is not None:
            self._app_filter_target.removeEventFilter(self)
            self._app_filter_target = None

    def _handle_global_mouse_press(self, event) -> None:
        if self._floating_preview is None:
            return
        if not hasattr(event, "globalPosition"):
            return
        global_pos = event.globalPosition().toPoint()
        preview_pos = self._floating_preview.mapFromGlobal(global_pos)
        if self._floating_preview.rect().contains(preview_pos):
            return
        for widget in (self._folder_button, self._upload_button, self._delete_button, self._expand_button):
            if not widget.isVisible():
                continue
            widget_pos = widget.mapFromGlobal(global_pos)
            if widget.rect().contains(widget_pos):
                return
        self._set_expanded(False)

    def _toggle_expanded(self) -> None:
        if self._pixmap.isNull():
            return
        self._set_expanded(not self._expanded)

    def _set_expanded(self, expanded: bool) -> None:
        if expanded:
            active = ScaledImageLabel._active_expanded_label
            if active is not None and active is not self:
                active._set_expanded(False)
            window = self.window()
            collapse_video = getattr(window, "_collapse_expanded_video", None)
            if callable(collapse_video):
                collapse_video()
            ScaledImageLabel._active_expanded_label = self
        elif ScaledImageLabel._active_expanded_label is self:
            ScaledImageLabel._active_expanded_label = None
        self._expanded = expanded
        self._sync_expand_button()
        if not expanded:
            self._detach_app_filter()
            if not self._pixmap.isNull():
                self._expand_button.show()
                self._position_expand_button()
            if self._floating_preview is not None:
                self._floating_preview.hide()
            return
        self._expand_button.hide()
        self._attach_window_filter()
        self._attach_app_filter()
        if self._window_filter_target is None:
            return
        if self._floating_preview is None:
            self._floating_preview = QLabel(self._window_filter_target)
            self._floating_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._floating_preview.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._floating_preview.setStyleSheet("background: #000000; border: 1px solid #444444;")
        self._floating_preview.show()
        self._floating_preview.raise_()
        self._update_floating_preview()

    def _sync_expand_button(self) -> None:
        self._expand_button.setIcon(QIcon(str(_assets_dir() / "maximize-white.svg")))

    def _update_floating_preview(self) -> None:
        if self._floating_preview is None or self._window_filter_target is None or self._pixmap.isNull():
            return
        anchor = self.mapTo(self._window_filter_target, self.rect().bottomRight())
        base_size = self.pixmap().size() if self.pixmap() is not None else QSize(self.width(), self.height())
        base_width = max(220, base_size.width())
        base_height = max(180, base_size.height())
        target_width = min(self._window_filter_target.width() - 24, base_width * 3)
        target_height = min(self._window_filter_target.height() - 24, base_height * 3)
        scaled = self._pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x_pos = max(12, anchor.x() - scaled.width() + 1)
        y_pos = max(12, anchor.y() - scaled.height() + 1)
        self._floating_preview.setPixmap(scaled)
        self._floating_preview.setGeometry(x_pos, y_pos, scaled.width(), scaled.height())


class OverlaySurface(QWidget):
    entered = Signal()
    left = Signal()
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

    def enterEvent(self, event) -> None:  # type: ignore[override]
        super().enterEvent(event)
        self.entered.emit()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        super().leaveEvent(event)
        self.left.emit()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class VideoOverlayContainer(QWidget):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._content_widget: QWidget | None = None
        self._hovered = False
        self._has_video = False
        self._is_playing = False
        self._play_icon = QPixmap(str(_assets_dir() / "play-button-white.svg"))
        self._pause_icon = QPixmap(str(_assets_dir() / "pause-white.svg"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.interaction_overlay = OverlaySurface(self)
        self.interaction_overlay.entered.connect(self._handle_overlay_enter)
        self.interaction_overlay.left.connect(self._handle_overlay_leave)
        self.interaction_overlay.clicked.connect(self._handle_overlay_click)

        self.overlay_label = QLabel(self.interaction_overlay)
        self.overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.overlay_opacity = QGraphicsOpacityEffect(self.overlay_label)
        self.overlay_opacity.setOpacity(0.0)
        self.overlay_label.setGraphicsEffect(self.overlay_opacity)
        self.overlay_animation = QPropertyAnimation(self.overlay_opacity, b"opacity", self)
        self.overlay_animation.setDuration(160)
        self.overlay_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.overlay_animation.finished.connect(self._finalize_overlay_animation)
        self.overlay_label.hide()

    def set_content_widget(self, widget: QWidget) -> None:
        self.layout().addWidget(widget)
        self._content_widget = widget
        self._reposition_overlay()

    def set_video_state(self, has_video: bool, is_playing: bool) -> None:
        self._has_video = has_video
        self._is_playing = is_playing
        self._update_overlay()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_overlay()
        self._update_overlay()

    def _handle_overlay_enter(self) -> None:
        self._hovered = True
        self._update_overlay()

    def _handle_overlay_leave(self) -> None:
        self._hovered = False
        self._update_overlay()

    def _handle_overlay_click(self) -> None:
        if self._has_video:
            self.clicked.emit()

    def _update_overlay(self) -> None:
        should_show = self._hovered and self._has_video
        if not should_show:
            self._fade_overlay(False)
            return
        base_pixmap = self._pause_icon if self._is_playing else self._play_icon
        if base_pixmap.isNull():
            self._fade_overlay(False)
            return
        target_width = max(48, self.width() // 3)
        target_height = max(48, self.height() // 3)
        scaled = base_pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.overlay_label.setPixmap(scaled)
        self.overlay_label.setFixedSize(scaled.size())
        self._reposition_overlay()
        self._fade_overlay(True)

    def _fade_overlay(self, visible: bool) -> None:
        self.overlay_animation.stop()
        current_opacity = self.overlay_opacity.opacity()
        target_opacity = 1.0 if visible else 0.0
        if visible:
            self.interaction_overlay.raise_()
            self.overlay_label.show()
            self.overlay_label.raise_()
        if abs(current_opacity - target_opacity) < 0.01:
            self.overlay_opacity.setOpacity(target_opacity)
            if not visible:
                self.overlay_label.hide()
            return
        self.overlay_animation.setStartValue(current_opacity)
        self.overlay_animation.setEndValue(target_opacity)
        self.overlay_animation.start()

    def _finalize_overlay_animation(self) -> None:
        if self.overlay_opacity.opacity() <= 0.01:
            self.overlay_label.hide()

    def _reposition_overlay(self) -> None:
        self.interaction_overlay.setGeometry(self.rect())
        self.interaction_overlay.raise_()
        pixmap = self.overlay_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        x_pos = max(0, (self.interaction_overlay.width() - self.overlay_label.width()) // 2)
        y_pos = max(0, (self.interaction_overlay.height() - self.overlay_label.height()) // 2)
        self.overlay_label.move(x_pos, y_pos)
        self.overlay_label.raise_()


