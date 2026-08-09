from __future__ import annotations

import unittest
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
    solve_lexicographic,
    validate_and_normalize,
)

from tests.fixtures import synthetic_schedule_input


def available(day: str, *periods: str) -> list[dict]:
    return [
        {"date": day, "period": period, "roles": ["assistant"]}
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
) -> dict:
    employee = {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "full_time",
        "full_time_class": full_time_class,
        "roles": ["assistant"],
        "fairness_group": f"{full_time_class}_{employee_id}",
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
    minimum: int,
    maximum: int,
    available_slots: list[dict],
) -> dict:
    return {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "part_time",
        "full_time_class": None,
        "roles": ["assistant"],
        "fairness_group": f"PT_{employee_id}",
        "shift_mode": "RANGE",
        "min_shifts": minimum,
        "max_shifts": maximum,
        "available_slots": available_slots,
    }


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

                self.assertEqual(result.status, FeasibilityStatus.OPTIMAL)
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

        self.assertEqual(result.status, FeasibilityStatus.OPTIMAL)
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

        self.assertEqual(result.status, FeasibilityStatus.OPTIMAL)
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


if __name__ == "__main__":
    unittest.main()
