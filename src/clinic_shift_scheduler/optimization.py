"""Phase-four strict lexicographic optimization controller.

The implemented objective prefix is full-time TARGET deviation followed by
part-time usage. Later v1 objectives are intentionally outside this module's
current scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from ortools.sat.python import cp_model

from .daily_patterns import DailyPattern
from .enums import EmploymentType, ShiftMode
from .feasibility import (
    Assignment,
    FeasibilityModel,
    FeasibilityStatus,
    PersonDayKey,
    build_feasibility_model,
    extract_model_solution,
)
from .models import Employee, NormalizedScheduleInput
from .precheck import PrecheckResult, PrecheckStatus, run_prechecks


class OptimizationStage(StrEnum):
    HARD_FEASIBILITY = "hard_feasibility"
    FULL_TIME_TARGET_DEVIATION = "full_time_target_deviation"
    PART_TIME_USAGE = "part_time_usage"


class ObjectiveDirection(StrEnum):
    NONE = "NONE"
    MINIMIZE = "MINIMIZE"


class OptimizationStageStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    OPTIMAL = "OPTIMAL"
    SKIPPED_CONSTANT = "SKIPPED_CONSTANT"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class ConstantProof(StrEnum):
    NO_TARGET_EMPLOYEES = "NO_TARGET_EMPLOYEES"
    ALL_TARGET_COUNTS_HARD_FIXED = "ALL_TARGET_COUNTS_HARD_FIXED"
    NO_PART_TIME_EMPLOYEES = "NO_PART_TIME_EMPLOYEES"
    ALL_PART_TIME_COUNTS_HARD_FIXED = "ALL_PART_TIME_COUNTS_HARD_FIXED"
    ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE = (
        "ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE"
    )


@dataclass(frozen=True, slots=True)
class LexicographicSolverConfig:
    max_time_seconds_per_stage: float | None = None
    num_search_workers: int = 1
    random_seed: int = 0

    def __post_init__(self) -> None:
        if (
            self.max_time_seconds_per_stage is not None
            and self.max_time_seconds_per_stage <= 0
        ):
            raise ValueError("max_time_seconds_per_stage must be greater than 0")
        if self.num_search_workers <= 0:
            raise ValueError("num_search_workers must be greater than 0")


@dataclass(frozen=True, slots=True)
class OptimizationStageResult:
    stage: OptimizationStage
    direction: ObjectiveDirection
    status: OptimizationStageStatus
    objective_value: int | None
    raw_solver_status: str
    wall_time_seconds: float
    locked: bool
    constant_proof: ConstantProof | None = None


@dataclass(frozen=True, slots=True)
class PhaseFourModel:
    feasibility: FeasibilityModel
    target_differences: Mapping[str, cp_model.IntVar]
    target_deviations: Mapping[str, cp_model.IntVar]
    target_objective: cp_model.LinearExpr | int
    part_time_objective: cp_model.LinearExpr | int


@dataclass(frozen=True, slots=True)
class LexicographicResult:
    status: FeasibilityStatus
    assignments: tuple[Assignment, ...]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    employee_shift_counts: Mapping[str, int]
    target_deviations: Mapping[str, int]
    part_time_total: int | None
    stages: tuple[OptimizationStageResult, ...]
    precheck: PrecheckResult

    @property
    def is_feasible(self) -> bool:
        return self.status in (
            FeasibilityStatus.FEASIBLE,
            FeasibilityStatus.OPTIMAL,
        )


@dataclass(frozen=True, slots=True)
class _ObjectiveSpec:
    stage: OptimizationStage
    variables: tuple[cp_model.IntVar, ...]
    expression: cp_model.LinearExpr | int
    constant_value: int | None
    constant_proof: ConstantProof | None


@dataclass(frozen=True, slots=True)
class _SolverRun:
    solver: cp_model.CpSolver
    raw_status: int
    raw_status_name: str
    wall_time_seconds: float


@dataclass(frozen=True, slots=True)
class _SolutionSnapshot:
    assignments: tuple[Assignment, ...]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    employee_shift_counts: Mapping[str, int]
    target_deviations: Mapping[str, int]
    part_time_total: int


def _var_name(prefix: str, employee_id: str) -> str:
    return f"{prefix}[{employee_id}]"


def build_phase_four_model(data: NormalizedScheduleInput) -> PhaseFourModel:
    """Add phase-four derived variables to the shared hard-feasibility model."""

    feasibility = build_feasibility_model(data)
    model = feasibility.model
    target_differences: dict[str, cp_model.IntVar] = {}
    target_deviations: dict[str, cp_model.IntVar] = {}
    for employee in data.source.employees:
        if employee.shift_mode is not ShiftMode.TARGET:
            continue
        assert employee.target_shifts is not None
        count_variable = feasibility.employee_shift_counts[employee.employee_id]
        candidate_count = sum(
            key[0] == employee.employee_id for key in feasibility.x
        )
        deviation_upper_bound = max(
            employee.target_shifts,
            abs(candidate_count - employee.target_shifts),
        )
        difference = model.new_int_var(
            -employee.target_shifts,
            candidate_count - employee.target_shifts,
            _var_name("target_difference", employee.employee_id),
        )
        model.add(
            difference == count_variable - employee.target_shifts
        )
        deviation = model.new_int_var(
            0,
            deviation_upper_bound,
            _var_name("target_deviation", employee.employee_id),
        )
        # OR-Tools 9.12 mis-encodes the negated offset when AddAbsEquality
        # receives a shifted expression directly, so take abs of a linked var.
        model.add_abs_equality(deviation, difference)
        target_differences[employee.employee_id] = difference
        target_deviations[employee.employee_id] = deviation

    part_time_counts = tuple(
        feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    return PhaseFourModel(
        feasibility=feasibility,
        target_differences=MappingProxyType(target_differences),
        target_deviations=MappingProxyType(target_deviations),
        target_objective=sum(target_deviations.values()),
        part_time_objective=sum(part_time_counts),
    )


def _hard_minimum(employee: Employee) -> int:
    if employee.shift_mode is ShiftMode.EXACT:
        assert employee.required_shifts is not None
        return employee.required_shifts
    return employee.min_shifts or 0


def _hard_fixed_count(
    employee: Employee,
    precheck: PrecheckResult,
) -> int | None:
    minimum = _hard_minimum(employee)
    maximum = precheck.employee_capacities[employee.employee_id]
    return minimum if minimum == maximum else None


def _target_constant(
    data: NormalizedScheduleInput,
    precheck: PrecheckResult,
) -> tuple[int | None, ConstantProof | None]:
    target_employees = tuple(
        employee
        for employee in data.source.employees
        if employee.shift_mode is ShiftMode.TARGET
    )
    if not target_employees:
        return 0, ConstantProof.NO_TARGET_EMPLOYEES

    fixed_counts = {
        employee.employee_id: _hard_fixed_count(employee, precheck)
        for employee in target_employees
    }
    if all(value is not None for value in fixed_counts.values()):
        return (
            sum(
                abs(fixed_counts[employee.employee_id] - employee.target_shifts)
                for employee in target_employees
            ),
            ConstantProof.ALL_TARGET_COUNTS_HARD_FIXED,
        )
    return None, None


def _part_time_constant(
    data: NormalizedScheduleInput,
    precheck: PrecheckResult,
) -> tuple[int | None, ConstantProof | None]:
    part_time = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    if not part_time:
        return 0, ConstantProof.NO_PART_TIME_EMPLOYEES

    fixed_part_time = tuple(
        _hard_fixed_count(employee, precheck) for employee in part_time
    )
    if all(value is not None for value in fixed_part_time):
        return (
            sum(value for value in fixed_part_time if value is not None),
            ConstantProof.ALL_PART_TIME_COUNTS_HARD_FIXED,
        )

    full_time = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.FULL_TIME
    )
    fixed_full_time = tuple(
        _hard_fixed_count(employee, precheck) for employee in full_time
    )
    if all(value is not None for value in fixed_full_time):
        fixed_full_time_total = sum(
            value for value in fixed_full_time if value is not None
        )
        return (
            precheck.total_demand - fixed_full_time_total,
            ConstantProof.ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE,
        )
    return None, None


def _objective_specs(
    data: NormalizedScheduleInput,
    built: PhaseFourModel,
    precheck: PrecheckResult,
) -> tuple[_ObjectiveSpec, ...]:
    target_constant, target_proof = _target_constant(data, precheck)
    part_time_constant, part_time_proof = _part_time_constant(data, precheck)
    part_time_variables = tuple(
        built.feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    return (
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_TARGET_DEVIATION,
            variables=tuple(built.target_deviations.values()),
            expression=built.target_objective,
            constant_value=target_constant,
            constant_proof=target_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.PART_TIME_USAGE,
            variables=part_time_variables,
            expression=built.part_time_objective,
            constant_value=part_time_constant,
            constant_proof=part_time_proof,
        ),
    )


def _solve_once(
    model: cp_model.CpModel,
    config: LexicographicSolverConfig,
) -> _SolverRun:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.num_search_workers
    solver.parameters.random_seed = config.random_seed
    if config.max_time_seconds_per_stage is not None:
        solver.parameters.max_time_in_seconds = config.max_time_seconds_per_stage
    raw_status = solver.solve(model)
    try:
        wall_time = solver.wall_time
    except RuntimeError:  # Supports deterministic mocked UNKNOWN tests.
        wall_time = 0.0
    return _SolverRun(
        solver=solver,
        raw_status=raw_status,
        raw_status_name=solver.status_name(raw_status),
        wall_time_seconds=wall_time,
    )


def _snapshot(
    data: NormalizedScheduleInput,
    built: PhaseFourModel,
    solver: cp_model.CpSolver,
) -> _SolutionSnapshot:
    assignments, daily_patterns = extract_model_solution(
        built.feasibility,
        solver,
    )
    shift_counts = {
        employee_id: solver.value(variable)
        for employee_id, variable in built.feasibility.employee_shift_counts.items()
    }
    deviations = {
        employee_id: solver.value(variable)
        for employee_id, variable in built.target_deviations.items()
    }
    part_time_total = sum(
        shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    return _SolutionSnapshot(
        assignments=assignments,
        daily_patterns=daily_patterns,
        employee_shift_counts=MappingProxyType(shift_counts),
        target_deviations=MappingProxyType(deviations),
        part_time_total=part_time_total,
    )


def _empty_result(
    status: FeasibilityStatus,
    precheck: PrecheckResult,
    stages: tuple[OptimizationStageResult, ...] = (),
) -> LexicographicResult:
    return LexicographicResult(
        status=status,
        assignments=(),
        daily_patterns=MappingProxyType({}),
        employee_shift_counts=MappingProxyType({}),
        target_deviations=MappingProxyType({}),
        part_time_total=None,
        stages=stages,
        precheck=precheck,
    )


def _result_from_snapshot(
    status: FeasibilityStatus,
    snapshot: _SolutionSnapshot,
    stages: list[OptimizationStageResult],
    precheck: PrecheckResult,
) -> LexicographicResult:
    return LexicographicResult(
        status=status,
        assignments=snapshot.assignments,
        daily_patterns=snapshot.daily_patterns,
        employee_shift_counts=snapshot.employee_shift_counts,
        target_deviations=snapshot.target_deviations,
        part_time_total=snapshot.part_time_total,
        stages=tuple(stages),
        precheck=precheck,
    )


def solve_lexicographic(
    data: NormalizedScheduleInput,
    config: LexicographicSolverConfig | None = None,
) -> LexicographicResult:
    """Optimize the implemented v1 objective prefix with exact value locks."""

    config = config or LexicographicSolverConfig()
    precheck = run_prechecks(data)
    if precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return _empty_result(FeasibilityStatus.PRECHECK_INFEASIBLE, precheck)

    built = build_phase_four_model(data)
    stages: list[OptimizationStageResult] = []
    hard_run = _solve_once(built.feasibility.model, config)
    if hard_run.raw_status == cp_model.INFEASIBLE:
        stages.append(
            OptimizationStageResult(
                stage=OptimizationStage.HARD_FEASIBILITY,
                direction=ObjectiveDirection.NONE,
                status=OptimizationStageStatus.INFEASIBLE,
                objective_value=None,
                raw_solver_status=hard_run.raw_status_name,
                wall_time_seconds=hard_run.wall_time_seconds,
                locked=False,
            )
        )
        return _empty_result(
            FeasibilityStatus.INFEASIBLE,
            precheck,
            tuple(stages),
        )
    if hard_run.raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        stages.append(
            OptimizationStageResult(
                stage=OptimizationStage.HARD_FEASIBILITY,
                direction=ObjectiveDirection.NONE,
                status=OptimizationStageStatus.UNKNOWN,
                objective_value=None,
                raw_solver_status=hard_run.raw_status_name,
                wall_time_seconds=hard_run.wall_time_seconds,
                locked=False,
            )
        )
        return _empty_result(
            FeasibilityStatus.UNKNOWN,
            precheck,
            tuple(stages),
        )

    stages.append(
        OptimizationStageResult(
            stage=OptimizationStage.HARD_FEASIBILITY,
            direction=ObjectiveDirection.NONE,
            status=OptimizationStageStatus.FEASIBLE,
            objective_value=None,
            raw_solver_status=hard_run.raw_status_name,
            wall_time_seconds=hard_run.wall_time_seconds,
            locked=False,
        )
    )
    snapshot = _snapshot(data, built, hard_run.solver)

    for objective in _objective_specs(data, built, precheck):
        if objective.constant_value is not None:
            stages.append(
                OptimizationStageResult(
                    stage=objective.stage,
                    direction=ObjectiveDirection.MINIMIZE,
                    status=OptimizationStageStatus.SKIPPED_CONSTANT,
                    objective_value=objective.constant_value,
                    raw_solver_status="NOT_RUN",
                    wall_time_seconds=0.0,
                    locked=False,
                    constant_proof=objective.constant_proof,
                )
            )
            continue

        built.feasibility.model.minimize(objective.expression)
        run = _solve_once(built.feasibility.model, config)
        if run.raw_status == cp_model.OPTIMAL:
            objective_value = sum(
                run.solver.value(variable) for variable in objective.variables
            )
            built.feasibility.model.add(
                objective.expression == objective_value
            )
            stages.append(
                OptimizationStageResult(
                    stage=objective.stage,
                    direction=ObjectiveDirection.MINIMIZE,
                    status=OptimizationStageStatus.OPTIMAL,
                    objective_value=objective_value,
                    raw_solver_status=run.raw_status_name,
                    wall_time_seconds=run.wall_time_seconds,
                    locked=True,
                )
            )
            snapshot = _snapshot(data, built, run.solver)
            continue

        if run.raw_status == cp_model.FEASIBLE:
            objective_value = sum(
                run.solver.value(variable) for variable in objective.variables
            )
            stages.append(
                OptimizationStageResult(
                    stage=objective.stage,
                    direction=ObjectiveDirection.MINIMIZE,
                    status=OptimizationStageStatus.FEASIBLE,
                    objective_value=objective_value,
                    raw_solver_status=run.raw_status_name,
                    wall_time_seconds=run.wall_time_seconds,
                    locked=False,
                )
            )
            snapshot = _snapshot(data, built, run.solver)
            return _result_from_snapshot(
                FeasibilityStatus.FEASIBLE,
                snapshot,
                stages,
                precheck,
            )

        stage_status = (
            OptimizationStageStatus.INFEASIBLE
            if run.raw_status == cp_model.INFEASIBLE
            else OptimizationStageStatus.UNKNOWN
        )
        stages.append(
            OptimizationStageResult(
                stage=objective.stage,
                direction=ObjectiveDirection.MINIMIZE,
                status=stage_status,
                objective_value=None,
                raw_solver_status=run.raw_status_name,
                wall_time_seconds=run.wall_time_seconds,
                locked=False,
            )
        )
        return _result_from_snapshot(
            FeasibilityStatus.FEASIBLE,
            snapshot,
            stages,
            precheck,
        )

    return _result_from_snapshot(
        FeasibilityStatus.OPTIMAL,
        snapshot,
        stages,
        precheck,
    )
