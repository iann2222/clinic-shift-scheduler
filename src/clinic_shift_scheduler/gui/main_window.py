"""Main desktop input-editor shell with stable workflow navigation."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QCloseEvent
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
from ..errors import InputValidationError
from ..events import DiagnosticIssue
from .dialogs import (
    MonthDialog,
    SettingsDialog,
    ask_yes_no,
    build_message_box,
    show_critical,
    show_information,
    show_warning,
)

from .navigation import NAVIGATION_ITEMS, PageId
from .pages import (
    AvailabilityPage,
    DateOverridePage,
    EmployeePage,
    MonthClinicPage,
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
        authoring_application: AuthoringApplication | None = None,
    ) -> None:
        super().__init__()
        self.authoring_application = authoring_application or AuthoringApplication()
        self.input_directory = Path(input_directory or Path.cwd() / "input")
        self.session: AuthoringSession | None = None
        self.setWindowTitle("診所排班系統－排班資料編輯器")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)

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
        self.availability_page = AvailabilityPage()
        self.review_save_page = ReviewSavePage()
        page_objects = (
            self.month_clinic_page,
            self.weekly_demand_page,
            self.date_override_page,
            self.employee_page,
            self.availability_page,
            self.review_save_page,
        )
        self._page_indexes: dict[PageId, int] = {}
        for page in page_objects:
            self._page_indexes[page.page_id] = self.page_stack.addWidget(page)

        if tuple(self._page_indexes) != tuple(
            item.page_id for item in NAVIGATION_ITEMS
        ):
            raise RuntimeError("page stack must follow the navigation contract")

        self.navigation.page_selected.connect(self.navigate_to)
        self.document_header.create_requested.connect(self._create_month_dialog)
        self.document_header.copy_previous_requested.connect(
            self._copy_previous_dialog
        )
        self.document_header.open_requested.connect(self._open_dialog)
        self.document_header.save_requested.connect(self.save_document)
        self.document_header.save_as_requested.connect(self.save_document_as)
        self.document_header.settings_requested.connect(self.open_settings)
        self.month_clinic_page.draft_changed.connect(self._structure_changed)
        self.weekly_demand_page.draft_changed.connect(self._draft_changed)
        self.date_override_page.draft_changed.connect(self._draft_changed)
        self.employee_page.draft_changed.connect(self._employees_changed)
        self.availability_page.draft_changed.connect(self._draft_changed)
        self.review_save_page.validate_requested.connect(self.validate_document)
        self.review_save_page.save_requested.connect(self.save_document)
        self.review_save_page.save_as_requested.connect(self.save_document_as)
        self.review_save_page.issue_activated.connect(self.navigate_to_issue)
        self._bind_session(None)
        self.navigate_to(PageId.MONTH_CLINIC)

    @property
    def page_ids(self) -> tuple[PageId, ...]:
        return tuple(self._page_indexes)

    def navigate_to(self, page_id: PageId) -> None:
        self.page_stack.setCurrentIndex(self._page_indexes[page_id])

    def open_settings(self) -> None:
        SettingsDialog(self).exec()

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
        path = issue.path
        if "available_slots" in path or path.startswith(
            ("$.leave_requests", "$.unavailable_slots")
        ):
            page_id = PageId.AVAILABILITY
        elif path.startswith("$.employees"):
            page_id = PageId.EMPLOYEE
        elif path.startswith("$.weekly_demands"):
            page_id = PageId.WEEKLY_DEMAND
        elif path.startswith("$.date_overrides"):
            page_id = PageId.DATE_OVERRIDE
        else:
            page_id = PageId.MONTH_CLINIC
        self.navigation.select_page(page_id)
        employee_match = re.match(r"\$\.employees\[(\d+)\]", path)
        if employee_match:
            employee_index = int(employee_match.group(1))
            if page_id is PageId.EMPLOYEE:
                self.employee_page.focus_employee(employee_index)
            else:
                self.availability_page.focus_employee(employee_index)
            slot_match = re.match(
                r"\$\.employees\[\d+\]\.available_slots\[(\d+)\]",
                path,
            )
            if slot_match:
                self.availability_page.focus_available_slot(
                    employee_index,
                    int(slot_match.group(1)),
                )
        record_match = re.match(
            r"\$\.(leave_requests|unavailable_slots)\[(\d+)\]",
            path,
        )
        if record_match:
            self.availability_page.focus_record(
                record_match.group(1),
                int(record_match.group(2)),
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_document_replacement():
            event.accept()
        else:
            event.ignore()

    def _bind_session(self, session: AuthoringSession | None) -> None:
        self.session = session
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
        self.availability_page.bind_draft(
            None if session is None else session.draft
        )
        self.review_save_page.clear_validation()
        self._refresh_document_header()

    def _draft_changed(self) -> None:
        self.review_save_page.clear_validation()
        self._refresh_document_header()

    def _structure_changed(self) -> None:
        if self.session is not None:
            self.weekly_demand_page.bind_draft(self.session.draft)
            self.date_override_page.bind_draft(self.session.draft)
            self.employee_page.bind_draft(self.session.draft)
        self._draft_changed()

    def _employees_changed(self) -> None:
        if self.session is not None:
            self.availability_page.bind_draft(self.session.draft)
        self._draft_changed()

    def _refresh_document_header(self) -> None:
        if self.session is None:
            self.document_header.set_document(
                month=None,
                path=None,
                state=DocumentState.NEW,
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
