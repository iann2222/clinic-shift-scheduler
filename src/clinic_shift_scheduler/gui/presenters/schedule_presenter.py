"""Lossless mapping between weekly-v1 documents and mutable drafts."""

from __future__ import annotations

import json
from typing import Any

from ...authoring_models import WeeklyAuthoringDocument
from ...enums import PERIODS_V1
from ..drafts import (
    AvailableSlotDraft,
    DateOverrideDraft,
    EmployeeDraft,
    LeaveRequestDraft,
    ScheduleDraft,
    StaffingDraft,
    UnavailableSlotDraft,
    WeeklyDemandDraft,
)


class SchedulePresenter:
    @staticmethod
    def from_document(document: WeeklyAuthoringDocument) -> ScheduleDraft:
        def staffing(value: object | None) -> StaffingDraft | None:
            if value is None:
                return None
            payload = value.to_dict()
            return StaffingDraft(
                {
                    period: dict(payload[period.value])
                    for period in PERIODS_V1
                }
            )

        return ScheduleDraft(
            authoring_version=document.authoring_version,
            schema_version=document.schema_version,
            start_date=document.period.start_date,
            end_date=document.period.end_date,
            holidays=list(document.period.holidays),
            holidays_declared=document.period.holidays_declared,
            periods=list(document.periods),
            roles=list(document.roles),
            weekly_demands=[
                WeeklyDemandDraft(
                    weekdays=list(item.weekdays),
                    is_open=item.is_open,
                    staffing=staffing(item.staffing),
                )
                for item in document.weekly_demands
            ],
            date_overrides=[
                DateOverrideDraft(
                    date=item.date,
                    is_open=item.is_open,
                    staffing=staffing(item.staffing),
                )
                for item in document.date_overrides
            ],
            employees=[
                EmployeeDraft(
                    employee_id=item.employee_id,
                    name=item.name,
                    employment_type=item.employment_type,
                    full_time_class=item.full_time_class,
                    full_time_class_declared=item.full_time_class_declared,
                    roles=list(item.roles),
                    fairness_group=item.fairness_group,
                    shift_mode=item.shift_mode,
                    required_shifts=item.required_shifts,
                    target_shifts=item.target_shifts,
                    min_shifts=item.min_shifts,
                    max_shifts=item.max_shifts,
                    available_slots=(
                        None
                        if item.available_slots is None
                        else [
                            AvailableSlotDraft(
                                date=slot.date,
                                period=slot.period,
                                roles=None if slot.roles is None else list(slot.roles),
                            )
                            for slot in item.available_slots
                        ]
                    ),
                    notes=item.notes,
                    notes_declared=item.notes_declared,
                )
                for item in document.employees
            ],
            leave_requests=[
                LeaveRequestDraft(
                    employee_id=item.employee_id,
                    date=item.date,
                    all_day=item.all_day,
                    period=item.period,
                    note=item.note,
                    note_declared=item.note_declared,
                )
                for item in document.leave_requests
            ],
            unavailable_slots=[
                UnavailableSlotDraft(
                    employee_id=item.employee_id,
                    date=item.date,
                    period=item.period,
                )
                for item in document.unavailable_slots
            ],
            date_overrides_declared=document.date_overrides_declared,
            leave_requests_declared=document.leave_requests_declared,
            unavailable_slots_declared=document.unavailable_slots_declared,
        )

    @staticmethod
    def to_payload(draft: ScheduleDraft) -> dict[str, Any]:
        def staffing(value: StaffingDraft | None) -> dict[str, Any] | None:
            if value is None:
                return None
            return {
                period.value: dict(value.counts[period])
                for period in PERIODS_V1
            }

        payload: dict[str, Any] = {
            "authoring_version": draft.authoring_version,
            "schema_version": draft.schema_version,
            "period": {
                "start_date": draft.start_date.isoformat(),
                "end_date": draft.end_date.isoformat(),
            },
            "periods": [item.value for item in draft.periods],
            "roles": list(draft.roles),
            "weekly_demands": [],
            "employees": [],
        }
        if draft.holidays_declared:
            payload["period"]["holidays"] = [item.isoformat() for item in draft.holidays]
        for item in draft.weekly_demands:
            rule: dict[str, Any] = {
                "weekdays": [day.value for day in item.weekdays],
                "is_open": item.is_open,
            }
            if item.staffing is not None:
                rule["staffing"] = staffing(item.staffing)
            payload["weekly_demands"].append(rule)
        if draft.date_overrides_declared:
            payload["date_overrides"] = []
            for item in draft.date_overrides:
                override: dict[str, Any] = {
                    "date": item.date.isoformat(),
                    "is_open": item.is_open,
                }
                if item.staffing is not None:
                    override["staffing"] = staffing(item.staffing)
                payload["date_overrides"].append(override)
        for item in draft.employees:
            employee: dict[str, Any] = {
                "employee_id": item.employee_id,
                "name": item.name,
                "employment_type": item.employment_type.value,
                "roles": list(item.roles),
                "fairness_group": item.fairness_group,
                "shift_mode": item.shift_mode.value,
            }
            if item.full_time_class_declared:
                employee["full_time_class"] = (
                    None if item.full_time_class is None else item.full_time_class.value
                )
            for key in ("required_shifts", "target_shifts", "min_shifts", "max_shifts"):
                value = getattr(item, key)
                if value is not None:
                    employee[key] = value
            if item.available_slots is not None:
                employee["available_slots"] = []
                for slot in item.available_slots:
                    entry: dict[str, Any] = {
                        "date": slot.date.isoformat(),
                        "period": slot.period.value,
                    }
                    if slot.roles is not None:
                        entry["roles"] = list(slot.roles)
                    employee["available_slots"].append(entry)
            if item.notes_declared:
                employee["notes"] = item.notes
            payload["employees"].append(employee)
        if draft.leave_requests_declared:
            payload["leave_requests"] = []
            for item in draft.leave_requests:
                entry = {
                    "employee_id": item.employee_id,
                    "date": item.date.isoformat(),
                    "all_day": item.all_day,
                }
                if item.period is not None:
                    entry["period"] = item.period.value
                if item.note_declared:
                    entry["note"] = item.note
                payload["leave_requests"].append(entry)
        if draft.unavailable_slots_declared:
            payload["unavailable_slots"] = [
                {
                    "employee_id": item.employee_id,
                    "date": item.date.isoformat(),
                    "period": item.period.value,
                }
                for item in draft.unavailable_slots
            ]
        return payload

    @classmethod
    def to_document(cls, draft: ScheduleDraft) -> WeeklyAuthoringDocument:
        return WeeklyAuthoringDocument.from_dict(cls.to_payload(draft))

    @classmethod
    def snapshot(cls, draft: ScheduleDraft) -> str:
        return json.dumps(
            cls.to_payload(draft),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
