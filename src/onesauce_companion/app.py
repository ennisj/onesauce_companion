from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from onesauce_companion.services.app_logging import configure_application_logging


def main() -> int:
    configure_application_logging()
    logging.getLogger(__name__).info("Starting OnesaUCE Companion")
    app = QApplication(sys.argv)
    app.setApplicationName("OnesaUCE Companion")

    from onesauce_companion.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    exit_code = app.exec()
    logging.getLogger(__name__).info("Exiting OnesaUCE Companion with code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
