"""Main desktop input-editor shell with stable workflow navigation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..authoring_application import (
    AuthoringApplication,
    AuthoringSession,
    AuthoringValidationResult,
    default_month_filename,
)
from ..config_application import ConfigApplication
from ..errors import InputValidationError
from ..events import DiagnosticIssue
from ..enums import EmploymentType
from .dialogs import (
    MonthDialog,
    SettingsDialog,
    ask_yes_no,
    build_message_box,
    show_critical,
    show_information,
    show_warning,
)
from .execution_controller import ExecutionController

from .navigation import NAVIGATION_ITEMS, PageId
from .field_location import resolve_field_location
from .pages import (
    DateOverridePage,
    EmployeePage,
    ExecutionPage,
    FullTimeUnavailablePage,
    MonthClinicPage,
    PartTimeAvailablePage,
    ReviewSavePage,
    WeeklyDemandPage,
)
from .widgets import DocumentHeader, NavigationSidebar
from .widgets.document_header import DocumentState


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        input_directory: str | Path | None = None,
        config_path: str | Path | None = None,
        authoring_application: AuthoringApplication | None = None,
        config_application: ConfigApplication | None = None,
    ) -> None:
        super().__init__()
        self.authoring_application = authoring_application or AuthoringApplication()
        self.config_application = config_application or ConfigApplication()
        self.input_directory = Path(input_directory or Path.cwd() / "input")
        self.config_path = Path(config_path or Path.cwd() / "config.json")
        self.application_root = self.config_path.resolve().parent
        self.session: AuthoringSession | None = None
        self._execution_locked = False
        self.setWindowTitle("診所排班系統")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.navigation = NavigationSidebar()
        root_layout.addWidget(self.navigation)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(16)
        root_layout.addWidget(content, 1)

        self.document_header = DocumentHeader()
        content_layout.addWidget(self.document_header)

        self.page_stack = QStackedWidget()
        content_layout.addWidget(self.page_stack, 1)

        self.month_clinic_page = MonthClinicPage()
        self.weekly_demand_page = WeeklyDemandPage()
        self.date_override_page = DateOverridePage()
        self.employee_page = EmployeePage()
        self.full_time_unavailable_page = FullTimeUnavailablePage()
        self.part_time_available_page = PartTimeAvailablePage()
        self.review_save_page = ReviewSavePage()
        self.execution_page = ExecutionPage()
        page_objects = (
            self.month_clinic_page,
            self.weekly_demand_page,
            self.date_override_page,
            self.employee_page,
            self.full_time_unavailable_page,
            self.part_time_available_page,
            self.review_save_page,
            self.execution_page,
        )
        self._page_indexes: dict[PageId, int] = {}
        for page in page_objects:
            self._page_indexes[page.page_id] = self.page_stack.addWidget(page)

        if tuple(self._page_indexes) != tuple(
            item.page_id for item in NAVIGATION_ITEMS
        ):
            raise RuntimeError("page stack must follow the navigation contract")

        self.navigation.page_selected.connect(self.navigate_to)
        self.month_clinic_page.create_requested.connect(self._create_month_dialog)
        self.month_clinic_page.copy_previous_requested.connect(
            self._copy_previous_dialog
        )
        self.month_clinic_page.open_requested.connect(self._open_dialog)
        self.document_header.save_requested.connect(self.save_document)
        self.document_header.save_as_requested.connect(self.save_document_as)
        self.document_header.settings_requested.connect(self.open_settings)
        self.month_clinic_page.draft_changed.connect(self._structure_changed)
        self.weekly_demand_page.draft_changed.connect(self._draft_changed)
        self.date_override_page.draft_changed.connect(self._draft_changed)
        self.employee_page.draft_changed.connect(self._employees_changed)
        self.full_time_unavailable_page.draft_changed.connect(self._draft_changed)
        self.part_time_available_page.draft_changed.connect(self._draft_changed)
        self.review_save_page.validate_requested.connect(self.validate_document)
        self.review_save_page.save_requested.connect(self.save_document)
        self.review_save_page.save_as_requested.connect(self.save_document_as)
        self.review_save_page.issue_activated.connect(self.navigate_to_issue)
        self.execution_controller = ExecutionController(
            self.application_root,
            self,
        )
        self.execution_page.run_requested.connect(self._start_schedule)
        self.execution_page.cancel_requested.connect(self._cancel_schedule)
        self.execution_page.stop_candidate_requested.connect(
            self._stop_candidate_processing
        )
        self.execution_page.open_output_requested.connect(
            self._open_output_directory
        )
        self.execution_controller.message_received.connect(
            self._show_execution_message
        )
        self.execution_controller.stderr_received.connect(
            self.execution_page.append_stderr
        )
        self.execution_controller.finished.connect(self._execution_finished)
        self._install_shortcuts()
        self._bind_session(None)
        self.navigate_to(PageId.MONTH_CLINIC)
        # Keep initial focus neutral instead of highlighting the only enabled
        # header action before a document has been opened.
        self.setFocus()

    @property
    def page_ids(self) -> tuple[PageId, ...]:
        return tuple(self._page_indexes)

    def navigate_to(self, page_id: PageId) -> None:
        self.page_stack.setCurrentIndex(self._page_indexes[page_id])

    def open_settings(self) -> None:
        try:
            config_session = self.config_application.open_document(
                self.config_path
            )
        except (InputValidationError, OSError, ValueError) as error:
            show_warning(
                self,
                "無法開啟設定",
                f"請先確認設定檔內容：\n{self.config_path}\n\n{error}",
            )
            return
        dialog = SettingsDialog(
            config_session.draft,
            config_path=self.config_path,
            input_directory=self.input_directory,
            current_document_path=(
                None if self.session is None else self.session.path
            ),
            parent=self,
        )
        def restore_defaults() -> None:
            config_session.restore_defaults()
            dialog.reload_from_draft()

        dialog.defaults_restored.connect(restore_defaults)
        if not dialog.exec():
            return
        try:
            self.config_application.save(config_session)
        except InputValidationError as error:
            show_warning(
                self,
                "設定內容有誤",
                "\n".join(issue.message for issue in error.issues),
            )
        except OSError as error:
            show_critical(self, "設定儲存失敗", str(error))

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("建立月份", QKeySequence.StandardKey.New, self._create_month_dialog),
            ("開啟", QKeySequence.StandardKey.Open, self._open_dialog),
            ("儲存", QKeySequence.StandardKey.Save, self.save_document),
            ("另存", QKeySequence.StandardKey.SaveAs, self.save_document_as),
            ("檢查輸入資料", QKeySequence("Ctrl+Shift+V"), self.validate_document),
        )
        self.document_actions: dict[str, QAction] = {}
        for label, shortcut, callback in shortcuts:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
            self.addAction(action)
            self.document_actions[label] = action

    def create_new_month(self, year: int, month: int) -> None:
        self._bind_session(self.authoring_application.create_month(year, month))

    def create_from_previous(
        self,
        source: str | Path,
        year: int,
        month: int,
    ) -> None:
        self._bind_session(
            self.authoring_application.create_month_from_previous(
                source,
                year,
                month,
            )
        )

    def open_document_path(self, path: str | Path) -> None:
        self._bind_session(self.authoring_application.open_document(path))

    def validate_document(self) -> AuthoringValidationResult | None:
        if self.session is None:
            show_information(self, "尚未開啟文件", "請先建立或開啟月份。")
            return None
        result = self.authoring_application.validate(self.session.draft)
        self.review_save_page.show_validation(
            is_valid=result.is_valid,
            issues=result.issues,
        )
        self.navigate_to(PageId.REVIEW_SAVE)
        return result

    def save_document(self) -> bool:
        if self.session is None:
            show_information(self, "尚未開啟文件", "請先建立或開啟月份。")
            return False
        if self.session.path is None:
            return self.save_document_as()
        return self._save_to(self.session.path, overwrite=True)

    def save_document_as(self) -> bool:
        if self.session is None:
            show_information(self, "尚未開啟文件", "請先建立或開啟月份。")
            return False
        self.input_directory.mkdir(parents=True, exist_ok=True)
        suggested = self.input_directory / default_month_filename(
            self.session.draft.start_date.year,
            self.session.draft.start_date.month,
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "另存排班輸入",
            str(suggested),
            "JSON files (*.json)",
        )
        if not path:
            return False
        target = Path(path)
        if target.exists() and not self._confirm_overwrite(target):
            return False
        return self._save_to(target, overwrite=True)

    def navigate_to_issue(self, issue: DiagnosticIssue) -> None:
        location = resolve_field_location(issue.path)
        if (
            self.session is not None
            and location.record_type is not None
            and location.record_index is not None
        ):
            records = (
                self.session.draft.leave_requests
                if location.record_type == "leave_requests"
                else self.session.draft.unavailable_slots
            )
            if 0 <= location.record_index < len(records):
                employee_id = records[location.record_index].employee_id
                employee_index = next(
                    (
                        index
                        for index, employee in enumerate(
                            self.session.draft.employees
                        )
                        if employee.employee_id == employee_id
                    ),
                    None,
                )
                if employee_index is not None:
                    employee = self.session.draft.employees[employee_index]
                    location = replace(
                        location,
                        page_id=(
                            PageId.PART_TIME_AVAILABLE
                            if employee.employment_type
                            is EmploymentType.PART_TIME
                            else PageId.FULL_TIME_UNAVAILABLE
                        ),
                        employee_index=employee_index,
                    )
        self.navigation.select_page(location.page_id)
        if location.page_id is PageId.EMPLOYEE:
            self.employee_page.focus_location(location)
        elif location.page_id is PageId.PART_TIME_AVAILABLE:
            self.part_time_available_page.focus_location(location)
        elif location.page_id is PageId.FULL_TIME_UNAVAILABLE:
            self.full_time_unavailable_page.focus_location(location)
        elif location.page_id is PageId.WEEKLY_DEMAND:
            self.weekly_demand_page.focus_location(location)
        elif location.page_id is PageId.DATE_OVERRIDE:
            self.date_override_page.focus_location(location)
        else:
            self.month_clinic_page.focus_location(location)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.execution_controller.is_running:
            if not ask_yes_no(
                self,
                "排班仍在進行",
                "排班尚未完成，關閉程式會取消本次執行。確定要關閉嗎？",
            ):
                event.ignore()
                return
            self.execution_controller.stop_for_shutdown()
        if self._allow_document_replacement():
            event.accept()
        else:
            event.ignore()

    def _bind_session(self, session: AuthoringSession | None) -> None:
        self.session = session
        self.execution_page.reset_for_document()
        self.navigation.set_document_available(session is not None)
        self.month_clinic_page.bind_draft(
            None if session is None else session.draft
        )
        self.weekly_demand_page.bind_draft(
            None if session is None else session.draft
        )
        self.date_override_page.bind_draft(
            None if session is None else session.draft
        )
        self.employee_page.bind_draft(
            None if session is None else session.draft
        )
        self.full_time_unavailable_page.bind_draft(
            None if session is None else session.draft
        )
        self.part_time_available_page.bind_draft(
            None if session is None else session.draft
        )
        self.review_save_page.clear_validation()
        self._refresh_document_header()

    def _draft_changed(self) -> None:
        self.review_save_page.clear_validation()
        self.execution_page.mark_input_changed()
        self._refresh_document_header()

    def _structure_changed(self) -> None:
        if self.session is not None:
            self.weekly_demand_page.bind_draft(self.session.draft)
            self.date_override_page.bind_draft(self.session.draft)
            self.employee_page.bind_draft(self.session.draft)
        self._draft_changed()

    def _employees_changed(self) -> None:
        if self.session is not None:
            self.full_time_unavailable_page.bind_draft(self.session.draft)
            self.part_time_available_page.bind_draft(self.session.draft)
        self._draft_changed()

    def _refresh_document_header(self) -> None:
        if self.session is None:
            self.document_header.set_document(
                month=None,
                path=None,
                state=DocumentState.NEW,
            )
            self.execution_page.bind_document(
                month=None,
                path=None,
                config_path=self.config_path,
            )
            return
        state = (
            DocumentState.DIRTY
            if self.session.is_dirty
            else DocumentState.CLEAN
        )
        self.document_header.set_document(
            month=self.session.month_label,
            path=self.session.path,
            state=state,
        )
        self.execution_page.bind_document(
            month=self.session.month_label,
            path=self.session.path,
            config_path=self.config_path,
        )

    def _save_to(self, target: Path, *, overwrite: bool) -> bool:
        assert self.session is not None
        try:
            self.authoring_application.save(
                self.session,
                target,
                overwrite=overwrite,
            )
        except InputValidationError as error:
            self.review_save_page.show_validation(
                is_valid=False,
                issues=tuple(error.issues),
            )
            self.navigate_to(PageId.REVIEW_SAVE)
            show_warning(
                self,
                "無法儲存",
                "輸入資料仍有問題，請依清單修正後再儲存。",
            )
            return False
        except OSError as error:
            show_critical(self, "儲存失敗", str(error))
            return False
        self.review_save_page.show_validation(is_valid=True, issues=())
        self._refresh_document_header()
        return True

    def _create_month_dialog(self) -> None:
        if not self._allow_document_replacement():
            return
        dialog = MonthDialog(
            "建立月份",
            "建立一份新的月份資料，之後再填寫需求與員工。",
            parent=self,
        )
        if dialog.exec():
            self.create_new_month(*dialog.year_month)

    def _copy_previous_dialog(self) -> None:
        if not self._allow_document_replacement():
            return
        source, _ = QFileDialog.getOpenFileName(
            self,
            "選擇上個月排班輸入",
            str(self.input_directory),
            "JSON files (*.json)",
        )
        if not source:
            return
        dialog = MonthDialog(
            "從上月建立",
            "保留週間模板與人員，清除所有日期綁定資料。",
            parent=self,
        )
        if dialog.exec():
            try:
                self.create_from_previous(source, *dialog.year_month)
            except (InputValidationError, OSError, ValueError) as error:
                show_warning(self, "無法建立月份", str(error))

    def _open_dialog(self) -> None:
        if not self._allow_document_replacement():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "開啟排班輸入",
            str(self.input_directory),
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            self.open_document_path(path)
        except (InputValidationError, OSError, ValueError) as error:
            show_warning(self, "無法開啟文件", str(error))

    def _allow_document_replacement(self) -> bool:
        if self.execution_controller.is_running:
            show_information(
                self,
                "排班仍在進行",
                "請先等待排班完成，或在「執行排班」頁取消本次執行。",
            )
            return False
        if self.session is None or not self.session.is_dirty:
            return True
        message = build_message_box(
            self,
            QMessageBox.Icon.Warning,
            "尚未儲存的修改",
            "目前文件仍有尚未儲存的修改。",
            informative_text="要先儲存後再繼續嗎？",
            buttons=(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            ),
        )
        answer = message.exec()
        if answer == QMessageBox.StandardButton.Save:
            return self.save_document()
        return answer == QMessageBox.StandardButton.Discard

    def _confirm_overwrite(self, target: Path) -> bool:
        return ask_yes_no(
            self,
            "覆寫既有檔案",
            f"檔案已存在，確定要覆寫嗎？\n{target}",
        )

    def _start_schedule(self) -> None:
        if self.session is None or self.execution_controller.is_running:
            return
        validation = self.authoring_application.validate(self.session.draft)
        if not validation.is_valid:
            self.review_save_page.show_validation(
                is_valid=False,
                issues=validation.issues,
            )
            self.navigate_to(PageId.REVIEW_SAVE)
            show_warning(
                self,
                "輸入資料尚未通過檢查",
                "請先修正檢查清單中的問題，再執行排班。",
            )
            return
        if self.session.path is None or self.session.is_dirty:
            if not self.save_document():
                return
        assert self.session.path is not None
        try:
            self.config_application.open_document(self.config_path)
        except (InputValidationError, OSError, ValueError) as error:
            show_warning(
                self,
                "排班設定無法使用",
                f"請先修正設定內容：\n{error}",
            )
            return

        self.navigate_to(PageId.EXECUTION)
        self.execution_page.begin()
        self._set_execution_locked(True)
        try:
            self.execution_controller.start(
                config_path=self.config_path,
                input_path=self.session.path,
                output_directory=self.application_root / "output",
                intermediate_directory=(
                    self.application_root / "runtime" / "expanded-input"
                ),
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.execution_page.show_message(
                {
                    "type": "failed",
                    "kind": "WORKER_START_FAILED",
                    "message": str(error),
                    "issues": [],
                }
            )
            self.execution_page.process_finished()
            self._set_execution_locked(False)

    def _cancel_schedule(self) -> None:
        if not self.execution_controller.is_running:
            return
        self.execution_page.request_cancelling()
        self.execution_controller.cancel()

    def _stop_candidate_processing(self) -> None:
        if not self.execution_controller.is_running:
            return
        self.execution_page.request_candidate_stopping()
        self.execution_controller.cancel()

    def _show_execution_message(self, message: dict[str, object]) -> None:
        self.execution_page.show_message(message)

    def _execution_finished(self, _exit_code: int) -> None:
        self.execution_page.process_finished()
        self._set_execution_locked(False)

    def _set_execution_locked(self, locked: bool) -> None:
        self._execution_locked = locked
        self.navigation.list_widget.setEnabled(
            not locked and self.session is not None
        )
        for button in self.document_header.document_action_buttons:
            button.setEnabled(not locked and self.session is not None)
        self.document_header.settings_button.setEnabled(not locked)
        for action in self.document_actions.values():
            action.setEnabled(not locked)

    def _open_output_directory(self, directory: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(directory))
