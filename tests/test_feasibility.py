from __future__ import annotations

import unittest
from collections import Counter, defaultdict
from datetime import date

from clinic_shift_scheduler import (
    DailyPattern,
    FeasibilitySolverConfig,
    FeasibilityStatus,
    build_feasibility_model,
    solve_feasibility,
    validate_and_normalize,
)
from clinic_shift_scheduler.feasibility import PATTERN_PERIODS

from tests.fixtures import (
    clone_fixture,
    single_employee_pattern_input,
    synthetic_schedule_input,
)


NO_PRECHECK = FeasibilitySolverConfig(enable_precheck=False)


class FeasibilityTests(unittest.TestCase):
    def solve_pattern(
        self,
        pattern: DailyPattern,
        *,
        employment_type: str,
        full_time_class: str | None,
    ):
        payload = single_employee_pattern_input(
            employment_type=employment_type,
            full_time_class=full_time_class,
            worked_periods={period.value for period in PATTERN_PERIODS[pattern]},
        )
        return solve_feasibility(validate_and_normalize(payload), NO_PRECHECK)

    def test_class_a_allows_seven_patterns_and_forbids_triple(self) -> None:
        for pattern in DailyPattern:
            with self.subTest(pattern=pattern):
                result = self.solve_pattern(
                    pattern,
                    employment_type="full_time",
                    full_time_class="A",
                )
                expected = (
                    FeasibilityStatus.INFEASIBLE
                    if pattern is DailyPattern.TRIPLE
                    else FeasibilityStatus.FEASIBLE
                )
                self.assertEqual(result.status, expected)
                if result.is_feasible:
                    self.assertEqual(result.daily_patterns[("E001", date(2024, 10, 1))], pattern)

    def test_class_b_allows_seven_patterns_and_forbids_morning_evening(self) -> None:
        for pattern in DailyPattern:
            with self.subTest(pattern=pattern):
                result = self.solve_pattern(
                    pattern,
                    employment_type="full_time",
                    full_time_class="B",
                )
                expected = (
                    FeasibilityStatus.INFEASIBLE
                    if pattern is DailyPattern.MORNING_EVENING
                    else FeasibilityStatus.FEASIBLE
                )
                self.assertEqual(result.status, expected)
                if result.is_feasible:
                    self.assertEqual(result.daily_patterns[("E001", date(2024, 10, 1))], pattern)

    def test_class_b_has_at_most_one_single_shift_day_per_schedule(self) -> None:
        days = ("2024-10-01", "2024-10-02")
        employee = {
            "employee_id": "B",
            "name": "B",
            "employment_type": "full_time",
            "full_time_class": "B",
            "roles": ["assistant"],
            "fairness_group": "B_ONLY",
            "shift_mode": "EXACT",
            "required_shifts": 2,
        }
        two_singles = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[employee],
            positive_demands={
                (day, "morning", "assistant"): 1 for day in days
            },
        )
        self.assertEqual(
            solve_feasibility(
                validate_and_normalize(two_singles), NO_PRECHECK
            ).status,
            FeasibilityStatus.INFEASIBLE,
        )

        one_single = synthetic_schedule_input(
            start_date=days[0],
            end_date=days[-1],
            roles=["assistant"],
            employees=[{**employee, "required_shifts": 3}],
            positive_demands={
                (days[0], "morning", "assistant"): 1,
                (days[0], "afternoon", "assistant"): 1,
                (days[1], "morning", "assistant"): 1,
            },
        )
        self.assertEqual(
            solve_feasibility(
                validate_and_normalize(one_single), NO_PRECHECK
            ).status,
            FeasibilityStatus.FEASIBLE,
        )

    def test_part_time_allows_seven_patterns_and_forbids_triple(self) -> None:
        for pattern in DailyPattern:
            with self.subTest(pattern=pattern):
                result = self.solve_pattern(
                    pattern,
                    employment_type="part_time",
                    full_time_class=None,
                )
                expected = (
                    FeasibilityStatus.INFEASIBLE
                    if pattern is DailyPattern.TRIPLE
                    else FeasibilityStatus.FEASIBLE
                )
                self.assertEqual(result.status, expected)
                if result.is_feasible:
                    self.assertEqual(result.daily_patterns[("E001", date(2024, 10, 1))], pattern)

    def test_feasible_result_exactly_covers_demand_with_qualified_people(self) -> None:
        normalized = validate_and_normalize(clone_fixture())
        built = build_feasibility_model(normalized)
        result = solve_feasibility(normalized, NO_PRECHECK)

        self.assertEqual(set(built.x), set(normalized.allowed_assignments))
        self.assertFalse(built.model.has_objective())
        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)

        coverage = Counter(
            (assignment.date, assignment.period, assignment.role)
            for assignment in result.assignments
        )
        self.assertEqual(dict(coverage), {key: count for key, count in normalized.demands.items() if count})

        simultaneous_roles: dict[tuple, int] = defaultdict(int)
        for assignment in result.assignments:
            employee = normalized.employees[assignment.employee_id]
            self.assertIn(assignment.role, employee.roles)
            self.assertIn(
                (
                    assignment.employee_id,
                    assignment.date,
                    assignment.period,
                    assignment.role,
                ),
                normalized.allowed_assignments,
            )
            simultaneous_roles[
                (assignment.employee_id, assignment.date, assignment.period)
            ] += 1
        self.assertTrue(all(count == 1 for count in simultaneous_roles.values()))

    def test_one_employee_cannot_cover_two_roles_in_the_same_period(self) -> None:
        payload = single_employee_pattern_input(
            employment_type="full_time",
            full_time_class="B",
            worked_periods={"morning"},
        )
        payload["roles"] = ["reception", "assistant"]
        payload["employees"][0]["roles"] = ["reception", "assistant"]
        payload["employees"][0]["required_shifts"] = 1
        payload["demands"] = [
            {
                "date": "2024-10-01",
                "period": period,
                "role": role,
                "count": int(period == "morning"),
            }
            for period in ("morning", "afternoon", "evening")
            for role in ("reception", "assistant")
        ]

        result = solve_feasibility(validate_and_normalize(payload), NO_PRECHECK)

        self.assertEqual(result.status, FeasibilityStatus.INFEASIBLE)

    def test_missing_qualified_person_makes_model_infeasible(self) -> None:
        payload = clone_fixture()
        payload["employees"][0]["roles"] = ["assistant"]

        result = solve_feasibility(validate_and_normalize(payload), NO_PRECHECK)

        self.assertEqual(result.status, FeasibilityStatus.INFEASIBLE)

    def test_exact_and_range_are_hard_total_shift_constraints(self) -> None:
        exact = single_employee_pattern_input(
            employment_type="full_time",
            full_time_class="B",
            worked_periods={"morning"},
        )
        exact["employees"][0]["required_shifts"] = 2
        self.assertEqual(
            solve_feasibility(validate_and_normalize(exact), NO_PRECHECK).status,
            FeasibilityStatus.INFEASIBLE,
        )

        ranged = single_employee_pattern_input(
            employment_type="full_time",
            full_time_class="B",
            worked_periods={"morning"},
        )
        employee = ranged["employees"][0]
        employee["shift_mode"] = "RANGE"
        del employee["required_shifts"]
        employee["min_shifts"] = 2
        employee["max_shifts"] = 3
        self.assertEqual(
            solve_feasibility(validate_and_normalize(ranged), NO_PRECHECK).status,
            FeasibilityStatus.INFEASIBLE,
        )

    def test_target_value_is_not_a_hard_constraint_but_explicit_min_is(self) -> None:
        target = single_employee_pattern_input(
            employment_type="full_time",
            full_time_class="B",
            worked_periods={"morning"},
        )
        employee = target["employees"][0]
        employee["shift_mode"] = "TARGET"
        del employee["required_shifts"]
        employee["target_shifts"] = 99

        result = solve_feasibility(validate_and_normalize(target), NO_PRECHECK)
        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)

        employee["min_shifts"] = 2
        result = solve_feasibility(validate_and_normalize(target), NO_PRECHECK)
        self.assertEqual(result.status, FeasibilityStatus.INFEASIBLE)


if __name__ == "__main__":
    unittest.main()
