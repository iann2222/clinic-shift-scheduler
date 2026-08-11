"""Shared hard monthly shift bounds for normalized employees."""

from __future__ import annotations

from .enums import ShiftMode
from .models import Employee


def hard_minimum_shifts(employee: Employee) -> int:
    """Return the employee's explicit hard monthly minimum."""

    if employee.shift_mode is ShiftMode.EXACT:
        assert employee.required_shifts is not None
        return employee.required_shifts
    return employee.min_shifts or 0


def hard_maximum_within_capacity(
    employee: Employee,
    physical_capacity: int,
) -> int:
    """Apply the employee's hard monthly maximum to physical capacity."""

    if employee.shift_mode is ShiftMode.EXACT:
        assert employee.required_shifts is not None
        return min(physical_capacity, employee.required_shifts)
    if employee.max_shifts is not None:
        return min(physical_capacity, employee.max_shifts)
    return physical_capacity
