from __future__ import annotations

import io
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from onesauce_companion.services.settings import SettingsStore

try:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
except ImportError:  # pragma: no cover
    QtMsgType = None  # type: ignore[assignment]
    qInstallMessageHandler = None  # type: ignore[assignment]


LOG_FILE_NAME = "onesauce_companion.log"
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_configured_log_path: Path | None = None


class _LoggerWriter(io.TextIOBase):
    def __init__(self, logger: logging.Logger, level: int, original_stream) -> None:
        self._logger = logger
        self._level = level
        self._original_stream = original_stream
        self._buffer = ""
        self._reentrant = False

    def write(self, text: str) -> int:
        if not text:
            return 0
        if self._original_stream is not None:
            self._original_stream.write(text)
        if self._reentrant:
            return len(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self._emit(line)
        return len(text)

    def flush(self) -> None:
        if self._original_stream is not None:
            self._original_stream.flush()
        if self._buffer.strip():
            self._emit(self._buffer.rstrip())
        self._buffer = ""

    def _emit(self, message: str) -> None:
        self._reentrant = True
        try:
            self._logger.log(self._level, message)
        finally:
            self._reentrant = False


def configure_application_logging(
    config_dir: Path | None = None,
    *,
    redirect_streams: bool = True,
    install_exception_hooks: bool = True,
    install_qt_handler: bool = True,
    force: bool = False,
) -> Path:
    global _configured_log_path

    log_dir = SettingsStore(config_dir).config_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE_NAME
    if not force and _configured_log_path == log_path:
        return log_path

    root_logger = logging.getLogger()
    if force:
        for handler in list(root_logger.handlers):
            if getattr(handler, "_onesauce_handler", False):
                root_logger.removeHandler(handler)
                handler.close()

    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler.setLevel(logging.INFO)
    file_handler._onesauce_handler = True  # type: ignore[attr-defined]

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    logging.captureWarnings(True)

    if install_exception_hooks:
        _install_exception_hooks()
    if redirect_streams:
        _redirect_standard_streams()
    if install_qt_handler:
        _install_qt_message_handler()

    _configured_log_path = log_path
    logging.getLogger(__name__).info("Logging initialized at %s", log_path)
    return log_path


def _install_exception_hooks() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        logging.getLogger("onesauce_companion.exceptions").exception(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception

    if hasattr(threading, "excepthook"):
        def handle_thread_exception(args) -> None:
            logging.getLogger("onesauce_companion.exceptions").exception(
                "Unhandled thread exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = handle_thread_exception  # type: ignore[assignment]


def _redirect_standard_streams() -> None:
    stdout_logger = logging.getLogger("onesauce_companion.stdout")
    stderr_logger = logging.getLogger("onesauce_companion.stderr")
    if not isinstance(sys.stdout, _LoggerWriter):
        sys.stdout = _LoggerWriter(stdout_logger, logging.INFO, sys.__stdout__)  # type: ignore[assignment]
    if not isinstance(sys.stderr, _LoggerWriter):
        sys.stderr = _LoggerWriter(stderr_logger, logging.ERROR, sys.__stderr__)  # type: ignore[assignment]


def _install_qt_message_handler() -> None:
    if qInstallMessageHandler is None or QtMsgType is None:
        return

    def handle_qt_message(message_type, _context, message) -> None:
        logger = logging.getLogger("onesauce_companion.qt")
        if message_type == QtMsgType.QtDebugMsg:
            logger.debug(message)
        elif message_type == QtMsgType.QtInfoMsg:
            logger.info(message)
        elif message_type == QtMsgType.QtWarningMsg:
            logger.warning(message)
        elif message_type == QtMsgType.QtCriticalMsg:
            logger.error(message)
        else:
            logger.critical(message)

    qInstallMessageHandler(handle_qt_message)
