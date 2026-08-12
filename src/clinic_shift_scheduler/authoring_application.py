"""Lightweight application service for weekly input document lifecycle."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .authoring import (
    WEEKLY_AUTHORING_VERSION,
    load_weekly_authoring_document,
    write_weekly_authoring_document,
)
from .authoring_models import WeeklyAuthoringDocument
from .enums import PERIODS_V1, EmploymentType, Weekday
from .errors import InputValidationError
from .events import DiagnosticIssue
from .gui.drafts import ScheduleDraft, StaffingDraft, WeeklyDemandDraft
from .gui.presenters import SchedulePresenter


DEFAULT_NEW_DOCUMENT_ROLES = ("reception", "nursing")


class AuthoringFileExistsError(FileExistsError):
    """Raised when save-as would overwrite a file without permission."""


@dataclass(frozen=True, slots=True)
class AuthoringValidationResult:
    is_valid: bool
    issues: tuple[DiagnosticIssue, ...]
    document: WeeklyAuthoringDocument | None = None


@dataclass(slots=True)
class AuthoringSession:
    draft: ScheduleDraft
    path: Path | None = None
    _clean_snapshot: str | None = None

    @property
    def is_dirty(self) -> bool:
        if self._clean_snapshot is None:
            return True
        return SchedulePresenter.snapshot(self.draft) != self._clean_snapshot

    @property
    def month_label(self) -> str:
        return self.draft.start_date.strftime("%Y-%m")

    def mark_clean(self, path: str | Path) -> None:
        self.path = Path(path)
        self._clean_snapshot = SchedulePresenter.snapshot(self.draft)


def default_month_filename(year: int, month: int) -> str:
    return f"排班輸入_{year:04d}-{month:02d}.json"


class AuthoringApplication:
    """Create, open, validate, copy, and atomically save weekly drafts."""

    def create_month(
        self,
        year: int,
        month: int,
        *,
        roles: tuple[str, ...] = DEFAULT_NEW_DOCUMENT_ROLES,
    ) -> AuthoringSession:
        start, end = _month_bounds(year, month)
        role_list = list(roles)
        if not role_list or len(set(role_list)) != len(role_list):
            raise ValueError("roles must contain unique values and cannot be empty")
        rules = [
            WeeklyDemandDraft(
                weekdays=list(weekdays),
                is_open=False,
                staffing=None,
            )
            for weekdays in (
                (
                    Weekday.MONDAY,
                    Weekday.TUESDAY,
                    Weekday.WEDNESDAY,
                    Weekday.THURSDAY,
                    Weekday.FRIDAY,
                ),
                (Weekday.SATURDAY,),
                (Weekday.SUNDAY,),
            )
        ]
        return AuthoringSession(
            ScheduleDraft(
                authoring_version=WEEKLY_AUTHORING_VERSION,
                schema_version="v1",
                start_date=start,
                end_date=end,
                holidays=[],
                holidays_declared=True,
                periods=list(PERIODS_V1),
                roles=role_list,
                weekly_demands=rules,
                date_overrides=[],
                employees=[],
                leave_requests=[],
                unavailable_slots=[],
            )
        )

    def create_month_from_previous(
        self,
        source: str | Path | WeeklyAuthoringDocument,
        year: int,
        month: int,
    ) -> AuthoringSession:
        document = (
            source
            if isinstance(source, WeeklyAuthoringDocument)
            else load_weekly_authoring_document(source)
        )
        start, end = _month_bounds(year, month)
        if (
            document.period.start_date.year == year
            and document.period.start_date.month == month
        ):
            raise ValueError("目標月份不可與來源月份相同")
        draft = SchedulePresenter.from_document(document)
        draft.start_date = start
        draft.end_date = end
        draft.holidays = []
        draft.holidays_declared = True
        draft.date_overrides = []
        draft.date_overrides_declared = True
        draft.leave_requests = []
        draft.leave_requests_declared = True
        draft.unavailable_slots = []
        draft.unavailable_slots_declared = True
        for employee in draft.employees:
            if employee.employment_type is EmploymentType.PART_TIME:
                employee.available_slots = []
        draft.touch()
        return AuthoringSession(draft)

    def open_document(self, path: str | Path) -> AuthoringSession:
        resolved = Path(path)
        document = load_weekly_authoring_document(resolved)
        session = AuthoringSession(SchedulePresenter.from_document(document))
        session.mark_clean(resolved)
        return session

    def validate(self, draft: ScheduleDraft) -> AuthoringValidationResult:
        try:
            document = SchedulePresenter.to_document(draft)
        except InputValidationError as error:
            return AuthoringValidationResult(False, tuple(error.issues))
        except (TypeError, ValueError) as error:
            return AuthoringValidationResult(
                False,
                (
                    DiagnosticIssue(
                        code="invalid_draft",
                        path="$",
                        message=str(error),
                    ),
                ),
            )
        return AuthoringValidationResult(True, (), document)

    def save(
        self,
        session: AuthoringSession,
        path: str | Path | None = None,
        *,
        overwrite: bool = False,
    ) -> Path:
        target = Path(path) if path is not None else session.path
        if target is None:
            raise ValueError("尚未指定儲存路徑")
        is_same_current = session.path is not None and _same_path(target, session.path)
        if target.exists() and not overwrite and not is_same_current:
            raise AuthoringFileExistsError(f"檔案已存在：{target}")
        result = self.validate(session.draft)
        if not result.is_valid or result.document is None:
            raise InputValidationError(result.issues)
        saved = write_weekly_authoring_document(target, result.document)
        session.mark_clean(saved)
        return saved


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()
