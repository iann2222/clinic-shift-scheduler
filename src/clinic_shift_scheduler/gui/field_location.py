"""Map formal validation paths to concrete GUI pages and controls."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .navigation import PageId


@dataclass(frozen=True, slots=True)
class FieldLocation:
    page_id: PageId
    field: str | None = None
    employee_index: int | None = None
    weekly_index: int | None = None
    override_index: int | None = None
    record_type: str | None = None
    record_index: int | None = None
    available_slot_index: int | None = None
    period: str | None = None
    role: str | None = None


def resolve_field_location(path: str) -> FieldLocation:
    if path == "$.employees":
        return FieldLocation(PageId.EMPLOYEE, field="employees")
    if path == "$.weekly_demands":
        return FieldLocation(PageId.WEEKLY_DEMAND, field="weekly_demands")
    if path == "$.date_overrides":
        return FieldLocation(PageId.DATE_OVERRIDE, field="date_overrides")
    if path in {"$.leave_requests", "$.unavailable_slots"}:
        return FieldLocation(PageId.AVAILABILITY, field=path.removeprefix("$."))
    if path.startswith("$.roles"):
        return FieldLocation(PageId.MONTH_CLINIC, field="roles")
    if path.startswith("$.period.holidays"):
        return FieldLocation(PageId.MONTH_CLINIC, field="holidays")

    employee = re.match(r"\$\.employees\[(\d+)\](?:\.([A-Za-z_]+))?", path)
    if employee:
        employee_index = int(employee.group(1))
        field = employee.group(2)
        slot = re.match(
            r"\$\.employees\[\d+\]\.available_slots\[(\d+)\](?:\.([A-Za-z_]+))?",
            path,
        )
        if slot:
            return FieldLocation(
                PageId.AVAILABILITY,
                field=slot.group(2),
                employee_index=employee_index,
                available_slot_index=int(slot.group(1)),
            )
        return FieldLocation(
            PageId.EMPLOYEE,
            field=field,
            employee_index=employee_index,
        )

    weekly = re.match(r"\$\.weekly_demands\[(\d+)\](.*)", path)
    if weekly:
        period, role = _staffing_coordinates(weekly.group(2))
        return FieldLocation(
            PageId.WEEKLY_DEMAND,
            field=_last_field(weekly.group(2)),
            weekly_index=int(weekly.group(1)),
            period=period,
            role=role,
        )

    override = re.match(r"\$\.date_overrides\[(\d+)\](.*)", path)
    if override:
        period, role = _staffing_coordinates(override.group(2))
        return FieldLocation(
            PageId.DATE_OVERRIDE,
            field=_last_field(override.group(2)),
            override_index=int(override.group(1)),
            period=period,
            role=role,
        )

    record = re.match(
        r"\$\.(leave_requests|unavailable_slots)\[(\d+)\](?:\.([A-Za-z_]+))?",
        path,
    )
    if record:
        return FieldLocation(
            PageId.AVAILABILITY,
            field=record.group(3),
            record_type=record.group(1),
            record_index=int(record.group(2)),
        )

    field = _last_field(path)
    return FieldLocation(PageId.MONTH_CLINIC, field=field)


def _staffing_coordinates(suffix: str) -> tuple[str | None, str | None]:
    match = re.search(r"\.staffing\.(morning|afternoon|evening)\.([^\.]+)$", suffix)
    return (match.group(1), match.group(2)) if match else (None, None)


def _last_field(path: str) -> str | None:
    match = re.search(r"\.([A-Za-z_]+)$", path)
    return match.group(1) if match else None
