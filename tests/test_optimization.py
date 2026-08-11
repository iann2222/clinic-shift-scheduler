from __future__ import annotations

import unittest
from collections import Counter
from dataclasses import replace
from datetime import date
from unittest.mock import patch

from ortools.sat.python import cp_model

import clinic_shift_scheduler.optimization as optimization
from clinic_shift_scheduler import (
    Assignment,
    ConstantProof,
    DailyPattern,
    FairnessMetric,
    FeasibilityStatus,
    ObjectiveDirection,
    OptimizationStage,
    OptimizationStageStatus,
    PreferenceRank,
    ResultValidationStatus,
    recompute_schedule_metrics,
    solve_lexicographic,
    validate_and_normalize,
    validate_schedule_result,
)
from clinic_shift_scheduler.enums import Period

from tests.fixtures import synthetic_schedule_input
from clinic_shift_scheduler.ratio_fairness import ratio_basis_points
from clinic_shift_scheduler.result_validation import FORMAL_STAGE_SEQUENCE


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
            FORMAL_STAGE_SEQUENCE,
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
    def test_b_monthly_single_shift_cap_allows_three_and_rejects_four(self) -> None:
        def payload_for(day_count: int) -> dict:
            days = tuple(
                f"2024-10-{day:02d}" for day in range(1, day_count + 1)
            )
            return synthetic_schedule_input(
                start_date=days[0],
                end_date=days[-1],
                roles=["assistant"],
                employees=[
                    full_time(
                        "B",
                        full_time_class="B",
                        shift_mode="EXACT",
                        required=day_count,
                    )
                ],
                positive_demands={
                    (day, "morning", "assistant"): 1 for day in days
                },
            )

        allowed = solve_lexicographic(
            validate_and_normalize(payload_for(3))
        )
        rejected = solve_lexicographic(
            validate_and_normalize(payload_for(4))
        )

        self.assertEqual(allowed.status, FeasibilityStatus.FEASIBLE)
        self.assertEqual(
            sum(
                pattern in (
                    DailyPattern.MORNING_ONLY,
                    DailyPattern.AFTERNOON_ONLY,
                    DailyPattern.EVENING_ONLY,
                )
                for pattern in allowed.daily_patterns.values()
            ),
            3,
        )
        self.assertEqual(rejected.status, FeasibilityStatus.INFEASIBLE)

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
        metrics = recompute_schedule_metrics(
            validate_and_normalize(payload),
            result.assignments,
            result.preference_benchmarks,
        )

        self.assertEqual(
            result.daily_patterns[("B", date(2024, 10, 1))],
            DailyPattern.TRIPLE,
        )
        self.assertEqual(metrics.employee_metrics["B"].triple_days, 1)
        self.assertEqual(metrics.employee_metrics["B"].consecutive_double_days, 0)
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            ).objective_value,
            0,
        )

    def test_b_avoids_single_before_considering_consecutive_double(self) -> None:
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
        patterns = [
            result.daily_patterns[(employee_id, date(2024, 10, 1))]
            for employee_id in ("B1", "B2")
        ]

        self.assertEqual(patterns.count(DailyPattern.TRIPLE), 1)
        self.assertEqual(patterns.count(DailyPattern.OFF), 1)
        b_first = next(
            item
            for item in result.preference_benchmarks
            if item.full_time_class.value == "B"
            and item.rank is PreferenceRank.FIRST
        )
        self.assertEqual(b_first.ideal_value, 0)
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            ).objective_value,
            0,
        )

    def test_a_uses_morning_evening_as_second_preference(self) -> None:
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
        patterns = [
            result.daily_patterns[(employee_id, date(2024, 10, 1))]
            for employee_id in ("A1", "A2")
        ]
        self.assertEqual(patterns.count(DailyPattern.MORNING_EVENING), 1)
        self.assertEqual(patterns.count(DailyPattern.OFF), 1)
        a_second = next(
            item
            for item in result.preference_benchmarks
            if item.full_time_class.value == "A"
            and item.rank is PreferenceRank.SECOND
        )
        self.assertEqual(a_second.ideal_value, 1)

    def test_a_never_sacrifices_consecutive_double_for_second_preference(self) -> None:
        days = ("2024-10-01", "2024-10-02")
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                ),
                part_time(
                    "PT",
                    required=2,
                    available_slots=available(
                        days[0], "morning", "afternoon"
                    )
                    + available(days[1], "morning", "evening"),
                ),
            ],
            positive_demands={
                (days[0], "morning", "assistant"): 1,
                (days[0], "afternoon", "assistant"): 1,
                (days[1], "morning", "assistant"): 1,
                (days[1], "evening", "assistant"): 1,
            },
        )

        result = solve_lexicographic(validate_and_normalize(payload))

        self.assertEqual(
            result.daily_patterns[("A", date(2024, 10, 1))],
            DailyPattern.MORNING_AFTERNOON,
        )
        self.assertEqual(
            result.daily_patterns[("A", date(2024, 10, 2))],
            DailyPattern.OFF,
        )

    def test_b_uses_consecutive_doubles_before_triple_fallback(self) -> None:
        days = ("2024-10-01", "2024-10-02", "2024-10-03")
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=6,
                ),
                part_time(
                    "PT1",
                    required=2,
                    available_slots=sum(
                        (available(day, "morning", "afternoon", "evening") for day in days),
                        [],
                    ),
                ),
                part_time(
                    "PT2",
                    required=1,
                    available_slots=sum(
                        (available(day, "morning", "afternoon", "evening") for day in days),
                        [],
                    ),
                ),
            ],
            positive_demands={
                (day, period, "assistant"): 1
                for day in days
                for period in ("morning", "afternoon", "evening")
            },
        )
        data = validate_and_normalize(payload)

        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(
            data, result.assignments, result.preference_benchmarks
        )

        self.assertEqual(metrics.employee_metrics["B"].single_shift_days, 0)
        self.assertEqual(metrics.employee_metrics["B"].consecutive_double_days, 3)
        self.assertEqual(metrics.employee_metrics["B"].triple_days, 0)

    def test_a_and_b_use_separate_preference_benchmarks(self) -> None:
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
        self.assertEqual(
            result.daily_patterns[("A", date(2024, 10, 1))],
            DailyPattern.MORNING_AFTERNOON,
        )
        self.assertEqual(
            result.daily_patterns[("B", date(2024, 10, 2))],
            DailyPattern.AFTERNOON_EVENING,
        )
        ideals = {
            (item.full_time_class.value, item.rank.value): item.ideal_value
            for item in result.preference_benchmarks
        }
        self.assertEqual(
            ideals,
            {("A", "first"): 1, ("B", "first"): 0, ("A", "second"): 0, ("B", "second"): 1},
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
        self.assertEqual(len(result.preference_benchmarks), 4)
        self.assertTrue(
            all(
                item.status is OptimizationStageStatus.SKIPPED_CONSTANT
                and item.ideal_value == 0
                and item.opportunity_days == 0
                for item in result.preference_benchmarks
            )
        )
        for stage_name in (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ):
            self.assertEqual(
                stage(result, stage_name).status,
                OptimizationStageStatus.SKIPPED_CONSTANT,
            )


class FairnessOptimizationTests(unittest.TestCase):
    def test_class_first_preferences_use_independent_conditional_ideals(self) -> None:
        days = ("2024-10-01", "2024-10-02", "2024-10-03")
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                ),
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=1,
                ),
            ],
            positive_demands={
                (days[0], "morning", "assistant"): 1,
                (days[0], "afternoon", "assistant"): 1,
                (days[1], "morning", "assistant"): 1,
            },
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(
            data, result.assignments, result.preference_benchmarks
        )
        ideals = {
            (item.full_time_class.value, item.rank.value): item.ideal_value
            for item in result.preference_benchmarks
        }

        self.assertEqual(ideals[("A", "first")], 1)
        self.assertEqual(ideals[("B", "first")], 1)
        self.assertEqual(
            metrics.employee_metrics["A"].consecutive_double_days, 1
        )
        self.assertEqual(metrics.employee_metrics["B"].single_shift_days, 1)
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            ).objective_value,
            0,
        )
        self.assertEqual(
            stage(
                result,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
            ).objective_value,
            0,
        )

    def test_preference_metrics_and_validator_recompute_identically(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    "A",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                ),
                full_time(
                    "B",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=1,
                ),
            ],
            ("morning", "afternoon", "evening"),
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(
            data, result.assignments, result.preference_benchmarks
        )
        report = validate_schedule_result(
            data,
            result.assignments,
            result.stages,
            result.preference_benchmarks,
            result.class_pattern_locks,
        )

        self.assertEqual(report.status, ResultValidationStatus.PASS)
        for benchmark in result.preference_benchmarks:
            self.assertEqual(
                benchmark.locked_actual_value,
                metrics.class_preference_actual_values[
                    (benchmark.full_time_class, benchmark.rank)
                ],
            )
        self.assertEqual(len(result.class_pattern_locks), 2)
        for item in result.class_pattern_locks:
            self.assertEqual(
                item.locked_value,
                metrics.class_remaining_pattern_actual_values[
                    item.full_time_class
                ],
            )
        for stage_name in (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ):
            self.assertEqual(
                stage(result, stage_name).objective_value,
                metrics.objective_values[stage_name],
            )

    def test_ratio_rounding_uses_shared_half_up_basis_points_rule(self) -> None:
        self.assertEqual(ratio_basis_points(5, 7), 7143)
        self.assertEqual(ratio_basis_points(1, 6), 1667)
        self.assertEqual(ratio_basis_points(2, 3), 6667)
        self.assertEqual(ratio_basis_points(1, 32), 313)
        self.assertEqual(ratio_basis_points(0, 3), 0)
        self.assertIsNone(ratio_basis_points(0, 0))

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

    def test_person_fairness_metrics_follow_each_class_preference_order(self) -> None:
        payload = one_day_input(
            [
                full_time(
                    employee_id,
                    full_time_class=full_time_class,
                    shift_mode="RANGE",
                    minimum=0,
                    maximum=1,
                    fairness_group=f"{full_time_class}_SHARED",
                )
                for full_time_class in ("A", "B")
                for employee_id in (
                    f"{full_time_class}1",
                    f"{full_time_class}2",
                )
            ],
            (),
        )
        built = optimization.build_optimization_model(
            validate_and_normalize(payload)
        )
        rank1 = built.preference_ratio_gap_variables[
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP
        ]
        rank2 = built.preference_ratio_gap_variables[
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP
        ]
        remaining = built.preference_ratio_gap_variables[
            OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP
        ]

        self.assertEqual(
            set(rank1),
            {
                ("A_SHARED", FairnessMetric.CONSECUTIVE_DOUBLES),
                ("B_SHARED", FairnessMetric.SINGLE_SHIFT_DAYS),
            },
        )
        self.assertEqual(
            set(rank2),
            {
                ("A_SHARED", FairnessMetric.MORNING_EVENING_DAYS),
                ("B_SHARED", FairnessMetric.CONSECUTIVE_DOUBLES),
            },
        )
        self.assertEqual(
            set(remaining),
            {
                ("A_SHARED", FairnessMetric.SINGLE_SHIFT_DAYS),
                ("B_SHARED", FairnessMetric.TRIPLE_DAYS),
            },
        )

    def test_ratio_max_objective_is_not_overwritten_by_gap_sum(self) -> None:
        days = tuple(f"2024-10-{day:02d}" for day in range(1, 5))
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                full_time(
                    employee_id,
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=required,
                    fairness_group=group,
                )
                for employee_id, required, group in (
                    ("A1", 3, "G1"),
                    ("A2", 1, "G1"),
                    ("A3", 3, "G2"),
                    ("A4", 1, "G2"),
                )
            ],
            positive_demands={
                (day, period, "assistant"): 1
                for day in days
                for period in ("morning", "afternoon")
            },
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(
            data, result.assignments, result.preference_benchmarks
        )
        maximum_stage = OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP
        total_stage = OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP
        gaps = metrics.fairness_gaps[maximum_stage]

        self.assertEqual(len(gaps), 6)
        self.assertGreater(sum(gaps.values()), max(gaps.values()))
        self.assertEqual(
            metrics.objective_values[maximum_stage], max(gaps.values())
        )
        self.assertEqual(
            metrics.objective_values[total_stage], sum(gaps.values())
        )

    def test_joint_ratio_fairness_avoids_locking_one_small_gap_too_early(self) -> None:
        days = tuple(f"2024-10-{day:02d}" for day in range(1, 5))
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                full_time(
                    "B1",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=5,
                    fairness_group="B_SHARED",
                ),
                full_time(
                    "B2",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=3,
                    fairness_group="B_SHARED",
                ),
            ],
            positive_demands={
                (days[0], period, "assistant"): 1
                for period in ("morning", "afternoon", "evening")
            }
            | {
                (day, period, "assistant"): 1
                for day in days[1:3]
                for period in ("morning", "afternoon")
            }
            | {(days[3], "morning", "assistant"): 1},
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        final_metrics = recompute_schedule_metrics(
            data, result.assignments, result.preference_benchmarks
        )
        old_style_candidate = (
            *(
                Assignment("B2", date(2024, 10, 1), period, "assistant")
                for period in Period
            ),
            Assignment("B1", date(2024, 10, 2), Period.MORNING, "assistant"),
            Assignment("B1", date(2024, 10, 2), Period.AFTERNOON, "assistant"),
            Assignment("B1", date(2024, 10, 3), Period.MORNING, "assistant"),
            Assignment("B1", date(2024, 10, 3), Period.AFTERNOON, "assistant"),
            Assignment("B1", date(2024, 10, 4), Period.MORNING, "assistant"),
        )
        candidate_metrics = recompute_schedule_metrics(
            data, old_style_candidate, result.preference_benchmarks
        )
        formal_max = OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP
        first_total = (
            OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP
        )

        self.assertEqual(
            final_metrics.class_preference_actual_values,
            candidate_metrics.class_preference_actual_values,
        )
        self.assertGreater(
            final_metrics.objective_values[first_total],
            candidate_metrics.objective_values[first_total],
        )
        self.assertEqual(final_metrics.objective_values[first_total], 5000)
        self.assertEqual(candidate_metrics.objective_values[first_total], 3333)
        self.assertEqual(final_metrics.objective_values[formal_max], 5000)
        self.assertEqual(candidate_metrics.objective_values[formal_max], 10_000)

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
        metrics = recompute_schedule_metrics(
            data, result.assignments, result.preference_benchmarks
        )

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
            OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP,
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
        for stage_name in (
            OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
            OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
        ):
            fairness = stage(result, stage_name)
            self.assertEqual(
                fairness.status,
                OptimizationStageStatus.SKIPPED_CONSTANT,
            )
            self.assertEqual(fairness.objective_value, 0)
            self.assertEqual(
                fairness.constant_proof,
                ConstantProof.NO_COMPARABLE_FULL_TIME_EMPLOYEES,
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

    def test_common_fairness_includes_period_sunday_and_holiday_gaps(self) -> None:
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

        data = validate_and_normalize(payload)
        built = optimization.build_optimization_model(data)
        common_gaps = built.fairness_gap_variables[
            OptimizationStage.COMMON_GROUP_FAIRNESS
        ]
        self.assertIn(
            ("A_SHARED", FairnessMetric.SUNDAY_SHIFTS),
            common_gaps,
        )
        result = solve_lexicographic(data)
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
        expected_weighted_gap = (
            3 * period_gap_sum + 7 * sunday_gap + 3 * holiday_gap
        )
        self.assertEqual(expected_weighted_gap, 6)
        self.assertEqual(common.objective_value, expected_weighted_gap)
        self.assertTrue(common.locked)

    def test_common_fairness_weights_sunday_gap_seven_to_three(self) -> None:
        day = "2024-10-06"  # Sunday and explicitly marked holiday.
        payload = synthetic_schedule_input(
            start_date=day,
            end_date=day,
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
            ],
            positive_demands={
                (day, "morning", "assistant"): 1,
                (day, "afternoon", "assistant"): 1,
            },
        )
        payload["period"]["holidays"] = [day]

        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        common = stage(result, OptimizationStage.COMMON_GROUP_FAIRNESS)
        metrics = recompute_schedule_metrics(
            data,
            result.assignments,
            result.preference_benchmarks,
        )
        report = validate_schedule_result(
            data,
            result.assignments,
            result.stages,
            result.preference_benchmarks,
            result.class_pattern_locks,
        )

        # Sunday gap is 2. Morning, afternoon and holiday gaps are 1, 1 and 2.
        expected_weighted_gap = 7 * 2 + 3 * (1 + 1 + 2)
        self.assertEqual(common.objective_value, expected_weighted_gap)
        self.assertEqual(
            metrics.objective_values[OptimizationStage.COMMON_GROUP_FAIRNESS],
            expected_weighted_gap,
        )
        self.assertEqual(report.status, ResultValidationStatus.PASS)
        self.assertTrue(common.locked)

    def test_final_sunday_fairness_compares_all_full_time_employees(self) -> None:
        sunday = "2024-10-06"
        monday = "2024-10-07"
        payload = synthetic_schedule_input(
            start_date=sunday,
            end_date=monday,
            roles=["assistant"],
            employees=[
                full_time(
                    "A1",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="A_G1",
                ),
                full_time(
                    "A2",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="A_G2",
                ),
                full_time(
                    "B1",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="B_G1",
                ),
                full_time(
                    "B2",
                    full_time_class="B",
                    shift_mode="EXACT",
                    required=1,
                    fairness_group="B_G2",
                ),
            ],
            positive_demands={
                (sunday, "morning", "assistant"): 1,
                (sunday, "afternoon", "assistant"): 1,
                (monday, "morning", "assistant"): 1,
                (monday, "afternoon", "assistant"): 1,
            },
        )

        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        metrics = recompute_schedule_metrics(
            data,
            result.assignments,
            result.preference_benchmarks,
        )
        maximum = stage(
            result,
            OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
        )
        total = stage(
            result,
            OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
        )

        self.assertEqual(maximum.objective_value, 1)
        self.assertEqual(total.objective_value, 2)
        self.assertTrue(maximum.locked)
        self.assertTrue(total.locked)
        self.assertEqual(
            metrics.objective_values[
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP
            ],
            1,
        )
        self.assertEqual(
            metrics.objective_values[
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP
            ],
            2,
        )
        self.assertEqual(
            tuple(item.stage for item in result.stages)[-2:],
            (
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
            ),
        )

    def test_sunday_attendance_days_count_each_date_once(self) -> None:
        sunday = "2024-10-06"
        monday = "2024-10-07"
        payload = synthetic_schedule_input(
            start_date=sunday,
            end_date=monday,
            roles=["assistant"],
            employees=[
                full_time(
                    "A1",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                ),
                full_time(
                    "A2",
                    full_time_class="A",
                    shift_mode="EXACT",
                    required=2,
                ),
            ],
            positive_demands={
                (sunday, "morning", "assistant"): 1,
                (sunday, "afternoon", "assistant"): 1,
                (monday, "morning", "assistant"): 1,
                (monday, "afternoon", "assistant"): 1,
            },
        )
        data = validate_and_normalize(payload)
        assignments = (
            Assignment("A1", date(2024, 10, 6), Period.MORNING, "assistant"),
            Assignment("A1", date(2024, 10, 6), Period.AFTERNOON, "assistant"),
            Assignment("A2", date(2024, 10, 7), Period.MORNING, "assistant"),
            Assignment("A2", date(2024, 10, 7), Period.AFTERNOON, "assistant"),
        )

        metrics = recompute_schedule_metrics(data, assignments)

        self.assertEqual(metrics.employee_metrics["A1"].sunday_shifts, 2)
        self.assertEqual(
            metrics.employee_metrics["A1"].sunday_attendance_days,
            1,
        )
        self.assertEqual(
            metrics.objective_values[
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP
            ],
            2,
        )
        self.assertEqual(
            metrics.objective_values[
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP
            ],
            3,
        )


if __name__ == "__main__":
    unittest.main()
