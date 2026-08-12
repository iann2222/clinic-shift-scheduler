"""Desktop GUI bootstrap kept separate from the scheduling CLI."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from ..application_paths import application_root
from .main_window import MainWindow
from .presenters import SchedulePresenter
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
    smoke, qt_arguments = _parse_gui_arguments(arguments)
    app = create_application(qt_arguments)
    entry_file = Path(__file__).resolve().parents[2] / "run_gui.py"
    root = application_root(entry_file)
    window = MainWindow(
        input_directory=root / "input",
        config_path=root / "config.json",
    )
    window.show()
    if smoke.enabled:
        QTimer.singleShot(
            0,
            lambda: _run_smoke_test(app, window, smoke),
        )
    return app.exec()


class _SmokeArguments(argparse.Namespace):
    enabled: bool
    input: Path | None
    output: Path | None


def _parse_gui_arguments(
    arguments: list[str],
) -> tuple[_SmokeArguments, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", action="store_true", dest="enabled")
    parser.add_argument("--smoke-input", type=Path, dest="input")
    parser.add_argument("--smoke-output", type=Path, dest="output")
    smoke, remaining = parser.parse_known_args(arguments[1:], namespace=_SmokeArguments())
    if (smoke.input is None) != (smoke.output is None):
        parser.error("--smoke-input and --smoke-output must be provided together")
    return smoke, [arguments[0], *remaining]


def _run_smoke_test(
    app: QApplication,
    window: MainWindow,
    smoke: _SmokeArguments,
) -> None:
    exit_code = 0
    error_path = (
        None
        if smoke.output is None
        else smoke.output.with_suffix(smoke.output.suffix + ".error.txt")
    )
    try:
        if smoke.input is not None and smoke.output is not None:
            smoke.output.parent.mkdir(parents=True, exist_ok=True)
            smoke.output.unlink(missing_ok=True)
            if error_path is not None:
                error_path.unlink(missing_ok=True)
            window.open_document_path(smoke.input)
            assert window.session is not None
            original_snapshot = SchedulePresenter.snapshot(window.session.draft)
            validation = window.validate_document()
            if validation is None or not validation.is_valid:
                raise RuntimeError("GUI smoke input did not pass formal validation")
            window.authoring_application.save(window.session, smoke.output)
            reopened = window.authoring_application.open_document(smoke.output)
            if SchedulePresenter.snapshot(reopened.draft) != original_snapshot:
                raise RuntimeError("GUI smoke round-trip changed the input document")
    except Exception:
        exit_code = 1
        if error_path is not None:
            error_path.write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        window._bind_session(None)
        window.close()
        app.exit(exit_code)
