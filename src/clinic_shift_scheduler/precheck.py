"""Conservative necessary-condition checks run before CP-SAT.

A ``CONTINUE`` result only means these checks did not prove infeasibility. It
does not prove that the complete hard-constraint model has a solution.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .daily_patterns import PATTERN_PERIODS, allowed_daily_patterns
from .enums import PERIODS_V1, Period, ShiftMode
from .models import Employee, NormalizedScheduleInput


class PrecheckStatus(StrEnum):
    CONTINUE = "CONTINUE"
    PRECHECK_INFEASIBLE = "PRECHECK_INFEASIBLE"


class PrecheckDiagnosticCode(StrEnum):
    TOTAL_CAPACITY_SHORTAGE = "TOTAL_CAPACITY_SHORTAGE"
    HARD_MINIMUM_EXCEEDS_TOTAL_DEMAND = "HARD_MINIMUM_EXCEEDS_TOTAL_DEMAND"
    EMPLOYEE_HARD_MINIMUM_EXCEEDS_CAPACITY = (
        "EMPLOYEE_HARD_MINIMUM_EXCEEDS_CAPACITY"
    )
    ROLE_CAPACITY_SHORTAGE = "ROLE_CAPACITY_SHORTAGE"
    SLOT_ROLE_SHORTAGE = "SLOT_ROLE_SHORTAGE"
    SLOT_MATCHING_SHORTAGE = "SLOT_MATCHING_SHORTAGE"


@dataclass(frozen=True, slots=True)
class PrecheckDiagnostic:
    code: PrecheckDiagnosticCode
    message: str
    required: int
    available: int
    shortage: int
    date: date | None = None
    period: Period | None = None
    role: str | None = None
    employee_id: str | None = None
    related_roles: tuple[str, ...] = ()
    eligible_employee_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrecheckResult:
    status: PrecheckStatus
    diagnostics: tuple[PrecheckDiagnostic, ...]
    total_demand: int
    total_capacity: int
    employee_capacities: Mapping[str, int]
    role_capacities: Mapping[str, int]

    @property
    def is_infeasible(self) -> bool:
        return self.status is PrecheckStatus.PRECHECK_INFEASIBLE


def _hard_minimum(employee: Employee) -> int:
    if employee.shift_mode is ShiftMode.EXACT:
        assert employee.required_shifts is not None
        return employee.required_shifts
    return employee.min_shifts or 0


def _apply_hard_maximum(employee: Employee, physical_capacity: int) -> int:
    if employee.shift_mode is ShiftMode.EXACT:
        assert employee.required_shifts is not None
        return min(physical_capacity, employee.required_shifts)
    if employee.max_shifts is not None:
        return min(physical_capacity, employee.max_shifts)
    return physical_capacity


def _maximum_daily_count(employee: Employee, available: frozenset[Period]) -> int:
    return max(
        len(periods)
        for pattern in allowed_daily_patterns(
            employee.employment_type, employee.full_time_class
        )
        if (periods := PATTERN_PERIODS[pattern]).issubset(available)
    )


def _maximum_daily_role_count(
    employee: Employee,
    available: frozenset[Period],
    role_available: frozenset[Period],
) -> int:
    return max(
        len(periods & role_available)
        for pattern in allowed_daily_patterns(
            employee.employment_type, employee.full_time_class
        )
        if (periods := PATTERN_PERIODS[pattern]).issubset(available)
    )


def _maximum_slot_matching(
    demand_by_role: Mapping[str, int],
    eligible_by_role: Mapping[str, tuple[str, ...]],
) -> int:
    """Return a maximum role-unit-to-employee bipartite matching size."""

    units = tuple(
        (role, unit_index)
        for role in sorted(demand_by_role)
        for unit_index in range(demand_by_role[role])
    )
    matched_employee: dict[str, tuple[str, int]] = {}

    def augment(unit: tuple[str, int], seen: set[str]) -> bool:
        role, _ = unit
        for employee_id in eligible_by_role.get(role, ()):
            if employee_id in seen:
                continue
            seen.add(employee_id)
            prior = matched_employee.get(employee_id)
            if prior is None or augment(prior, seen):
                matched_employee[employee_id] = unit
                return True
        return False

    return sum(augment(unit, set()) for unit in units)


def run_prechecks(data: NormalizedScheduleInput) -> PrecheckResult:
    """Run fast, conservative checks that can prove selected infeasible cases."""

    diagnostics: list[PrecheckDiagnostic] = []
    periods_by_employee_day: dict[tuple[str, date], set[Period]] = defaultdict(set)
    periods_by_employee_day_role: dict[tuple[str, date, str], set[Period]] = (
        defaultdict(set)
    )
    eligible_by_slot_role: dict[tuple[date, Period, str], set[str]] = defaultdict(set)

    for employee_id, day, period, role in data.allowed_assignments:
        periods_by_employee_day[(employee_id, day)].add(period)
        periods_by_employee_day_role[(employee_id, day, role)].add(period)
        eligible_by_slot_role[(day, period, role)].add(employee_id)

    employee_capacities: dict[str, int] = {}
    for employee in data.source.employees:
        physical_capacity = sum(
            _maximum_daily_count(
                employee,
                frozenset(periods_by_employee_day[(employee.employee_id, day)]),
            )
            for day in data.open_dates
        )
        capacity = _apply_hard_maximum(employee, physical_capacity)
        employee_capacities[employee.employee_id] = capacity
        hard_minimum = _hard_minimum(employee)
        if hard_minimum > capacity:
            diagnostics.append(
                PrecheckDiagnostic(
                    code=(
                        PrecheckDiagnosticCode.EMPLOYEE_HARD_MINIMUM_EXCEEDS_CAPACITY
                    ),
                    message=(
                        f"Employee {employee.employee_id} requires at least "
                        f"{hard_minimum} shifts but can cover at most {capacity}."
                    ),
                    employee_id=employee.employee_id,
                    required=hard_minimum,
                    available=capacity,
                    shortage=hard_minimum - capacity,
                )
            )

    total_demand = sum(data.demands.values())
    total_capacity = sum(employee_capacities.values())
    if total_capacity < total_demand:
        diagnostics.append(
            PrecheckDiagnostic(
                code=PrecheckDiagnosticCode.TOTAL_CAPACITY_SHORTAGE,
                message=(
                    f"Total demand is {total_demand} shifts but maximum capacity is "
                    f"{total_capacity}."
                ),
                required=total_demand,
                available=total_capacity,
                shortage=total_demand - total_capacity,
            )
        )

    total_hard_minimum = sum(
        _hard_minimum(employee) for employee in data.source.employees
    )
    if total_hard_minimum > total_demand:
        diagnostics.append(
            PrecheckDiagnostic(
                code=PrecheckDiagnosticCode.HARD_MINIMUM_EXCEEDS_TOTAL_DEMAND,
                message=(
                    f"Employee hard minimums total {total_hard_minimum} shifts but "
                    f"total demand is only {total_demand}."
                ),
                required=total_hard_minimum,
                available=total_demand,
                shortage=total_hard_minimum - total_demand,
            )
        )

    role_capacities: dict[str, int] = {}
    for role in data.source.roles:
        capacity = 0
        for employee in data.source.employees:
            if role not in employee.roles:
                continue
            physical_role_capacity = sum(
                _maximum_daily_role_count(
                    employee,
                    frozenset(
                        periods_by_employee_day[(employee.employee_id, day)]
                    ),
                    frozenset(
                        periods_by_employee_day_role[
                            (employee.employee_id, day, role)
                        ]
                    ),
                )
                for day in data.open_dates
            )
            capacity += _apply_hard_maximum(employee, physical_role_capacity)
        role_capacities[role] = capacity
        role_demand = sum(
            count
            for (day, period, demand_role), count in data.demands.items()
            if demand_role == role
        )
        if capacity < role_demand:
            diagnostics.append(
                PrecheckDiagnostic(
                    code=PrecheckDiagnosticCode.ROLE_CAPACITY_SHORTAGE,
                    message=(
                        f"Role {role} needs {role_demand} shifts but its maximum "
                        f"qualified capacity is {capacity}."
                    ),
                    role=role,
                    required=role_demand,
                    available=capacity,
                    shortage=role_demand - capacity,
                )
            )

    for day in data.open_dates:
        for period in PERIODS_V1:
            demand_by_role = {
                role: data.demands[(day, period, role)]
                for role in data.source.roles
                if data.demands[(day, period, role)] > 0
            }
            if not demand_by_role:
                continue
            eligible_by_role = {
                role: tuple(
                    sorted(
                        employee_id
                        for employee_id in eligible_by_slot_role[
                            (day, period, role)
                        ]
                        if employee_capacities[employee_id] > 0
                    )
                )
                for role in demand_by_role
            }
            for role, required in demand_by_role.items():
                eligible = eligible_by_role[role]
                if len(eligible) < required:
                    diagnostics.append(
                        PrecheckDiagnostic(
                            code=PrecheckDiagnosticCode.SLOT_ROLE_SHORTAGE,
                            message=(
                                f"{day.isoformat()} {period.value} role {role} needs "
                                f"{required} people but only {len(eligible)} are eligible."
                            ),
                            date=day,
                            period=period,
                            role=role,
                            required=required,
                            available=len(eligible),
                            shortage=required - len(eligible),
                            eligible_employee_ids=eligible,
                        )
                    )

            slot_demand = sum(demand_by_role.values())
            matched = _maximum_slot_matching(demand_by_role, eligible_by_role)
            if matched < slot_demand:
                all_eligible = tuple(
                    sorted(
                        {
                            employee_id
                            for employee_ids in eligible_by_role.values()
                            for employee_id in employee_ids
                        }
                    )
                )
                roles = tuple(sorted(demand_by_role))
                diagnostics.append(
                    PrecheckDiagnostic(
                        code=PrecheckDiagnosticCode.SLOT_MATCHING_SHORTAGE,
                        message=(
                            f"{day.isoformat()} {period.value} needs {slot_demand} "
                            f"people across roles {', '.join(roles)}, but at most "
                            f"{matched} distinct people can be matched."
                        ),
                        date=day,
                        period=period,
                        required=slot_demand,
                        available=matched,
                        shortage=slot_demand - matched,
                        related_roles=roles,
                        eligible_employee_ids=all_eligible,
                    )
                )

    status = (
        PrecheckStatus.PRECHECK_INFEASIBLE
        if diagnostics
        else PrecheckStatus.CONTINUE
    )
    return PrecheckResult(
        status=status,
        diagnostics=tuple(diagnostics),
        total_demand=total_demand,
        total_capacity=total_capacity,
        employee_capacities=MappingProxyType(employee_capacities),
        role_capacities=MappingProxyType(role_capacities),
    )
