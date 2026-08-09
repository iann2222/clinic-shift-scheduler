from __future__ import annotations

import unittest
from collections import Counter
from dataclasses import replace
from datetime import date
from unittest.mock import patch

from ortools.sat.python import cp_model

import clinic_shift_scheduler.optimization as optimization
from clinic_shift_scheduler import (
    ConstantProof,
    DailyPattern,
    FeasibilityStatus,
    ObjectiveDirection,
    OptimizationStage,
    OptimizationStageStatus,
    PatternQualityLevel,
    ResultValidationStatus,
    recompute_schedule_metrics,
    solve_lexicographic,
    validate_and_normalize,
    validate_schedule_result,
)

from tests.fixtures import synthetic_schedule_input
from clinic_shift_scheduler.ratio_fairness import ratio_basis_points


def available(day: str, *periods: str) -> list[dict]:
    return [
        {"date": day, "period": period, "roles": ["assistant"]}
        for period in periods
    ]


def available_for(day: str, role: str, *periods: str) -> list[dict]:
    return [
        {"date": day, "period": period, "roles": [role]}
        for period in periods
    ]


def full_time(
    employee_id: str,
    *,
    full_time_class: str = "B",
    shift_mode: str,
    required: int | None = None,
    target: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    available_slots: list[dict] | None = None,
    fairness_group: str | None = None,
    roles: list[str] | None = None,
) -> dict:
    employee = {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "full_time",
        "full_time_class": full_time_class,
        "roles": roles or ["assistant"],
        "fairness_group": fairness_group or f"{full_time_class}_{employee_id}",
        "shift_mode": shift_mode,
    }
    if shift_mode == "EXACT":
        employee["required_shifts"] = required
    elif shift_mode == "RANGE":
        employee["min_shifts"] = minimum
        employee["max_shifts"] = maximum
    else:
        employee["target_shifts"] = target
        if minimum is not None:
            employee["min_shifts"] = minimum
        if maximum is not None:
            employee["max_shifts"] = maximum
    if available_slots is not None:
        employee["available_slots"] = available_slots
    return employee


def part_time(
    employee_id: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    required: int | None = None,
    available_slots: list[dict],
    fairness_group: str | None = None,
    roles: list[str] | None = None,
) -> dict:
    employee = {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "part_time",
        "full_time_class": None,
        "roles": roles or ["assistant"],
        "fairness_group": fairness_group or f"PT_{employee_id}",
        "available_slots": available_slots,
    }
    if required is not None:
        employee["shift_mode"] = "EXACT"
        employee["required_shifts"] = required
    else:
        employee["shift_mode"] = "RANGE"
        employee["min_shifts"] = minimum
        employee["max_shifts"] = maximum
    return employee


def one_day_input(employees: list[dict], demand_periods: tuple[str, ...]) -> dict:
    return synthetic_schedule_input(
        start_date="2024-10-01",
        end_date="2024-10-01",
        roles=["assistant"],
        employees=employees,
        positive_demands={
            ("2024-10-01", period, "assistant"): 1
            for period in demand_periods
        },
    )


def stage(result, name: OptimizationStage):
    return next(item for item in result.stages if item.stage is name)


class LexicographicOptimizationTests(unittest.TestCase):
    def test_target_uses_symmetric_absolute_deviation(self) -> None:
        cases = (
            (3, ("morning",), 1, 2),
            (1, ("morning", "afternoon"), 2, 1),
        )
        for target, periods, expected_count, expected_deviation in cases:
            with self.subTest(target=target, periods=periods):
                payload = one_day_input(
                    [
                        full_time(
                            "TARGET",
                            shift_mode="TARGET",
                            target=target,
                        )
                    ],
                    periods,
                )

                result = solve_lexicographic(validate_and_normalize(payload))
                target_stage = stage(
                    result,
                    OptimizationStage.FULL_TIME_TARGET_DEVIATION,
                )

                self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
                self.assertTrue(result.implemented_objective_prefix_optimal)
                self.assertEqual(
                    result.employee_shift_counts["TARGET"], expected_count
                )
                self.assertEqual(
                    result.target_deviations["TARGET"], expected_deviation
                )
                self.assertEqual(
                    target_stage.status,
                    OptimizationStageStatus.OPTIMAL,
                )
                self.assertEqual(
                    target_stage.objective_value,
                    expected_deviation,
                )
                self.assertTrue(target_stage.locked)

    def test_part_time_usage_is_minimized_after_target_stage(self) -> None:
        periods = ("morning", "afternoon")
        payload = one_day_input(
            [
                full_time(
                    "FT",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=2,
                ),
                part_time(
                    "PT",
                    minimum=0,
                    maximum=2,
                    available_slots=available("2024-10-01", *periods),
                ),
            ],
            periods,
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        target_stage = stage(
            result,
            OptimizationStage.FULL_TIME_TARGET_DEVIATION,
        )
        part_time_stage = stage(result, OptimizationStage.PART_TIME_USAGE)

        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertTrue(result.implemented_objective_prefix_optimal)
        self.assertEqual(
            target_stage.status,
            OptimizationStageStatus.SKIPPED_CONSTANT,
        )
        self.assertEqual(result.part_time_total, 0)
        self.assertEqual(part_time_stage.objective_value, 0)
        self.assertEqual(part_time_stage.status, OptimizationStageStatus.OPTIMAL)
        self.assertTrue(part_time_stage.locked)

    def test_later_stage_cannot_worsen_locked_target_value(self) -> None:
        periods = ("morning", "afternoon", "evening")
        payload = one_day_input(
            [
                full_time(
                    "TARGET",
                    shift_mode="TARGET",
                    target=1,
                ),
                part_time(
                    "PT",
                    minimum=0,
                    maximum=1,
                    available_slots=available("2024-10-01", *periods),
                ),
            ],
            periods,
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        target_stage = stage(
            result,
            OptimizationStage.FULL_TIME_TARGET_DEVIATION,
        )
        part_time_stage = stage(result, OptimizationStage.PART_TIME_USAGE)

        self.assertEqual(target_stage.objective_value, 1)
        self.assertTrue(target_stage.locked)
        self.assertEqual(part_time_stage.objective_value, 1)
        self.assertTrue(part_time_stage.locked)
        self.assertEqual(result.employee_shift_counts["TARGET"], 2)
        self.assertEqual(result.target_deviations["TARGET"], 1)
        self.assertEqual(result.part_time_total, 1)
        self.assertEqual(
            tuple(item.stage for item in result.stages),
            (
                OptimizationStage.HARD_FEASIBILITY,
                OptimizationStage.FULL_TIME_TARGET_DEVIATION,
                OptimizationStage.PART_TIME_USAGE,
                OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES,
                OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS,
                OptimizationStage.FULL_TIME_SECONDARY_PATTERNS,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
                OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
                OptimizationStage.PART_TIME_GROUP_FAIRNESS,
                OptimizationStage.COMMON_GROUP_FAIRNESS,
            ),
        )

    def test_constant_part_time_total_is_skipped_with_proof(self) -> None:
        periods = ("morning", "afternoon")
        payload = one_day_input(
            [
                full_time("FT", shift_mode="EXACT", required=1),
                part_time(
                    "PT",
                    minimum=0,
                    maximum=2,
                    available_slots=available("2024-10-01", *periods),
                ),
            ],
            periods,
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        part_time_stage = stage(result, OptimizationStage.PART_TIME_USAGE)

        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertTrue(result.implemented_objective_prefix_optimal)
        self.assertEqual(result.part_time_total, 1)
        self.assertEqual(
            part_time_stage.status,
            OptimizationStageStatus.SKIPPED_CONSTANT,
        )
        self.assertEqual(part_time_stage.objective_value, 1)
        self.assertEqual(
            part_time_stage.constant_proof,
            ConstantProof.ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE,
        )
        self.assertFalse(part_time_stage.locked)
        self.assertEqual(part_time_stage.raw_solver_status, "NOT_RUN")

    def test_nonoptimal_objective_is_not_locked_or_followed_by_next_stage(self) -> None:
        payload = one_day_input(
            [full_time("TARGET", shift_mode="TARGET", target=1)],
            ("morning", "afternoon"),
        )
        normalized = validate_and_normalize(payload)
        original_solve_once = optimization._solve_once
        calls = 0

        def downgrade_target(model, config):
            nonlocal calls
            calls += 1
            run = original_solve_once(model, config)
            if calls == 2:
                return replace(
                    run,
                    raw_status=cp_model.FEASIBLE,
                    raw_status_name="FEASIBLE",
                )
            return run

        with patch.object(optimization, "_solve_once", side_effect=downgrade_target):
            result = solve_lexicographic(normalized)

        target_stage = stage(
            result,
            OptimizationStage.FULL_TIME_TARGET_DEVIATION,
        )
        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertFalse(result.implemented_objective_prefix_optimal)
        self.assertEqual(target_stage.status, OptimizationStageStatus.FEASIBLE)
        self.assertFalse(target_stage.locked)
        self.assertEqual(len(result.stages), 2)

    def test_unknown_before_any_solution_maps_to_unknown(self) -> None:
        payload = one_day_input(
            [full_time("TARGET", shift_mode="TARGET", target=1)],
            ("morning",),
        )
        unknown_run = optimization._SolverRun(
            solver=cp_model.CpSolver(),
            raw_status=cp_model.UNKNOWN,
            raw_status_name="UNKNOWN",
            wall_time_seconds=0.0,
        )

        with patch.object(optimization, "_solve_once", return_value=unknown_run):
            result = solve_lexicographic(validate_and_normalize(payload))

        self.assertEqual(result.status, FeasibilityStatus.UNKNOWN)
        self.assertFalse(result.assignments)
        self.assertEqual(
            result.stages[0].status,
            OptimizationStageStatus.UNKNOWN,
        )

    def test_precheck_infeasible_stops_before_solver(self) -> None:
        payload = one_day_input(
            [
                part_time(
                    "PT",
                    minimum=1,
                    maximum=1,
                    available_slots=[],
                )
            ],
            ("morning",),
        )

        with patch.object(optimization, "_solve_once") as solve_once:
            result = solve_lexicographic(validate_and_normalize(payload))

        self.assertEqual(
            result.status,
            FeasibilityStatus.PRECHECK_INFEASIBLE,
        )
        self.assertEqual(result.stages, ())
        solve_once.assert_not_called()

    def test_unknown_later_stage_preserves_prior_feasible_solution(self) -> None:
        payload = one_day_input(
            [full_time("TARGET", shift_mode="TARGET", target=1)],
            ("morning", "afternoon"),
        )
        normalized = validate_and_normalize(payload)
        original_solve_once = optimization._solve_once
        calls = 0

        def unknown_target(model, config):
            nonlocal calls
            calls += 1
            if calls == 2:
                return optimization._SolverRun(
                    solver=cp_model.CpSolver(),
                    raw_status=cp_model.UNKNOWN,
                    raw_status_name="UNKNOWN",
                    wall_time_seconds=0.0,
                )
            return original_solve_once(model, config)

        with patch.object(optimization, "_solve_once", side_effect=unknown_target):
            result = solve_lexicographic(normalized)

        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertFalse(result.implemented_objective_prefix_optimal)
        self.assertTrue(result.assignments)
        self.assertEqual(
            result.stages[-1].status,
            OptimizationStageStatus.UNKNOWN,
        )
        self.assertFalse(result.stages[-1].locked)


class PatternQualityOptimizationTests(unittest.TestCase):
    def test_b_triple_is_not_counted_as_consecutive_double(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=3,
                )
            ],
            ("morning", "afternoon", "evening"),
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        consecutive = stage(
            result, OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES
        )
        singles = stage(result, OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS)
        secondary = stage(
            result, OptimizationStage.FULL_TIME_SECONDARY_PATTERNS
        )

        self.assertEqual(
            result.daily_patterns[("B", date(2024, 10, 1))],
            DailyPattern.TRIPLE,
        )
        self.assertEqual(consecutive.direction, ObjectiveDirection.MAXIMIZE)
        self.assertEqual(consecutive.objective_value, 0)
        self.assertEqual(singles.objective_value, 0)
        self.assertEqual(secondary.objective_value, 1)
        self.assertTrue(consecutive.locked)
        self.assertTrue(singles.locked)
        self.assertTrue(secondary.locked)

    def test_single_day_objective_cannot_replace_locked_double_with_triple(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "B1",
                    full_time_class="B",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=3,
                ),
                full_time(
                    "B2",
                    full_time_class="B",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=3,
                ),
            ],
            ("morning", "afternoon", "evening"),
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        consecutive = stage(
            result, OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES
        )
        singles = stage(result, OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS)
        secondary = stage(
            result, OptimizationStage.FULL_TIME_SECONDARY_PATTERNS
        )
        patterns = [
            result.daily_patterns[(employee_id, date(2024, 10, 1))]
            for employee_id in ("B1", "B2")
        ]

        self.assertEqual(consecutive.objective_value, 1)
        self.assertTrue(consecutive.locked)
        self.assertEqual(singles.objective_value, 1)
        self.assertTrue(singles.locked)
        self.assertEqual(secondary.objective_value, 0)
        self.assertEqual(patterns.count(DailyPattern.TRIPLE), 0)
        self.assertEqual(
            sum(
                pattern
                in (
                    DailyPattern.MORNING_AFTERNOON,
                    DailyPattern.AFTERNOON_EVENING,
                )
                for pattern in patterns
            ),
            1,
        )

    def test_secondary_objective_cannot_break_locked_single_day_optimum(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "A1",
                    full_time_class="A",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=2,
                ),
                full_time(
                    "A2",
                    full_time_class="A",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=2,
                ),
            ],
            ("morning", "evening"),
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        consecutive = stage(
            result, OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES
        )
        singles = stage(result, OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS)
        secondary = stage(
            result, OptimizationStage.FULL_TIME_SECONDARY_PATTERNS
        )

        patterns = [
            result.daily_patterns[(employee_id, date(2024, 10, 1))]
            for employee_id in ("A1", "A2")
        ]
        self.assertEqual(consecutive.objective_value, 0)
        self.assertEqual(
            consecutive.status,
            OptimizationStageStatus.SKIPPED_CONSTANT,
        )
        self.assertEqual(singles.objective_value, 0)
        self.assertTrue(singles.locked)
        self.assertEqual(secondary.objective_value, 1)
        self.assertTrue(secondary.locked)
        self.assertEqual(patterns.count(DailyPattern.MORNING_EVENING), 1)
        self.assertEqual(patterns.count(DailyPattern.OFF), 1)

    def test_a_and_b_consecutive_doubles_share_one_combined_objective(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-02",
            roles=["assistant"],
            employees=[
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                    available_slots=available(
                        "2024-10-01", "morning", "afternoon"
                    ),
                ),
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=2,
                    available_slots=available(
                        "2024-10-02", "afternoon", "evening"
                    ),
                ),
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
                ("2024-10-01", "afternoon", "assistant"): 1,
                ("2024-10-02", "afternoon", "assistant"): 1,
                ("2024-10-02", "evening", "assistant"): 1,
            },
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        consecutive = stage(
            result, OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES
        )

        self.assertEqual(consecutive.objective_value, 2)
        self.assertEqual(consecutive.direction, ObjectiveDirection.MAXIMIZE)
        self.assertTrue(consecutive.locked)
        self.assertEqual(
            result.daily_patterns[("A", date(2024, 10, 1))],
            DailyPattern.MORNING_AFTERNOON,
        )
        self.assertEqual(
            result.daily_patterns[("B", date(2024, 10, 2))],
            DailyPattern.AFTERNOON_EVENING,
        )
        self.assertEqual(
            sum(
                item.stage is OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES
                for item in result.stages
            ),
            1,
        )

    def test_pattern_stages_are_skipped_when_there_are_no_full_time_staff(self) -> None:
        payload = one_day_input(
            [
                part_time(
                    "PT",
                    minimum=1,
                    maximum=1,
                    available_slots=available("2024-10-01", "morning"),
                )
            ],
            ("morning",),
        )

        result = solve_lexicographic(validate_and_normalize(payload))

        for stage_name in (
            OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
            OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP,
        ):
            fairness = stage(result, stage_name)
            self.assertEqual(
                fairness.status,
                OptimizationStageStatus.SKIPPED_CONSTANT,
            )
            self.assertEqual(fairness.objective_value, 0)
            self.assertEqual(
                fairness.constant_proof,
                ConstantProof.NO_COMPARABLE_FULL_TIME_CLASSES,
            )

        for stage_name in (
            OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES,
            OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS,
            OptimizationStage.FULL_TIME_SECONDARY_PATTERNS,
        ):
            stage_result = stage(result, stage_name)
            self.assertEqual(
                stage_result.status,
                OptimizationStageStatus.SKIPPED_CONSTANT,
            )
            self.assertEqual(stage_result.objective_value, 0)
            self.assertEqual(
                stage_result.constant_proof,
                ConstantProof.NO_FULL_TIME_EMPLOYEES,
            )


class FairnessOptimizationTests(unittest.TestCase):
    def test_class_quality_compares_different_legal_second_preferences(self) -> None:
        day = "2024-10-01"
        payload = synthetic_schedule_input(
            start_date=day,
            end_date=day,
            roles=["a_role", "b_role"],
            employees=[
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                    roles=["a_role"],
                ),
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=3,
                    roles=["b_role"],
                ),
            ],
            positive_demands={
                (day, "morning", "a_role"): 1,
                (day, "evening", "a_role"): 1,
                **{
                    (day, period, "b_role"): 1
                    for period in ("morning", "afternoon", "evening")
                },
            },
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(data, result.assignments)

        self.assertEqual(
            result.daily_patterns[("A", date(2024, 10, 1))],
            DailyPattern.MORNING_EVENING,
        )
        self.assertEqual(
            result.daily_patterns[("B", date(2024, 10, 1))],
            DailyPattern.TRIPLE,
        )
        for full_time_class in ("A", "B"):
            enum_class = optimization.FullTimeClass(full_time_class)
            self.assertEqual(
                metrics.class_quality_ratio_basis_points[
                    (enum_class, PatternQualityLevel.SECOND)
                ],
                10_000,
            )
        self.assertEqual(
            metrics.class_quality_ratio_gaps_basis_points[
                PatternQualityLevel.SECOND
            ],
            0,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
            ).objective_value,
            0,
        )

    def test_class_quality_precedes_within_class_fairness_and_keeps_prefix(self) -> None:
        days = tuple(f"2024-10-{day:02d}" for day in range(1, 5))
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                full_time(
                    "A1",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                    fairness_group="A_SHARED",
                ),
                full_time(
                    "A2",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=0,
                    fairness_group="A_SHARED",
                ),
                full_time(
                    "B1",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=2,
                    fairness_group="B_SHARED",
                ),
                full_time(
                    "B2",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="B_SHARED",
                ),
            ],
            positive_demands={
                **{
                    (day, "morning", "assistant"): 1 for day in days
                },
                (days[0], "afternoon", "assistant"): 1,
            },
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(data, result.assignments)
        report = validate_schedule_result(data, result.assignments, result.stages)

        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES,
            ).objective_value,
            1,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS,
            ).objective_value,
            3,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_SECONDARY_PATTERNS,
            ).objective_value,
            0,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
            ).objective_value,
            5000,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP,
            ).objective_value,
            10_000,
        )
        # A class-fair solution forces B1/B2 to receive opposite pattern
        # qualities.  Optimizing people first could make this 0 only by
        # worsening the already locked class gap to 10,000 bp.
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
            ).objective_value,
            10_000,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
            ).objective_value,
            20_000,
        )
        self.assertEqual(
            metrics.objective_values[
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP
            ],
            5000,
        )
        self.assertEqual(report.status, ResultValidationStatus.PASS)

    def test_class_quality_rounding_and_validator_recomputation_match(self) -> None:
        days = ("2024-10-01", "2024-10-02", "2024-10-03")
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["a_role", "b_role"],
            employees=[
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=4,
                    roles=["a_role"],
                ),
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=3,
                    roles=["b_role"],
                ),
            ],
            positive_demands={
                (days[0], "morning", "a_role"): 1,
                (days[0], "afternoon", "a_role"): 1,
                (days[1], "morning", "a_role"): 1,
                (days[2], "morning", "a_role"): 1,
                (days[0], "morning", "b_role"): 1,
                (days[0], "afternoon", "b_role"): 1,
                (days[1], "morning", "b_role"): 1,
            },
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        report = validate_schedule_result(data, result.assignments, result.stages)
        metrics = report.recomputed

        self.assertEqual(
            metrics.class_quality_ratio_basis_points[
                (optimization.FullTimeClass.A, PatternQualityLevel.FIRST)
            ],
            3333,
        )
        self.assertEqual(
            metrics.class_quality_ratio_basis_points[
                (optimization.FullTimeClass.B, PatternQualityLevel.FIRST)
            ],
            5000,
        )
        self.assertEqual(
            metrics.class_quality_ratio_gaps_basis_points[
                PatternQualityLevel.FIRST
            ],
            1667,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
            ).objective_value,
            1667,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP,
            ).objective_value,
            3334,
        )
        self.assertEqual(report.status, ResultValidationStatus.PASS)

    def test_zero_attendance_class_is_na_and_does_not_force_work(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                ),
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=0,
                ),
            ],
            ("morning",),
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        report = validate_schedule_result(data, result.assignments, result.stages)

        self.assertEqual(result.employee_shift_counts["B"], 0)
        self.assertIsNone(
            report.recomputed.class_quality_ratio_basis_points[
                (optimization.FullTimeClass.B, PatternQualityLevel.FIRST)
            ]
        )
        self.assertTrue(
            all(
                gap == 0
                for gap in report.recomputed.class_quality_ratio_gaps_basis_points.values()
            )
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
            ).objective_value,
            0,
        )
        self.assertEqual(report.status, ResultValidationStatus.PASS)

    def test_ratio_rounding_uses_shared_half_up_basis_points_rule(self) -> None:
        self.assertEqual(ratio_basis_points(5, 7), 7143)
        self.assertEqual(ratio_basis_points(1, 6), 1667)
        self.assertEqual(ratio_basis_points(2, 3), 6667)
        self.assertEqual(ratio_basis_points(1, 32), 313)
        self.assertEqual(ratio_basis_points(0, 3), 0)
        self.assertIsNone(ratio_basis_points(0, 0))

    def test_pattern_ratio_fairness_precedes_integer_gaps_for_a_and_b(self) -> None:
        days = tuple(f"2024-10-{day:02d}" for day in range(1, 9))
        positive_demands = {
            (day, "morning", "assistant"): 1 for day in days
        }
        positive_demands.update(
            {
                (day, "afternoon", "assistant"): 1
                for day in days[:2]
            }
        )
        for full_time_class in ("A", "B"):
            with self.subTest(full_time_class=full_time_class):
                payload = synthetic_schedule_input(
                    start_date=days[0],
                    end_date=days[-1],
                    roles=["assistant"],
                    employees=[
                        full_time(
                            "HIGH",
                            full_time_class=full_time_class,
                            shift_mode="EXACT",
                            required=7,
                            fairness_group=f"{full_time_class}_SHARED",
                        ),
                        full_time(
                            "LOW",
                            full_time_class=full_time_class,
                            shift_mode="EXACT",
                            required=3,
                            fairness_group=f"{full_time_class}_SHARED",
                        ),
                    ],
                    positive_demands=positive_demands,
                )
                data = validate_and_normalize(payload)
                result = solve_lexicographic(data)
                metrics = recompute_schedule_metrics(data, result.assignments)
                report = validate_schedule_result(
                    data, result.assignments, result.stages
                )

                self.assertEqual(
                    stage(
                        result,
                        OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES,
                    ).objective_value,
                    2,
                )
                self.assertEqual(
                    stage(
                        result,
                        OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS,
                    ).objective_value,
                    6,
                )
                self.assertEqual(
                    stage(
                        result,
                        OptimizationStage.FULL_TIME_SECONDARY_PATTERNS,
                    ).objective_value,
                    0,
                )
                self.assertEqual(
                    stage(
                        result,
                        OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
                    ).objective_value,
                    3333,
                )
                self.assertEqual(
                    stage(
                        result,
                        OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
                    ).objective_value,
                    6666,
                )
                # Integer-first optimization would choose gap sum 2 here;
                # ratio-first deliberately retains the fairer proportions.
                self.assertEqual(
                    stage(
                        result,
                        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
                    ).objective_value,
                    4,
                )
                self.assertEqual(
                    metrics.objective_values[
                        OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP
                    ],
                    3333,
                )
                self.assertEqual(report.status, ResultValidationStatus.PASS)
                self.assertEqual(
                    report.recomputed.objective_values,
                    metrics.objective_values,
                )
                ratio_stage_index = next(
                    index
                    for index, item in enumerate(result.stages)
                    if item.stage
                    is OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP
                )
                tampered_stages = list(result.stages)
                tampered_stages[ratio_stage_index] = replace(
                    tampered_stages[ratio_stage_index],
                    objective_value=3334,
                )
                tampered_report = validate_schedule_result(
                    data, result.assignments, tuple(tampered_stages)
                )
                self.assertEqual(
                    tampered_report.status,
                    ResultValidationStatus.VALIDATION_FAILED,
                )
                self.assertTrue(
                    any(
                        issue.code == "objective_value_mismatch"
                        for issue in tampered_report.issues
                    )
                )

    def test_ratio_groups_are_modelled_independently(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    employee_id,
                    full_time_class="A",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=1,
                    fairness_group=group,
                )
                for employee_id, group in (
                    ("A1", "G1"),
                    ("A2", "G1"),
                    ("A3", "G2"),
                    ("A4", "G2"),
                )
            ],
            (),
        )
        built = optimization.build_optimization_model(
            validate_and_normalize(payload)
        )

        self.assertEqual(
            {group for group, _metric in built.ratio_fairness_gap_variables},
            {"G1", "G2"},
        )
        self.assertEqual(len(built.ratio_fairness_gap_variables), 6)

    def test_zero_attendance_is_excluded_from_ratio_gap(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "ACTIVE",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="A_SHARED",
                ),
                full_time(
                    "OFF",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=0,
                    fairness_group="A_SHARED",
                ),
            ],
            ("morning",),
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(data, result.assignments)

        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
            ).objective_value,
            0,
        )
        self.assertEqual(
            metrics.pattern_ratio_basis_points[
                ("ACTIVE", optimization.FairnessMetric.SINGLE_SHIFT_DAYS)
            ],
            10_000,
        )
        self.assertIsNone(
            metrics.pattern_ratio_basis_points[
                ("OFF", optimization.FairnessMetric.SINGLE_SHIFT_DAYS)
            ]
        )

    def test_completed_prefix_is_optimal_without_claiming_full_v1_optimal(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                )
            ],
            ("morning",),
        )

        result = solve_lexicographic(validate_and_normalize(payload))

        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertTrue(result.implemented_objective_prefix_optimal)
        self.assertTrue(
            all(
                item.status
                in (
                    OptimizationStageStatus.FEASIBLE,
                    OptimizationStageStatus.OPTIMAL,
                    OptimizationStageStatus.SKIPPED_CONSTANT,
                )
                for item in result.stages
            )
        )

    def test_single_person_groups_are_constant_zero(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                )
            ],
            ("morning",),
        )

        result = solve_lexicographic(validate_and_normalize(payload))

        for stage_name in (
            OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
            OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
            OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
            OptimizationStage.PART_TIME_GROUP_FAIRNESS,
            OptimizationStage.COMMON_GROUP_FAIRNESS,
        ):
            fairness = stage(result, stage_name)
            self.assertEqual(
                fairness.status,
                OptimizationStageStatus.SKIPPED_CONSTANT,
            )
            self.assertEqual(fairness.objective_value, 0)
            self.assertEqual(
                fairness.constant_proof,
                ConstantProof.NO_COMPARABLE_FAIRNESS_GROUPS,
            )

    def test_part_time_gaps_are_isolated_and_summed_across_groups(self) -> None:
        day = "2024-10-01"
        payload = synthetic_schedule_input(
            start_date=day,
            end_date=day,
            roles=["g1", "g2"],
            employees=[
                part_time(
                    "P1",
                    minimum=0,
                    maximum=2,
                    available_slots=available_for(day, "g1", "morning", "afternoon"),
                    fairness_group="G1",
                    roles=["g1"],
                ),
                part_time(
                    "P2",
                    minimum=0,
                    maximum=2,
                    available_slots=available_for(day, "g1", "morning", "afternoon"),
                    fairness_group="G1",
                    roles=["g1"],
                ),
                part_time(
                    "P3",
                    minimum=0,
                    maximum=1,
                    available_slots=available_for(day, "g2", "evening"),
                    fairness_group="G2",
                    roles=["g2"],
                ),
                part_time(
                    "P4",
                    minimum=0,
                    maximum=1,
                    available_slots=available_for(day, "g2", "evening"),
                    fairness_group="G2",
                    roles=["g2"],
                ),
            ],
            positive_demands={
                (day, "morning", "g1"): 1,
                (day, "afternoon", "g1"): 1,
                (day, "evening", "g2"): 1,
            },
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        fairness = stage(result, OptimizationStage.PART_TIME_GROUP_FAIRNESS)

        g1 = sorted(result.employee_shift_counts[item] for item in ("P1", "P2"))
        g2 = sorted(result.employee_shift_counts[item] for item in ("P3", "P4"))
        self.assertEqual(g1, [1, 1])
        self.assertEqual(g2, [0, 1])
        self.assertEqual((max(g1) - min(g1)) + (max(g2) - min(g2)), 1)
        self.assertEqual(fairness.objective_value, 1)
        self.assertEqual(fairness.status, OptimizationStageStatus.OPTIMAL)
        self.assertTrue(fairness.locked)

    def test_a_group_uses_max_minus_min_for_all_three_pattern_metrics(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "A1",
                    full_time_class="A",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=2,
                    fairness_group="A_SHARED",
                ),
                full_time(
                    "A2",
                    full_time_class="A",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=2,
                    fairness_group="A_SHARED",
                ),
            ],
            ("morning", "evening"),
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        fairness = stage(
            result, OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS
        )
        patterns = [
            result.daily_patterns[(item, date(2024, 10, 1))]
            for item in ("A1", "A2")
        ]

        self.assertEqual(patterns.count(DailyPattern.MORNING_EVENING), 1)
        self.assertEqual(patterns.count(DailyPattern.OFF), 1)
        self.assertEqual(fairness.objective_value, 1)
        self.assertTrue(fairness.locked)

    def test_b_group_fairness_preserves_locked_pattern_totals(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-02",
            roles=["assistant"],
            employees=[
                full_time(
                    "B1",
                    full_time_class="B",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=6,
                    fairness_group="B_SHARED",
                ),
                full_time(
                    "B2",
                    full_time_class="B",
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=6,
                    fairness_group="B_SHARED",
                ),
            ],
            positive_demands={
                (day, period, "assistant"): 1
                for day in ("2024-10-01", "2024-10-02")
                for period in ("morning", "afternoon", "evening")
            },
        )

        result = solve_lexicographic(validate_and_normalize(payload))
        consecutive = stage(
            result, OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES
        )
        singles = stage(result, OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS)
        b_fairness = stage(
            result, OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS
        )
        counts = {
            employee_id: Counter(
                pattern
                for (person, _day), pattern in result.daily_patterns.items()
                if person == employee_id
            )
            for employee_id in ("B1", "B2")
        }

        self.assertEqual(consecutive.objective_value, 2)
        self.assertEqual(singles.objective_value, 2)
        self.assertEqual(b_fairness.objective_value, 0)
        for employee_id in ("B1", "B2"):
            self.assertEqual(
                counts[employee_id][DailyPattern.MORNING_AFTERNOON]
                + counts[employee_id][DailyPattern.AFTERNOON_EVENING],
                1,
            )
            self.assertEqual(
                counts[employee_id][DailyPattern.MORNING_ONLY]
                + counts[employee_id][DailyPattern.AFTERNOON_ONLY]
                + counts[employee_id][DailyPattern.EVENING_ONLY],
                1,
            )
            self.assertEqual(counts[employee_id][DailyPattern.TRIPLE], 0)

    def test_common_fairness_uses_period_sunday_and_holiday_integer_gaps(self) -> None:
        day = "2024-10-06"  # Sunday.
        payload = synthetic_schedule_input(
            start_date=day,
            end_date=day,
            roles=["assistant"],
            employees=[
                full_time(
                    "A1",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="A_SHARED",
                ),
                full_time(
                    "A2",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="A_SHARED",
                ),
            ],
            positive_demands={
                (day, "morning", "assistant"): 1,
                (day, "afternoon", "assistant"): 1,
            },
        )
        payload["period"]["holidays"] = [day]

        result = solve_lexicographic(validate_and_normalize(payload))
        common = stage(result, OptimizationStage.COMMON_GROUP_FAIRNESS)
        by_employee = {
            employee_id: Counter(
                assignment.period.value
                for assignment in result.assignments
                if assignment.employee_id == employee_id
            )
            for employee_id in ("A1", "A2")
        }

        period_gap_sum = sum(
            abs(by_employee["A1"][period] - by_employee["A2"][period])
            for period in ("morning", "afternoon", "evening")
        )
        sunday_gap = 0  # Each person has exactly one shift on this Sunday.
        holiday_gap = 0  # The same date is explicitly marked as a holiday.
        self.assertEqual(period_gap_sum + sunday_gap + holiday_gap, 2)
        self.assertEqual(common.objective_value, 2)
        self.assertTrue(common.locked)


if __name__ == "__main__":
    unittest.main()
