from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from clinic_shift_scheduler import (
    Assignment,
    FeasibilityStatus,
    OptimizationStage,
    RatioValue,
    ResultValidationStatus,
    ScheduleCellKind,
    finalize_schedule_output,
    solve_lexicographic,
    validate_and_normalize,
    validate_schedule_result,
)
from clinic_shift_scheduler.enums import Period

from tests.fixtures import minimal_valid_input, synthetic_schedule_input


def issue_codes(report) -> set[str]:
    return {item.code for item in report.issues}


class IndependentResultValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = validate_and_normalize(minimal_valid_input())
        cls.result = solve_lexicographic(cls.data)

    def validate_assignments(self, assignments: tuple[Assignment, ...]):
        return validate_schedule_result(
            self.data,
            assignments,
            self.result.stages,
            self.result.preference_benchmarks,
            self.result.class_pattern_locks,
        )

    def test_valid_result_is_promoted_only_after_independent_validation(self) -> None:
        output = finalize_schedule_output(self.data, self.result)

        self.assertEqual(self.result.status, FeasibilityStatus.FEASIBLE)
        self.assertTrue(self.result.implemented_objective_prefix_optimal)
        self.assertEqual(output.validation_report.status, ResultValidationStatus.PASS)
        self.assertEqual(output.status, FeasibilityStatus.OPTIMAL)
        self.assertTrue(output.has_formal_schedule)

    def test_tampered_assignment_fails_and_suppresses_formal_schedule(self) -> None:
        tampered = replace(
            self.result,
            assignments=self.result.assignments[:-1],
        )

        output = finalize_schedule_output(self.data, tampered)

        self.assertEqual(output.status, FeasibilityStatus.VALIDATION_FAILED)
        self.assertFalse(output.has_formal_schedule)
        self.assertIsNone(output.monthly_schedule)
        self.assertIn("demand_count_mismatch", issue_codes(output.validation_report))
        self.assertIn("total_assignment_mismatch", issue_codes(output.validation_report))

    def test_unqualified_role_is_detected_from_assignments(self) -> None:
        original = next(
            item for item in self.result.assignments if item.employee_id == "FT002"
        )
        wrong = replace(original, role="reception")
        assignments = tuple(
            wrong if item is original else item for item in self.result.assignments
        )

        report = self.validate_assignments(assignments)

        self.assertEqual(report.status, ResultValidationStatus.VALIDATION_FAILED)
        self.assertIn("unqualified_role", issue_codes(report))

    def test_duplicate_and_same_period_role_assignments_are_detected(self) -> None:
        original = self.result.assignments[0]
        duplicate_report = self.validate_assignments(
            (*self.result.assignments, original)
        )
        second_role = replace(original, role="assistant")
        overlap_report = self.validate_assignments(
            (*self.result.assignments, second_role)
        )

        self.assertIn("duplicate_assignment", issue_codes(duplicate_report))
        self.assertIn("multiple_roles_same_period", issue_codes(duplicate_report))
        self.assertIn("multiple_roles_same_period", issue_codes(overlap_report))

    def test_a_b_and_part_time_illegal_daily_patterns_are_recomputed(self) -> None:
        day = date(2024, 10, 1)
        cases = (
            (
                "illegal_a_daily_pattern",
                tuple(
                    Assignment("FT001", day, period, "reception")
                    for period in Period
                ),
            ),
            (
                "illegal_b_daily_pattern",
                (
                    Assignment("FT002", day, Period.MORNING, "assistant"),
                    Assignment("FT002", day, Period.EVENING, "assistant"),
                ),
            ),
            (
                "illegal_part_time_daily_pattern",
                tuple(
                    Assignment("PT001", day, period, "assistant")
                    for period in Period
                ),
            ),
        )
        for expected, assignments in cases:
            with self.subTest(expected=expected):
                report = self.validate_assignments(assignments)
                self.assertIn(expected, issue_codes(report))

    def test_demand_count_and_exact_shift_mismatches_are_detected(self) -> None:
        assignments = tuple(
            item for item in self.result.assignments if item.employee_id != "FT001"
        )

        report = self.validate_assignments(assignments)

        self.assertIn("demand_count_mismatch", issue_codes(report))
        self.assertIn("exact_shift_mismatch", issue_codes(report))

    def test_locked_objective_value_mismatch_is_detected(self) -> None:
        target_index = next(
            index
            for index, item in enumerate(self.result.stages)
            if item.stage is OptimizationStage.FULL_TIME_TARGET_DEVIATION
        )
        target = self.result.stages[target_index]
        changed_stage = replace(
            target,
            objective_value=(target.objective_value or 0) + 1,
        )
        stages = list(self.result.stages)
        stages[target_index] = changed_stage
        tampered = replace(self.result, stages=tuple(stages))

        output = finalize_schedule_output(self.data, tampered)

        self.assertEqual(output.status, FeasibilityStatus.VALIDATION_FAILED)
        self.assertIn("objective_value_mismatch", issue_codes(output.validation_report))
        self.assertFalse(output.has_formal_schedule)

    def test_tampered_preference_benchmark_is_detected(self) -> None:
        original = self.result.preference_benchmarks[0]
        changed_ideal = (
            (original.ideal_value or 0) - 1
            if original.direction.value == "MAXIMIZE"
            else (original.ideal_value or 0) + 1
        )
        benchmarks = list(self.result.preference_benchmarks)
        benchmarks[0] = replace(original, ideal_value=changed_ideal)
        tampered = replace(
            self.result,
            preference_benchmarks=tuple(benchmarks),
        )

        output = finalize_schedule_output(self.data, tampered)

        self.assertEqual(output.status, FeasibilityStatus.VALIDATION_FAILED)
        self.assertIn(
            "preference_benchmark_ideal_violated",
            issue_codes(output.validation_report),
        )

    def test_tampered_locked_class_actual_is_detected(self) -> None:
        original = self.result.preference_benchmarks[0]
        benchmarks = list(self.result.preference_benchmarks)
        benchmarks[0] = replace(
            original,
            locked_actual_value=(original.locked_actual_value or 0) + 1,
        )
        tampered = replace(
            self.result,
            preference_benchmarks=tuple(benchmarks),
        )

        output = finalize_schedule_output(self.data, tampered)

        self.assertEqual(output.status, FeasibilityStatus.VALIDATION_FAILED)
        self.assertIn(
            "preference_locked_actual_mismatch",
            issue_codes(output.validation_report),
        )

    def test_tampered_remaining_pattern_class_lock_is_detected(self) -> None:
        original = self.result.class_pattern_locks[0]
        locks = list(self.result.class_pattern_locks)
        locks[0] = replace(original, locked_value=original.locked_value + 1)
        tampered = replace(self.result, class_pattern_locks=tuple(locks))

        output = finalize_schedule_output(self.data, tampered)

        self.assertEqual(output.status, FeasibilityStatus.VALIDATION_FAILED)
        self.assertIn(
            "class_pattern_lock_value_mismatch",
            issue_codes(output.validation_report),
        )

    def test_b_monthly_single_shift_limit_is_independently_validated(self) -> None:
        days = ("2024-10-01", "2024-10-02")
        payload = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[
                {
                    "employee_id": "B",
                    "name": "B",
                    "employment_type": "full_time",
                    "full_time_class": "B",
                    "roles": ["assistant"],
                    "fairness_group": "B_ONLY",
                    "shift_mode": "EXACT",
                    "required_shifts": 2,
                }
            ],
            positive_demands={
                (day, "morning", "assistant"): 1 for day in days
            },
        )
        data = validate_and_normalize(payload)
        assignments = tuple(
            Assignment("B", date.fromisoformat(day), Period.MORNING, "assistant")
            for day in days
        )

        report = validate_schedule_result(data, assignments, (), ())

        self.assertIn(
            "b_monthly_single_shift_limit_exceeded",
            issue_codes(report),
        )

    def test_leave_closed_dates_and_shift_bounds_are_revalidated(self) -> None:
        leave_payload = minimal_valid_input()
        leave_payload["leave_requests"] = [
            {"employee_id": "FT001", "date": "2024-10-01", "all_day": True}
        ]
        leave_data = validate_and_normalize(leave_payload)
        leave_report = validate_schedule_result(
            leave_data,
            self.result.assignments,
            self.result.stages,
            self.result.preference_benchmarks,
            self.result.class_pattern_locks,
        )

        range_payload = minimal_valid_input()
        range_payload["employees"][2]["min_shifts"] = 1
        range_data = validate_and_normalize(range_payload)
        range_report = validate_schedule_result(
            range_data,
            self.result.assignments,
            self.result.stages,
            self.result.preference_benchmarks,
            self.result.class_pattern_locks,
        )

        target_payload = minimal_valid_input()
        target_payload["employees"][1]["min_shifts"] = 4
        target_data = validate_and_normalize(target_payload)
        target_report = validate_schedule_result(
            target_data,
            self.result.assignments,
            self.result.stages,
            self.result.preference_benchmarks,
            self.result.class_pattern_locks,
        )

        self.assertIn("assignment_on_unavailable_period", issue_codes(leave_report))
        self.assertIn("range_shift_mismatch", issue_codes(range_report))
        self.assertIn("target_min_shift_mismatch", issue_codes(target_report))


class StructuredOutputTests(unittest.TestCase):
    def test_statistics_are_recomputed_from_final_assignments(self) -> None:
        data = validate_and_normalize(minimal_valid_input())
        result = solve_lexicographic(data)
        output = finalize_schedule_output(data, result)

        overall = output.overall_statistics
        self.assertEqual(overall.total_demand, 5)
        self.assertEqual(overall.total_assignments, 5)
        self.assertEqual(overall.unfilled_shifts, 0)
        self.assertEqual(
            sum(item.total_shifts for item in output.individual_statistics),
            overall.total_assignments,
        )
        self.assertEqual(
            overall.objective_vector["part_time_usage"],
            0,
        )
        self.assertEqual(
            len(output.fairness_group_statistics),
            len({employee.fairness_group for employee in data.source.employees}),
        )
        self.assertEqual(
            {item.category for item in output.category_statistics},
            {"A", "B", "PART_TIME"},
        )
        primitive = output.to_dict()
        self.assertEqual(primitive["status"], "OPTIMAL")
        self.assertIsInstance(primitive["monthly_schedule"]["rows"], list)

    def test_multiple_role_positions_exist_only_in_stably_sorted_output_rows(self) -> None:
        day = "2024-10-01"
        payload = synthetic_schedule_input(
            start_date=day,
            end_date=day,
            roles=["assistant"],
            employees=[
                {
                    "employee_id": employee_id,
                    "name": name,
                    "employment_type": "full_time",
                    "full_time_class": "A",
                    "roles": ["assistant"],
                    "fairness_group": f"A_{employee_id}",
                    "shift_mode": "EXACT",
                    "required_shifts": 1,
                }
                for employee_id, name in (("E002", "乙"), ("E001", "甲"))
            ],
            positive_demands={(day, "morning", "assistant"): 2},
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        output = finalize_schedule_output(data, result)
        rows = [
            row
            for row in output.monthly_schedule.rows
            if row.period is Period.MORNING and row.role == "assistant"
        ]

        self.assertEqual(
            [row.label for row in rows],
            ["morning / assistant 1", "morning / assistant 2"],
        )
        self.assertEqual([row.cells[0].employee_id for row in rows], ["E001", "E002"])
        self.assertEqual([row.cells[0].name for row in rows], ["甲", "乙"])
        self.assertTrue(
            all(len(key) == 4 for key in data.allowed_assignments)
        )  # No numbered vacancy dimension in the model.

    def test_zero_denominators_are_reported_as_na(self) -> None:
        day = "2024-10-01"
        payload = synthetic_schedule_input(
            start_date=day,
            end_date=day,
            roles=["assistant"],
            employees=[
                {
                    "employee_id": "PT",
                    "name": "兼職",
                    "employment_type": "part_time",
                    "full_time_class": None,
                    "roles": ["assistant"],
                    "fairness_group": "PT_ONLY",
                    "shift_mode": "RANGE",
                    "min_shifts": 0,
                    "max_shifts": 1,
                    "available_slots": [],
                }
            ],
            positive_demands={},
        )
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        output = finalize_schedule_output(data, result)
        stats = output.individual_statistics[0]

        self.assertEqual(output.status, FeasibilityStatus.OPTIMAL)
        self.assertEqual(stats.ratios["part_time_usage"], RatioValue.of(0, 0))
        self.assertIsNone(stats.ratios["part_time_usage"].value)
        self.assertEqual(stats.ratios["part_time_usage"].display, "N/A")
        self.assertEqual(stats.ratios["single_shift_days"].display, "N/A")

    def test_table_marks_zero_demand_and_closed_dates_without_assignments(self) -> None:
        payload = minimal_valid_input()
        payload["period"]["end_date"] = "2024-10-02"
        payload["period"]["closed_dates"] = ["2024-10-02"]
        data = validate_and_normalize(payload)
        result = solve_lexicographic(data)
        output = finalize_schedule_output(data, result)
        evening_reception = next(
            row
            for row in output.monthly_schedule.rows
            if row.period is Period.EVENING and row.role == "reception"
        )

        self.assertEqual(evening_reception.cells[0].kind, ScheduleCellKind.ZERO_DEMAND)
        self.assertEqual(evening_reception.cells[0].display, "—")
        self.assertEqual(evening_reception.cells[1].kind, ScheduleCellKind.CLOSED)
        self.assertEqual(evening_reception.cells[1].display, "休診")


if __name__ == "__main__":
    unittest.main()
