"""Independent validation of final assignments and locked objective values."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .daily_patterns import (
    B_MAX_SINGLE_SHIFT_DAYS_PER_MONTH,
    DailyPattern,
    PATTERN_PERIODS,
)
from .class_preferences import (
    PreferenceDirection,
    class_opportunity_days,
)
from .enums import EmploymentType, FullTimeClass, ShiftMode
from .models import NormalizedScheduleInput
from .optimization_contracts import (
    ClassPatternLockResult,
    FairnessMetric,
    OptimizationStage,
    OptimizationStageResult,
    OptimizationStageStatus,
    PreferenceBenchmarkResult,
)
from .optimization_policy import (
    CLASS_PREFERENCES,
    CLASS_REMAINING_PATTERN_METRICS,
    FORMAL_OBJECTIVE_STAGES,
    FORMAL_STAGE_POLICY_BY_STAGE,
    FORMAL_STAGE_SEQUENCE,
)
from .result_metrics import RecomputedScheduleMetrics, recompute_schedule_metrics
from .solver_contracts import Assignment


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


def validate_schedule_result(
    data: NormalizedScheduleInput,
    assignments: tuple[Assignment, ...],
    stages: tuple[OptimizationStageResult, ...],
    preference_benchmarks: tuple[PreferenceBenchmarkResult, ...] = (),
    class_pattern_locks: tuple[ClassPatternLockResult, ...] = (),
) -> ValidationReport:
    """Validate without reading any CP-SAT variable or solver-derived pattern."""

    recomputed = recompute_schedule_metrics(
        data, assignments, preference_benchmarks
    )
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
        "preference_benchmarks": True,
        "class_pattern_locks": True,
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

        if employee.full_time_class is FullTimeClass.B:
            monthly_single_days = Counter(
                (day.year, day.month)
                for day in data.dates
                if recomputed.daily_patterns[(employee.employee_id, day)]
                in (
                    DailyPattern.MORNING_ONLY,
                    DailyPattern.AFTERNOON_ONLY,
                    DailyPattern.EVENING_ONLY,
                )
            )
            for (year, month), count in monthly_single_days.items():
                if count <= B_MAX_SINGLE_SHIFT_DAYS_PER_MONTH:
                    continue
                add(
                    "daily_patterns",
                    "b_monthly_single_shift_limit_exceeded",
                    (
                        f"B employees may have at most "
                        f"{B_MAX_SINGLE_SHIFT_DAYS_PER_MONTH} single-shift "
                        f"day in {year:04d}-{month:02d}; got {count}"
                    ),
                    employee_id=employee.employee_id,
                )

    stage_sequence = tuple(item.stage for item in stages)
    if stage_sequence != FORMAL_STAGE_SEQUENCE:
        add(
            "optimization_stages",
            "optimization_stage_sequence_mismatch",
            "formal optimization stages are missing, duplicated, or out of order",
        )
    for stage_result in stages:
        policy = FORMAL_STAGE_POLICY_BY_STAGE.get(stage_result.stage)
        if policy is not None and stage_result.direction is not policy.direction:
            add(
                "optimization_stages",
                "optimization_stage_direction_mismatch",
                "formal optimization stage direction does not match policy",
                stage=stage_result.stage,
            )
    benchmark_by_key = {
        (item.full_time_class, item.rank): item
        for item in preference_benchmarks
    }
    expected_benchmark_keys = {
        (item.full_time_class, item.rank) for item in CLASS_PREFERENCES
    }
    if (
        len(preference_benchmarks) != len(CLASS_PREFERENCES)
        or set(benchmark_by_key) != expected_benchmark_keys
    ):
        add(
            "preference_benchmarks",
            "preference_benchmark_structure_mismatch",
            "formal result requires one A and B benchmark for each preference rank",
        )
    for benchmark in preference_benchmarks:
        definition = next(
            (
                item
                for item in CLASS_PREFERENCES
                if item.full_time_class is benchmark.full_time_class
                and item.rank is benchmark.rank
            ),
            None,
        )
        if definition is None:
            continue
        if (
            benchmark.metric is not definition.metric
            or benchmark.direction is not definition.direction
            or benchmark.opportunity_days
            != class_opportunity_days(data, benchmark.full_time_class)
        ):
            add(
                "preference_benchmarks",
                "preference_benchmark_definition_mismatch",
                "preference benchmark does not match the formal class definition",
            )
        if benchmark.status not in (
            OptimizationStageStatus.OPTIMAL,
            OptimizationStageStatus.SKIPPED_CONSTANT,
        ):
            add(
                "preference_benchmarks",
                "preference_benchmark_not_optimal",
                "every preference ideal must be proven OPTIMAL or constant",
            )
        if benchmark.ideal_value is None:
            add(
                "preference_benchmarks",
                "preference_benchmark_missing_value",
                "preference benchmark is missing its ideal value",
            )
            continue
        key = (benchmark.full_time_class, benchmark.rank)
        actual = recomputed.class_preference_actual_values[key]
        if benchmark.locked_actual_value is None:
            add(
                "preference_benchmarks",
                "preference_locked_actual_missing",
                "formal preference benchmark is missing its locked actual value",
            )
        elif actual != benchmark.locked_actual_value:
            add(
                "preference_benchmarks",
                "preference_locked_actual_mismatch",
                (
                    f"recorded locked actual {benchmark.locked_actual_value}, "
                    f"recomputed {actual}"
                ),
            )
        is_better_than_ideal = (
            actual > benchmark.ideal_value
            if benchmark.direction is PreferenceDirection.MAXIMIZE
            else actual < benchmark.ideal_value
        )
        if is_better_than_ideal:
            add(
                "preference_benchmarks",
                "preference_benchmark_ideal_violated",
                "final assignment is better than its recorded proven ideal",
            )
    expected_pattern_locks = set(CLASS_REMAINING_PATTERN_METRICS.items())
    pattern_lock_by_key = {
        (item.full_time_class, item.metric): item
        for item in class_pattern_locks
    }
    if (
        len(class_pattern_locks) != len(expected_pattern_locks)
        or set(pattern_lock_by_key) != expected_pattern_locks
    ):
        add(
            "class_pattern_locks",
            "class_pattern_lock_structure_mismatch",
            "formal result requires A single-day and B triple-day class locks",
        )
    for key, item in pattern_lock_by_key.items():
        full_time_class, _metric = key
        actual = recomputed.class_remaining_pattern_actual_values[
            full_time_class
        ]
        if actual != item.locked_value:
            add(
                "class_pattern_locks",
                "class_pattern_lock_value_mismatch",
                (
                    f"recorded class pattern lock {item.locked_value}, "
                    f"recomputed {actual}"
                ),
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
