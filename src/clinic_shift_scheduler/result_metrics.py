"""Pure recomputation of schedule facts from assignments and normalized input."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping

from .daily_patterns import DailyPattern, PATTERN_PERIODS
from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period
from .feasibility import Assignment, DemandKey, PersonDayKey, PersonPeriodKey
from .models import NormalizedScheduleInput
from .optimization import FairnessMetric, OptimizationStage


_PATTERN_BY_PERIODS = {
    periods: pattern for pattern, periods in PATTERN_PERIODS.items()
}
_CONSECUTIVE = frozenset(
    (DailyPattern.MORNING_AFTERNOON, DailyPattern.AFTERNOON_EVENING)
)
_SINGLES = frozenset(
    (
        DailyPattern.MORNING_ONLY,
        DailyPattern.AFTERNOON_ONLY,
        DailyPattern.EVENING_ONLY,
    )
)


@dataclass(frozen=True, slots=True)
class EmployeeResultMetrics:
    employee_id: str
    total_shifts: int
    role_counts: Mapping[str, int]
    period_counts: Mapping[Period, int]
    attendance_days: int
    single_shift_days: int
    consecutive_double_days: int
    morning_afternoon_days: int
    afternoon_evening_days: int
    morning_evening_days: int
    triple_days: int
    sunday_shifts: int
    holiday_shifts: int


@dataclass(frozen=True, slots=True)
class RecomputedScheduleMetrics:
    coverage: Mapping[DemandKey, int]
    person_period_counts: Mapping[PersonPeriodKey, int]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    employee_metrics: Mapping[str, EmployeeResultMetrics]
    fairness_gaps: Mapping[
        OptimizationStage, Mapping[tuple[str, FairnessMetric], int]
    ]
    objective_values: Mapping[OptimizationStage, int]
    total_assignments: int


def _gap(values: list[int]) -> int:
    return max(values) - min(values)


def recompute_schedule_metrics(
    data: NormalizedScheduleInput,
    assignments: tuple[Assignment, ...],
) -> RecomputedScheduleMetrics:
    """Recompute all v1 hard facts and objective values without solver state."""

    coverage = Counter((item.date, item.period, item.role) for item in assignments)
    person_period_counts = Counter(
        (item.employee_id, item.date, item.period) for item in assignments
    )
    assignments_by_employee: dict[str, list[Assignment]] = defaultdict(list)
    periods_by_person_day: dict[PersonDayKey, set[Period]] = defaultdict(set)
    for assignment in assignments:
        if assignment.employee_id not in data.employees:
            continue
        assignments_by_employee[assignment.employee_id].append(assignment)
        if assignment.date in data.dates:
            periods_by_person_day[(assignment.employee_id, assignment.date)].add(
                assignment.period
            )

    daily_patterns: dict[PersonDayKey, DailyPattern] = {}
    employee_metrics: dict[str, EmployeeResultMetrics] = {}
    for employee in data.source.employees:
        employee_id = employee.employee_id
        pattern_counts: Counter[DailyPattern] = Counter()
        for day in data.dates:
            periods = frozenset(periods_by_person_day[(employee_id, day)])
            pattern = _PATTERN_BY_PERIODS.get(periods, DailyPattern.OFF)
            daily_patterns[(employee_id, day)] = pattern
            pattern_counts[pattern] += 1

        employee_assignments = assignments_by_employee[employee_id]
        role_counts = Counter(item.role for item in employee_assignments)
        period_counts = Counter(item.period for item in employee_assignments)
        employee_metrics[employee_id] = EmployeeResultMetrics(
            employee_id=employee_id,
            total_shifts=len(employee_assignments),
            role_counts=MappingProxyType(
                {role: role_counts[role] for role in data.source.roles}
            ),
            period_counts=MappingProxyType(
                {period: period_counts[period] for period in PERIODS_V1}
            ),
            attendance_days=len(
                {
                    item.date
                    for item in employee_assignments
                    if item.date in data.dates
                }
            ),
            single_shift_days=sum(pattern_counts[item] for item in _SINGLES),
            consecutive_double_days=sum(
                pattern_counts[item] for item in _CONSECUTIVE
            ),
            morning_afternoon_days=pattern_counts[
                DailyPattern.MORNING_AFTERNOON
            ],
            afternoon_evening_days=pattern_counts[
                DailyPattern.AFTERNOON_EVENING
            ],
            morning_evening_days=pattern_counts[DailyPattern.MORNING_EVENING],
            triple_days=pattern_counts[DailyPattern.TRIPLE],
            sunday_shifts=sum(
                item.date.weekday() == 6 for item in employee_assignments
            ),
            holiday_shifts=sum(
                item.date in data.source.period.holidays
                for item in employee_assignments
            ),
        )

    def metric_value(employee_id: str, metric: FairnessMetric) -> int:
        values = employee_metrics[employee_id]
        return {
            FairnessMetric.CONSECUTIVE_DOUBLES: values.consecutive_double_days,
            FairnessMetric.SINGLE_SHIFT_DAYS: values.single_shift_days,
            FairnessMetric.MORNING_EVENING_DAYS: values.morning_evening_days,
            FairnessMetric.TRIPLE_DAYS: values.triple_days,
            FairnessMetric.TOTAL_SHIFTS: values.total_shifts,
            FairnessMetric.MORNING_SHIFTS: values.period_counts[Period.MORNING],
            FairnessMetric.AFTERNOON_SHIFTS: values.period_counts[
                Period.AFTERNOON
            ],
            FairnessMetric.EVENING_SHIFTS: values.period_counts[Period.EVENING],
            FairnessMetric.SUNDAY_SHIFTS: values.sunday_shifts,
            FairnessMetric.HOLIDAY_SHIFTS: values.holiday_shifts,
        }[metric]

    stage_members_and_metrics = {
        OptimizationStage.A_GROUP_FAIRNESS: (
            tuple(
                employee
                for employee in data.source.employees
                if employee.full_time_class is FullTimeClass.A
            ),
            (
                FairnessMetric.CONSECUTIVE_DOUBLES,
                FairnessMetric.SINGLE_SHIFT_DAYS,
                FairnessMetric.MORNING_EVENING_DAYS,
            ),
        ),
        OptimizationStage.B_GROUP_FAIRNESS: (
            tuple(
                employee
                for employee in data.source.employees
                if employee.full_time_class is FullTimeClass.B
            ),
            (
                FairnessMetric.CONSECUTIVE_DOUBLES,
                FairnessMetric.SINGLE_SHIFT_DAYS,
                FairnessMetric.TRIPLE_DAYS,
            ),
        ),
        OptimizationStage.PART_TIME_GROUP_FAIRNESS: (
            tuple(
                employee
                for employee in data.source.employees
                if employee.employment_type is EmploymentType.PART_TIME
            ),
            (FairnessMetric.TOTAL_SHIFTS,),
        ),
        OptimizationStage.COMMON_GROUP_FAIRNESS: (
            tuple(data.source.employees),
            (
                FairnessMetric.MORNING_SHIFTS,
                FairnessMetric.AFTERNOON_SHIFTS,
                FairnessMetric.EVENING_SHIFTS,
                FairnessMetric.SUNDAY_SHIFTS,
                FairnessMetric.HOLIDAY_SHIFTS,
            ),
        ),
    }
    fairness_gaps: dict[
        OptimizationStage, Mapping[tuple[str, FairnessMetric], int]
    ] = {}
    for stage, (employees, stage_metrics) in stage_members_and_metrics.items():
        groups: dict[str, list[str]] = defaultdict(list)
        for employee in employees:
            groups[employee.fairness_group].append(employee.employee_id)
        stage_gaps: dict[tuple[str, FairnessMetric], int] = {}
        for group, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            for metric in stage_metrics:
                stage_gaps[(group, metric)] = _gap(
                    [metric_value(employee_id, metric) for employee_id in members]
                )
        fairness_gaps[stage] = MappingProxyType(stage_gaps)

    target_deviation = sum(
        abs(
            employee_metrics[employee.employee_id].total_shifts
            - employee.target_shifts
        )
        for employee in data.source.employees
        if employee.target_shifts is not None
    )
    part_time_usage = sum(
        employee_metrics[employee.employee_id].total_shifts
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    objective_values = {
        OptimizationStage.FULL_TIME_TARGET_DEVIATION: target_deviation,
        OptimizationStage.PART_TIME_USAGE: part_time_usage,
        OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES: sum(
            values.consecutive_double_days
            for employee_id, values in employee_metrics.items()
            if data.employees[employee_id].employment_type
            is EmploymentType.FULL_TIME
        ),
        OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS: sum(
            values.single_shift_days
            for employee_id, values in employee_metrics.items()
            if data.employees[employee_id].employment_type
            is EmploymentType.FULL_TIME
        ),
        OptimizationStage.FULL_TIME_SECONDARY_PATTERNS: sum(
            (
                values.morning_evening_days
                if data.employees[employee_id].full_time_class
                is FullTimeClass.A
                else values.triple_days
            )
            for employee_id, values in employee_metrics.items()
            if data.employees[employee_id].employment_type
            is EmploymentType.FULL_TIME
        ),
        **{
            stage: sum(stage_gaps.values())
            for stage, stage_gaps in fairness_gaps.items()
        },
    }
    canonical_coverage = {
        key: coverage[key] for key in data.demands
    }
    return RecomputedScheduleMetrics(
        coverage=MappingProxyType(canonical_coverage),
        person_period_counts=MappingProxyType(dict(person_period_counts)),
        daily_patterns=MappingProxyType(daily_patterns),
        employee_metrics=MappingProxyType(employee_metrics),
        fairness_gaps=MappingProxyType(fairness_gaps),
        objective_values=MappingProxyType(objective_values),
        total_assignments=len(assignments),
    )
