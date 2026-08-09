"""Media-independent formal schedule output models and finalization pipeline."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from .class_preferences import (
    CLASS_PREFERENCES,
    PreferenceDirection,
    PreferenceRank,
)
from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period, Weekday
from .feasibility import Assignment, FeasibilityStatus
from .models import NormalizedScheduleInput
from .optimization import (
    ClassPatternLockResult,
    FairnessMetric,
    LexicographicResult,
    OptimizationStage,
    OptimizationStageResult,
    OptimizationStageStatus,
    PreferenceBenchmarkResult,
)
from .result_metrics import EmployeeResultMetrics, RecomputedScheduleMetrics
from .ratio_fairness import (
    BASIS_POINTS_SCALE,
    ratio_basis_points,
)
from .result_validation import (
    FORMAL_OBJECTIVE_STAGES,
    ValidationReport,
    validate_schedule_result,
)


class ScheduleCellKind(StrEnum):
    ASSIGNED = "ASSIGNED"
    ZERO_DEMAND = "ZERO_DEMAND"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class RatioValue:
    numerator: int
    denominator: int
    basis_points: int | None
    value: float | None

    @classmethod
    def of(cls, numerator: int, denominator: int) -> "RatioValue":
        basis_points = ratio_basis_points(numerator, denominator)
        return cls(
            numerator=numerator,
            denominator=denominator,
            basis_points=basis_points,
            value=(
                None
                if basis_points is None
                else basis_points / BASIS_POINTS_SCALE
            ),
        )

    @property
    def display(self) -> str:
        return "N/A" if self.value is None else f"{self.value:.2%}"


@dataclass(frozen=True, slots=True)
class ScheduleCell:
    kind: ScheduleCellKind
    employee_id: str | None = None
    name: str | None = None

    @property
    def display(self) -> str:
        if self.kind is ScheduleCellKind.CLOSED:
            return "休診"
        if self.kind is ScheduleCellKind.ZERO_DEMAND:
            return "—"
        return self.name or ""


@dataclass(frozen=True, slots=True)
class MonthlyScheduleRow:
    period: Period
    role: str
    position: int
    label: str
    cells: tuple[ScheduleCell, ...]


@dataclass(frozen=True, slots=True)
class MonthlyScheduleTable:
    dates: tuple[date, ...]
    weekdays: tuple[Weekday, ...]
    rows: tuple[MonthlyScheduleRow, ...]

    def display_matrix(self) -> tuple[tuple[str, ...], ...]:
        """Return a simple table representation suitable for tests or adapters."""

        date_row = ("日期", *(day.isoformat() for day in self.dates))
        weekday_row = ("星期", *(weekday.value for weekday in self.weekdays))
        body = tuple(
            (row.label, *(cell.display for cell in row.cells)) for row in self.rows
        )
        return (date_row, weekday_row, *body)


@dataclass(frozen=True, slots=True)
class IndividualStatistics:
    employee_id: str
    name: str
    employment_type: EmploymentType
    full_time_class: FullTimeClass | None
    fairness_group: str
    shift_mode: str
    total_shifts: int
    role_counts: Mapping[str, int]
    period_counts: Mapping[str, int]
    attendance_days: int
    single_shift_days: int
    consecutive_double_days: int
    morning_afternoon_days: int
    afternoon_evening_days: int
    morning_evening_days: int
    triple_days: int
    sunday_shifts: int
    holiday_shifts: int
    leave_periods: int
    available_periods: int
    ratios: Mapping[str, RatioValue]


@dataclass(frozen=True, slots=True)
class FairnessGroupStatistics:
    fairness_group: str
    employment_type: EmploymentType
    full_time_class: FullTimeClass | None
    employee_ids: tuple[str, ...]
    metric_values: Mapping[str, Mapping[str, int]]
    gaps: Mapping[str, int]
    ratio_basis_points: Mapping[str, Mapping[str, int | None]]
    ratio_gaps_basis_points: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class CategoryStatistics:
    category: str
    employee_ids: tuple[str, ...]
    total_shifts: int
    consecutive_double_days: int
    single_shift_days: int
    morning_evening_days: int
    triple_days: int


@dataclass(frozen=True, slots=True)
class ClassPreferenceStatistics:
    full_time_class: FullTimeClass
    rank: PreferenceRank
    metric: str
    direction: PreferenceDirection
    employee_ids: tuple[str, ...]
    actual_value: int
    locked_actual_value: int | None
    ideal_value: int
    regret_days: int
    opportunity_days: int
    regret_basis_points: int | None


@dataclass(frozen=True, slots=True)
class OverallStatistics:
    total_demand: int
    total_assignments: int
    unfilled_shifts: int
    full_time_shifts: int
    a_shifts: int
    b_shifts: int
    part_time_shifts: int
    role_counts: Mapping[str, int]
    period_counts: Mapping[str, int]
    objective_vector: Mapping[str, int]
    implemented_objective_prefix_optimal: bool


@dataclass(frozen=True, slots=True)
class ExecutionTiming:
    """Wall-clock time for one complete scheduling pipeline before file export."""

    input_loading_seconds: float
    validation_normalization_seconds: float
    precheck_seconds: float
    optimization_seconds: float
    result_validation_and_build_seconds: float
    scheduling_pipeline_seconds: float


@dataclass(frozen=True, slots=True)
class FormalScheduleOutput:
    status: FeasibilityStatus
    assignments: tuple[Assignment, ...]
    validation_report: ValidationReport | None
    monthly_schedule: MonthlyScheduleTable | None
    individual_statistics: tuple[IndividualStatistics, ...]
    category_statistics: tuple[CategoryStatistics, ...]
    class_preference_statistics: tuple[ClassPreferenceStatistics, ...]
    fairness_group_statistics: tuple[FairnessGroupStatistics, ...]
    overall_statistics: OverallStatistics | None
    optimization_stages: tuple[OptimizationStageResult, ...]
    preference_benchmarks: tuple[PreferenceBenchmarkResult, ...]
    class_pattern_locks: tuple[ClassPatternLockResult, ...]
    execution_timing: ExecutionTiming | None = None

    @property
    def has_formal_schedule(self) -> bool:
        return self.monthly_schedule is not None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


def _build_monthly_table(
    data: NormalizedScheduleInput,
    assignments: tuple[Assignment, ...],
) -> MonthlyScheduleTable:
    by_slot: dict[tuple[date, Period, str], list[Assignment]] = defaultdict(list)
    for assignment in assignments:
        by_slot[(assignment.date, assignment.period, assignment.role)].append(
            assignment
        )
    for values in by_slot.values():
        values.sort(key=lambda item: item.employee_id)

    names = {employee.employee_id: employee.name for employee in data.source.employees}
    rows: list[MonthlyScheduleRow] = []
    for period in PERIODS_V1:
        for role in data.source.roles:
            maximum = max(
                (data.demands.get((day, period, role), 0) for day in data.open_dates),
                default=0,
            )
            row_count = max(1, maximum)
            for position in range(1, row_count + 1):
                role_label = role if row_count == 1 else f"{role} {position}"
                label = f"{period.value} / {role_label}"
                cells: list[ScheduleCell] = []
                for day in data.dates:
                    if day in data.closed_dates:
                        cells.append(ScheduleCell(ScheduleCellKind.CLOSED))
                        continue
                    demand = data.demands[(day, period, role)]
                    if demand == 0 or position > demand:
                        cells.append(ScheduleCell(ScheduleCellKind.ZERO_DEMAND))
                        continue
                    selected = by_slot[(day, period, role)][position - 1]
                    cells.append(
                        ScheduleCell(
                            ScheduleCellKind.ASSIGNED,
                            employee_id=selected.employee_id,
                            name=names[selected.employee_id],
                        )
                    )
                rows.append(
                    MonthlyScheduleRow(
                        period=period,
                        role=role,
                        position=position,
                        label=label,
                        cells=tuple(cells),
                    )
                )
    return MonthlyScheduleTable(
        dates=data.dates,
        weekdays=tuple(tuple(Weekday)[day.weekday()] for day in data.dates),
        rows=tuple(rows),
    )


def _available_period_count(data: NormalizedScheduleInput, employee_id: str) -> int:
    return len(
        {
            (day, period)
            for person, day, period, _role in data.allowed_assignments
            if person == employee_id
        }
    )


def _leave_period_count(data: NormalizedScheduleInput, employee_id: str) -> int:
    return sum(
        3 if item.all_day else 1
        for item in data.source.leave_requests
        if item.employee_id == employee_id
    )


def _ratios(
    values: EmployeeResultMetrics,
    available_periods: int,
    employment_type: EmploymentType,
) -> Mapping[str, RatioValue]:
    ratios = {
        "single_shift_days": RatioValue.of(
            values.single_shift_days, values.attendance_days
        ),
        "consecutive_double_days": RatioValue.of(
            values.consecutive_double_days, values.attendance_days
        ),
        "morning_evening_days": RatioValue.of(
            values.morning_evening_days, values.attendance_days
        ),
        "triple_days": RatioValue.of(
            values.triple_days, values.attendance_days
        ),
        "morning_shifts": RatioValue.of(
            values.period_counts[Period.MORNING], values.total_shifts
        ),
        "afternoon_shifts": RatioValue.of(
            values.period_counts[Period.AFTERNOON], values.total_shifts
        ),
        "evening_shifts": RatioValue.of(
            values.period_counts[Period.EVENING], values.total_shifts
        ),
        "sunday_shifts": RatioValue.of(
            values.sunday_shifts, values.total_shifts
        ),
        "holiday_shifts": RatioValue.of(
            values.holiday_shifts, values.total_shifts
        ),
    }
    if employment_type is EmploymentType.PART_TIME:
        ratios["part_time_usage"] = RatioValue.of(
            values.total_shifts, available_periods
        )
    return MappingProxyType(ratios)


def _build_individual_statistics(
    data: NormalizedScheduleInput,
    metrics: RecomputedScheduleMetrics,
) -> tuple[IndividualStatistics, ...]:
    result: list[IndividualStatistics] = []
    for employee in data.source.employees:
        values = metrics.employee_metrics[employee.employee_id]
        available_periods = _available_period_count(data, employee.employee_id)
        result.append(
            IndividualStatistics(
                employee_id=employee.employee_id,
                name=employee.name,
                employment_type=employee.employment_type,
                full_time_class=employee.full_time_class,
                fairness_group=employee.fairness_group,
                shift_mode=employee.shift_mode.value,
                total_shifts=values.total_shifts,
                role_counts=MappingProxyType(dict(values.role_counts)),
                period_counts=MappingProxyType(
                    {period.value: values.period_counts[period] for period in PERIODS_V1}
                ),
                attendance_days=values.attendance_days,
                single_shift_days=values.single_shift_days,
                consecutive_double_days=values.consecutive_double_days,
                morning_afternoon_days=values.morning_afternoon_days,
                afternoon_evening_days=values.afternoon_evening_days,
                morning_evening_days=values.morning_evening_days,
                triple_days=values.triple_days,
                sunday_shifts=values.sunday_shifts,
                holiday_shifts=values.holiday_shifts,
                leave_periods=_leave_period_count(data, employee.employee_id),
                available_periods=available_periods,
                ratios=_ratios(
                    values, available_periods, employee.employment_type
                ),
            )
        )
    return tuple(result)


def _metric_value(values: EmployeeResultMetrics, metric: FairnessMetric) -> int:
    return {
        FairnessMetric.ATTENDANCE_DAYS: values.attendance_days,
        FairnessMetric.CONSECUTIVE_DOUBLES: values.consecutive_double_days,
        FairnessMetric.SINGLE_SHIFT_DAYS: values.single_shift_days,
        FairnessMetric.MORNING_EVENING_DAYS: values.morning_evening_days,
        FairnessMetric.TRIPLE_DAYS: values.triple_days,
        FairnessMetric.TOTAL_SHIFTS: values.total_shifts,
        FairnessMetric.MORNING_SHIFTS: values.period_counts[Period.MORNING],
        FairnessMetric.AFTERNOON_SHIFTS: values.period_counts[Period.AFTERNOON],
        FairnessMetric.EVENING_SHIFTS: values.period_counts[Period.EVENING],
        FairnessMetric.SUNDAY_SHIFTS: values.sunday_shifts,
        FairnessMetric.HOLIDAY_SHIFTS: values.holiday_shifts,
    }[metric]


def _group_metrics(employee) -> tuple[FairnessMetric, ...]:
    common = (
        FairnessMetric.MORNING_SHIFTS,
        FairnessMetric.AFTERNOON_SHIFTS,
        FairnessMetric.EVENING_SHIFTS,
        FairnessMetric.SUNDAY_SHIFTS,
        FairnessMetric.HOLIDAY_SHIFTS,
    )
    if employee.employment_type is EmploymentType.PART_TIME:
        return (FairnessMetric.TOTAL_SHIFTS, *common)
    if employee.full_time_class is FullTimeClass.A:
        return (
            FairnessMetric.CONSECUTIVE_DOUBLES,
            FairnessMetric.SINGLE_SHIFT_DAYS,
            FairnessMetric.MORNING_EVENING_DAYS,
            *common,
        )
    return (
        FairnessMetric.CONSECUTIVE_DOUBLES,
        FairnessMetric.SINGLE_SHIFT_DAYS,
        FairnessMetric.TRIPLE_DAYS,
        *common,
    )


def _build_group_statistics(
    data: NormalizedScheduleInput,
    metrics: RecomputedScheduleMetrics,
) -> tuple[FairnessGroupStatistics, ...]:
    groups: dict[str, list] = defaultdict(list)
    for employee in data.source.employees:
        groups[employee.fairness_group].append(employee)
    result: list[FairnessGroupStatistics] = []
    for group, employees in sorted(groups.items()):
        employee_ids = tuple(sorted(item.employee_id for item in employees))
        group_metrics = _group_metrics(employees[0])
        metric_values = {
            metric.value: MappingProxyType(
                {
                    employee_id: _metric_value(
                        metrics.employee_metrics[employee_id], metric
                    )
                    for employee_id in employee_ids
                }
            )
            for metric in group_metrics
        }
        gaps = {
            metric: max(values.values()) - min(values.values())
            for metric, values in metric_values.items()
        }
        ratio_values: dict[str, Mapping[str, int | None]] = {}
        ratio_gaps: dict[str, int] = {}
        if employees[0].employment_type is EmploymentType.FULL_TIME:
            pattern_metrics = (
                (
                    FairnessMetric.CONSECUTIVE_DOUBLES,
                    FairnessMetric.SINGLE_SHIFT_DAYS,
                    FairnessMetric.MORNING_EVENING_DAYS,
                )
                if employees[0].full_time_class is FullTimeClass.A
                else (
                    FairnessMetric.CONSECUTIVE_DOUBLES,
                    FairnessMetric.SINGLE_SHIFT_DAYS,
                    FairnessMetric.TRIPLE_DAYS,
                )
            )
            for metric in pattern_metrics:
                values = MappingProxyType(
                    {
                        employee_id: metrics.pattern_ratio_basis_points[
                            (employee_id, metric)
                        ]
                        for employee_id in employee_ids
                    }
                )
                ratio_values[metric.value] = values
                defined = [value for value in values.values() if value is not None]
                ratio_gaps[metric.value] = (
                    max(defined) - min(defined) if len(defined) >= 2 else 0
                )
        result.append(
            FairnessGroupStatistics(
                fairness_group=group,
                employment_type=employees[0].employment_type,
                full_time_class=employees[0].full_time_class,
                employee_ids=employee_ids,
                metric_values=MappingProxyType(metric_values),
                gaps=MappingProxyType(gaps),
                ratio_basis_points=MappingProxyType(ratio_values),
                ratio_gaps_basis_points=MappingProxyType(ratio_gaps),
            )
        )
    return tuple(result)


def _build_category_statistics(
    data: NormalizedScheduleInput,
    metrics: RecomputedScheduleMetrics,
) -> tuple[CategoryStatistics, ...]:
    categories = {
        "A": tuple(
            item.employee_id
            for item in data.source.employees
            if item.full_time_class is FullTimeClass.A
        ),
        "B": tuple(
            item.employee_id
            for item in data.source.employees
            if item.full_time_class is FullTimeClass.B
        ),
        "PART_TIME": tuple(
            item.employee_id
            for item in data.source.employees
            if item.employment_type is EmploymentType.PART_TIME
        ),
    }
    return tuple(
        CategoryStatistics(
            category=category,
            employee_ids=employee_ids,
            total_shifts=sum(
                metrics.employee_metrics[item].total_shifts for item in employee_ids
            ),
            consecutive_double_days=sum(
                metrics.employee_metrics[item].consecutive_double_days
                for item in employee_ids
            ),
            single_shift_days=sum(
                metrics.employee_metrics[item].single_shift_days
                for item in employee_ids
            ),
            morning_evening_days=sum(
                metrics.employee_metrics[item].morning_evening_days
                for item in employee_ids
            ),
            triple_days=sum(
                metrics.employee_metrics[item].triple_days for item in employee_ids
            ),
        )
        for category, employee_ids in categories.items()
    )


def _build_class_preference_statistics(
    data: NormalizedScheduleInput,
    metrics: RecomputedScheduleMetrics,
) -> tuple[ClassPreferenceStatistics, ...]:
    result: list[ClassPreferenceStatistics] = []
    for definition in CLASS_PREFERENCES:
        key = (definition.full_time_class, definition.rank)
        result.append(
            ClassPreferenceStatistics(
                full_time_class=definition.full_time_class,
                rank=definition.rank,
                metric=definition.metric.value,
                direction=definition.direction,
                employee_ids=tuple(
                    sorted(
                        employee.employee_id
                        for employee in data.source.employees
                        if employee.full_time_class is definition.full_time_class
                    )
                ),
                actual_value=metrics.class_preference_actual_values[key],
                locked_actual_value=(
                    metrics.class_preference_locked_actual_values[key]
                ),
                ideal_value=metrics.class_preference_ideal_values[key],
                regret_days=metrics.class_preference_regret_days[key],
                opportunity_days=(
                    metrics.class_preference_opportunity_days[
                        definition.full_time_class
                    ]
                ),
                regret_basis_points=(
                    metrics.class_preference_regret_basis_points[key]
                ),
            )
        )
    return tuple(result)


def _build_overall_statistics(
    data: NormalizedScheduleInput,
    result: LexicographicResult,
    metrics: RecomputedScheduleMetrics,
) -> OverallStatistics:
    assignment_roles = Counter(item.role for item in result.assignments)
    assignment_periods = Counter(item.period for item in result.assignments)
    full_time_ids = {
        item.employee_id
        for item in data.source.employees
        if item.employment_type is EmploymentType.FULL_TIME
    }
    a_ids = {
        item.employee_id
        for item in data.source.employees
        if item.full_time_class is FullTimeClass.A
    }
    b_ids = {
        item.employee_id
        for item in data.source.employees
        if item.full_time_class is FullTimeClass.B
    }
    pt_ids = set(data.employees) - full_time_ids
    total_demand = sum(data.demands.values())
    return OverallStatistics(
        total_demand=total_demand,
        total_assignments=metrics.total_assignments,
        unfilled_shifts=max(0, total_demand - metrics.total_assignments),
        full_time_shifts=sum(
            metrics.employee_metrics[item].total_shifts for item in full_time_ids
        ),
        a_shifts=sum(metrics.employee_metrics[item].total_shifts for item in a_ids),
        b_shifts=sum(metrics.employee_metrics[item].total_shifts for item in b_ids),
        part_time_shifts=sum(
            metrics.employee_metrics[item].total_shifts for item in pt_ids
        ),
        role_counts=MappingProxyType(
            {role: assignment_roles[role] for role in data.source.roles}
        ),
        period_counts=MappingProxyType(
            {period.value: assignment_periods[period] for period in PERIODS_V1}
        ),
        objective_vector=MappingProxyType(
            {
                stage.value: metrics.objective_values[stage]
                for stage in FORMAL_OBJECTIVE_STAGES
            }
        ),
        implemented_objective_prefix_optimal=(
            result.implemented_objective_prefix_optimal
        ),
    )


def finalize_schedule_output(
    data: NormalizedScheduleInput,
    result: LexicographicResult,
) -> FormalScheduleOutput:
    """Validate a solver result, promote status, and build formal output models."""

    if not result.is_feasible:
        return FormalScheduleOutput(
            status=result.status,
            assignments=result.assignments,
            validation_report=None,
            monthly_schedule=None,
            individual_statistics=(),
            category_statistics=(),
            class_preference_statistics=(),
            fairness_group_statistics=(),
            overall_statistics=None,
            optimization_stages=result.stages,
            preference_benchmarks=result.preference_benchmarks,
            class_pattern_locks=result.class_pattern_locks,
        )

    report = validate_schedule_result(
        data,
        result.assignments,
        result.stages,
        result.preference_benchmarks,
        result.class_pattern_locks,
    )
    if not report.is_valid:
        return FormalScheduleOutput(
            status=FeasibilityStatus.VALIDATION_FAILED,
            assignments=result.assignments,
            validation_report=report,
            monthly_schedule=None,
            individual_statistics=(),
            category_statistics=(),
            class_preference_statistics=(),
            fairness_group_statistics=(),
            overall_statistics=None,
            optimization_stages=result.stages,
            preference_benchmarks=result.preference_benchmarks,
            class_pattern_locks=result.class_pattern_locks,
        )

    stage_by_name = {item.stage: item for item in result.stages}
    all_objectives_complete = all(
        stage_by_name.get(stage) is not None
        and stage_by_name[stage].status
        in (
            OptimizationStageStatus.OPTIMAL,
            OptimizationStageStatus.SKIPPED_CONSTANT,
        )
        for stage in FORMAL_OBJECTIVE_STAGES
    )
    formal_status = (
        FeasibilityStatus.OPTIMAL
        if result.implemented_objective_prefix_optimal and all_objectives_complete
        else FeasibilityStatus.FEASIBLE
    )
    metrics = report.recomputed
    return FormalScheduleOutput(
        status=formal_status,
        assignments=result.assignments,
        validation_report=report,
        monthly_schedule=_build_monthly_table(data, result.assignments),
        individual_statistics=_build_individual_statistics(data, metrics),
        category_statistics=_build_category_statistics(data, metrics),
        class_preference_statistics=(
            _build_class_preference_statistics(data, metrics)
        ),
        fairness_group_statistics=_build_group_statistics(data, metrics),
        overall_statistics=_build_overall_statistics(data, result, metrics),
        optimization_stages=result.stages,
        preference_benchmarks=result.preference_benchmarks,
        class_pattern_locks=result.class_pattern_locks,
    )


def to_primitive(value: Any) -> Any:
    """Convert output dataclasses into JSON-compatible Python primitives."""

    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            (key.value if isinstance(key, Enum) else str(key)): to_primitive(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [to_primitive(item) for item in value]
    raise TypeError(f"cannot convert {type(value).__name__} to primitive output")
