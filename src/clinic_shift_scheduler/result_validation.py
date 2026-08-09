"""Independent validation of final assignments and locked objective values."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .daily_patterns import DailyPattern, PATTERN_PERIODS
from .enums import EmploymentType, FullTimeClass, ShiftMode
from .feasibility import Assignment
from .models import NormalizedScheduleInput
from .optimization import (
    OptimizationStage,
    OptimizationStageResult,
    OptimizationStageStatus,
)
from .result_metrics import RecomputedScheduleMetrics, recompute_schedule_metrics


class ResultValidationStatus(StrEnum):
    PASS = "PASS"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True, slots=True)
class ResultValidationIssue:
    category: str
    code: str
    message: str
    employee_id: str | None = None
    date: date | None = None
    stage: OptimizationStage | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    status: ResultValidationStatus
    checks: Mapping[str, bool]
    issues: tuple[ResultValidationIssue, ...]
    recomputed: RecomputedScheduleMetrics

    @property
    def is_valid(self) -> bool:
        return self.status is ResultValidationStatus.PASS


FORMAL_OBJECTIVE_STAGES: tuple[OptimizationStage, ...] = (
    OptimizationStage.FULL_TIME_TARGET_DEVIATION,
    OptimizationStage.PART_TIME_USAGE,
    OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES,
    OptimizationStage.FULL_TIME_CONSECUTIVE_RATIO_MAX_GAP,
    OptimizationStage.FULL_TIME_CONSECUTIVE_RATIO_TOTAL_GAP,
    OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS,
    OptimizationStage.FULL_TIME_SECONDARY_PATTERNS,
    OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
    OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP,
    OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
    OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
    OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
    OptimizationStage.PART_TIME_GROUP_FAIRNESS,
    OptimizationStage.COMMON_GROUP_FAIRNESS,
)
FORMAL_STAGE_SEQUENCE: tuple[OptimizationStage, ...] = (
    OptimizationStage.HARD_FEASIBILITY,
    *FORMAL_OBJECTIVE_STAGES,
)


def validate_schedule_result(
    data: NormalizedScheduleInput,
    assignments: tuple[Assignment, ...],
    stages: tuple[OptimizationStageResult, ...],
) -> ValidationReport:
    """Validate without reading any CP-SAT variable or solver-derived pattern."""

    recomputed = recompute_schedule_metrics(data, assignments)
    issues: list[ResultValidationIssue] = []
    checks = {
        "assignment_integrity": True,
        "demand_coverage": True,
        "role_qualification": True,
        "person_period_exclusivity": True,
        "availability_and_leave": True,
        "closed_dates": True,
        "shift_bounds": True,
        "daily_patterns": True,
        "total_shifts": True,
        "optimization_stages": True,
        "locked_objectives": True,
    }

    def add(
        category: str,
        code: str,
        message: str,
        *,
        employee_id: str | None = None,
        day: date | None = None,
        stage: OptimizationStage | None = None,
    ) -> None:
        checks[category] = False
        issues.append(
            ResultValidationIssue(
                category=category,
                code=code,
                message=message,
                employee_id=employee_id,
                date=day,
                stage=stage,
            )
        )

    duplicate_counts = Counter(assignments)
    for assignment, count in duplicate_counts.items():
        if count > 1:
            add(
                "assignment_integrity",
                "duplicate_assignment",
                f"assignment appears {count} times",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )

    valid_dates = set(data.dates)
    roles = set(data.source.roles)
    assignment_coverage = Counter(
        (item.date, item.period, item.role) for item in assignments
    )
    for assignment in assignments:
        employee = data.employees.get(assignment.employee_id)
        if employee is None:
            add(
                "assignment_integrity",
                "unknown_employee_id",
                f"unknown employee_id {assignment.employee_id!r}",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )
            continue
        if assignment.date not in valid_dates:
            add(
                "assignment_integrity",
                "assignment_date_out_of_range",
                "assignment date is outside the scheduling period",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )
        if assignment.role not in roles:
            add(
                "assignment_integrity",
                "unknown_role",
                f"unknown role {assignment.role!r}",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )
        elif assignment.role not in employee.roles:
            add(
                "role_qualification",
                "unqualified_role",
                f"employee is not qualified for {assignment.role!r}",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )
        if assignment.date in data.closed_dates:
            add(
                "closed_dates",
                "assignment_on_closed_date",
                "closed dates must not contain assignments",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )
        person_period = (
            assignment.employee_id,
            assignment.date,
            assignment.period,
        )
        if person_period in data.unavailable_periods:
            add(
                "availability_and_leave",
                "assignment_on_unavailable_period",
                "assignment overlaps unavailable_slots or leave_requests",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )
        assignment_key = (*person_period, assignment.role)
        if assignment_key not in data.allowed_assignments:
            add(
                "availability_and_leave",
                "assignment_not_allowed",
                "assignment is outside normalized availability",
                employee_id=assignment.employee_id,
                day=assignment.date,
            )

    for person_period, count in recomputed.person_period_counts.items():
        if count > 1:
            employee_id, day, _period = person_period
            add(
                "person_period_exclusivity",
                "multiple_roles_same_period",
                f"employee has {count} assignments in one period",
                employee_id=employee_id,
                day=day,
            )

    for key, required in data.demands.items():
        actual = assignment_coverage[key]
        if actual != required:
            day, period, role = key
            add(
                "demand_coverage",
                "demand_count_mismatch",
                (
                    f"({day}, {period.value}, {role}) requires {required}, "
                    f"got {actual}"
                ),
                day=day,
            )
    for key, actual in assignment_coverage.items():
        if key not in data.demands and actual:
            day, period, role = key
            add(
                "demand_coverage",
                "unexpected_demand_key",
                f"unexpected ({day}, {period.value}, {role}) has {actual} assignments",
                day=day,
            )

    expected_total = sum(data.demands.values())
    if len(assignments) != expected_total:
        add(
            "total_shifts",
            "total_assignment_mismatch",
            f"expected {expected_total} total assignments, got {len(assignments)}",
        )

    for employee in data.source.employees:
        actual = recomputed.employee_metrics[employee.employee_id].total_shifts
        if employee.shift_mode is ShiftMode.EXACT:
            if actual != employee.required_shifts:
                add(
                    "shift_bounds",
                    "exact_shift_mismatch",
                    f"EXACT requires {employee.required_shifts}, got {actual}",
                    employee_id=employee.employee_id,
                )
        elif employee.shift_mode is ShiftMode.RANGE:
            assert employee.min_shifts is not None and employee.max_shifts is not None
            if not employee.min_shifts <= actual <= employee.max_shifts:
                add(
                    "shift_bounds",
                    "range_shift_mismatch",
                    (
                        f"RANGE requires {employee.min_shifts}..{employee.max_shifts}, "
                        f"got {actual}"
                    ),
                    employee_id=employee.employee_id,
                )
        else:
            if employee.min_shifts is not None and actual < employee.min_shifts:
                add(
                    "shift_bounds",
                    "target_min_shift_mismatch",
                    f"TARGET minimum is {employee.min_shifts}, got {actual}",
                    employee_id=employee.employee_id,
                )
            if employee.max_shifts is not None and actual > employee.max_shifts:
                add(
                    "shift_bounds",
                    "target_max_shift_mismatch",
                    f"TARGET maximum is {employee.max_shifts}, got {actual}",
                    employee_id=employee.employee_id,
                )

        for day in data.dates:
            pattern = recomputed.daily_patterns[(employee.employee_id, day)]
            daily_count = len(PATTERN_PERIODS[pattern])
            if employee.employment_type is EmploymentType.PART_TIME:
                if daily_count > 2 or pattern is DailyPattern.TRIPLE:
                    add(
                        "daily_patterns",
                        "illegal_part_time_daily_pattern",
                        f"part-time pattern {pattern.value} is forbidden",
                        employee_id=employee.employee_id,
                        day=day,
                    )
            elif employee.full_time_class is FullTimeClass.A:
                if daily_count > 2 or pattern is DailyPattern.TRIPLE:
                    add(
                        "daily_patterns",
                        "illegal_a_daily_pattern",
                        f"A pattern {pattern.value} is forbidden",
                        employee_id=employee.employee_id,
                        day=day,
                    )
            elif pattern is DailyPattern.MORNING_EVENING:
                add(
                    "daily_patterns",
                    "illegal_b_daily_pattern",
                    "B employees cannot work morning+evening without afternoon",
                    employee_id=employee.employee_id,
                    day=day,
                )

    stage_sequence = tuple(item.stage for item in stages)
    if stage_sequence != FORMAL_STAGE_SEQUENCE:
        add(
            "optimization_stages",
            "optimization_stage_sequence_mismatch",
            "formal optimization stages are missing, duplicated, or out of order",
        )
    stage_by_name = {item.stage: item for item in stages}
    for stage_name in FORMAL_OBJECTIVE_STAGES:
        stage_result = stage_by_name.get(stage_name)
        if stage_result is None:
            continue
        recomputed_value = recomputed.objective_values[stage_name]
        if stage_result.objective_value != recomputed_value:
            add(
                "locked_objectives",
                "objective_value_mismatch",
                (
                    f"recorded {stage_result.objective_value}, "
                    f"recomputed {recomputed_value}"
                ),
                stage=stage_name,
            )
        if (
            stage_result.status is OptimizationStageStatus.OPTIMAL
            and not stage_result.locked
        ):
            add(
                "locked_objectives",
                "optimal_objective_not_locked",
                "an OPTIMAL objective must be locked before later stages",
                stage=stage_name,
            )
        if (
            stage_result.status is OptimizationStageStatus.SKIPPED_CONSTANT
            and stage_result.locked
        ):
            add(
                "locked_objectives",
                "constant_objective_marked_locked",
                "a skipped constant stage must not be marked locked",
                stage=stage_name,
            )

    status = (
        ResultValidationStatus.PASS
        if not issues
        else ResultValidationStatus.VALIDATION_FAILED
    )
    return ValidationReport(
        status=status,
        checks=MappingProxyType(checks),
        issues=tuple(issues),
        recomputed=recomputed,
    )
