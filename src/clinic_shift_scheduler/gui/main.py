"""Desktop GUI bootstrap kept separate from the scheduling CLI."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from ..application_paths import application_root
from .main_window import MainWindow
from .styles.loader import load_application_stylesheet


APPLICATION_NAME = "ClinicShiftSchedulerEditor"
APPLICATION_DISPLAY_NAME = "診所排班系統"


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    app = QApplication(list(argv) if argv is not None else sys.argv)
    QCoreApplication.setOrganizationName("ClinicShiftScheduler")
    QCoreApplication.setApplicationName(APPLICATION_NAME)
    app.setApplicationDisplayName(APPLICATION_DISPLAY_NAME)
    app.setStyleSheet(load_application_stylesheet())
    return app


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv
    smoke_test = "--smoke-test" in arguments
    qt_arguments = [item for item in arguments if item != "--smoke-test"]
    app = create_application(qt_arguments)
    entry_file = Path(__file__).resolve().parents[2] / "run_gui.py"
    root = application_root(entry_file)
    window = MainWindow(input_directory=root / "input")
    window.show()
    if smoke_test:
        QTimer.singleShot(0, app.quit)
    return app.exec()
