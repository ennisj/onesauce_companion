from __future__ import annotations

import logging

from onesauce_companion.services.app_logging import LOG_FILE_NAME, configure_application_logging


def test_configure_application_logging_writes_log_file(tmp_path):
    log_path = configure_application_logging(
        tmp_path,
        redirect_streams=False,
        install_exception_hooks=False,
        install_qt_handler=False,
        force=True,
    )

    logging.getLogger("onesauce_companion.tests").info("hello from test logger")

    assert log_path == tmp_path / LOG_FILE_NAME
    assert log_path.exists()
    assert "hello from test logger" in log_path.read_text(encoding="utf-8")
