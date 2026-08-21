from __future__ import annotations

import unittest
from datetime import date

from clinic_shift_scheduler import (
    FeasibilityStatus,
    PrecheckDiagnosticCode,
    PrecheckStatus,
    build_feasibility_model,
    run_prechecks,
    solve_feasibility,
    validate_and_normalize,
)
from clinic_shift_scheduler.enums import Period

from tests.fixtures import synthetic_schedule_input


def full_time_employee(
    employee_id: str,
    *,
    roles: list[str] | None = None,
    full_time_class: str = "B",
    shift_mode: str = "RANGE",
    required_shifts: int | None = None,
    min_shifts: int = 0,
    max_shifts: int = 99,
    available_slots: list[dict] | None = None,
) -> dict:
    employee = {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "full_time",
        "full_time_class": full_time_class,
        "roles": roles or ["assistant"],
        "fairness_group": f"{full_time_class}_{employee_id}",
        "shift_mode": shift_mode,
    }
    if shift_mode == "EXACT":
        employee["required_shifts"] = required_shifts
    elif shift_mode == "TARGET":
        employee["target_shifts"] = required_shifts
    else:
        employee["min_shifts"] = min_shifts
        employee["max_shifts"] = max_shifts
    if available_slots is not None:
        employee["available_slots"] = available_slots
    return employee


def part_time_employee(
    employee_id: str,
    *,
    required_shifts: int | None = None,
    target_shifts: int | None = None,
    available_slots: list[dict] | None = None,
) -> dict:
    employee = {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "part_time",
        "full_time_class": None,
        "roles": ["assistant"],
        "fairness_group": f"PT_{employee_id}",
    }
    if target_shifts is not None:
        employee["shift_mode"] = "TARGET"
        employee["target_shifts"] = target_shifts
    else:
        employee["shift_mode"] = "EXACT"
        employee["required_shifts"] = required_shifts
    if available_slots is not None:
        employee["available_slots"] = available_slots
    return employee


def slot(day: str, period: str, roles: list[str] | None = None) -> dict:
    value = {"date": day, "period": period}
    if roles is not None:
        value["roles"] = roles
    return value


class AvailabilityIntegrationTests(unittest.TestCase):
    def test_full_time_is_available_by_default(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "FT001", shift_mode="EXACT", required_shifts=1
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )

        normalized = validate_and_normalize(payload)
        key = ("FT001", date(2024, 10, 1), Period.MORNING, "assistant")

        self.assertIn(key, normalized.allowed_assignments)
        self.assertIn(key, build_feasibility_model(normalized).x)
        self.assertEqual(
            solve_feasibility(normalized).status,
            FeasibilityStatus.FEASIBLE,
        )

    def test_part_time_explicit_availability_reaches_model(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                part_time_employee(
                    "PT001",
                    required_shifts=1,
                    available_slots=[
                        slot("2024-10-01", "morning", ["assistant"])
                    ],
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )

        normalized = validate_and_normalize(payload)
        result = solve_feasibility(normalized)

        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.assignments[0].employee_id, "PT001")

    def test_part_time_has_no_implicit_availability(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[part_time_employee("PT001", required_shifts=1)],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )

        normalized = validate_and_normalize(payload)
        result = solve_feasibility(normalized)

        self.assertFalse(normalized.allowed_assignments)
        self.assertEqual(result.status, FeasibilityStatus.PRECHECK_INFEASIBLE)
        self.assertEqual(result.raw_solver_status, "NOT_RUN")
        self.assertIsNotNone(result.precheck)
        self.assertTrue(result.precheck.is_infeasible)

    def test_unavailable_overrides_part_time_explicit_availability(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                part_time_employee(
                    "PT001",
                    required_shifts=1,
                    available_slots=[slot("2024-10-01", "morning")],
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )
        payload["unavailable_slots"] = [
            {
                "employee_id": "PT001",
                "date": "2024-10-01",
                "period": "morning",
            }
        ]

        normalized = validate_and_normalize(payload)

        self.assertFalse(normalized.allowed_assignments)
        self.assertEqual(
            solve_feasibility(normalized).status,
            FeasibilityStatus.PRECHECK_INFEASIBLE,
        )

    def test_partial_leave_overrides_full_time_default_availability(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "FT001", shift_mode="EXACT", required_shifts=1
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )
        payload["leave_requests"] = [
            {
                "employee_id": "FT001",
                "date": "2024-10-01",
                "all_day": False,
                "period": "morning",
            }
        ]

        normalized = validate_and_normalize(payload)

        self.assertFalse(normalized.allowed_assignments)
        self.assertEqual(
            solve_feasibility(normalized).status,
            FeasibilityStatus.PRECHECK_INFEASIBLE,
        )

    def test_all_day_leave_expands_to_all_periods_and_reaches_model(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "ON_LEAVE", shift_mode="EXACT", required_shifts=0
                ),
                full_time_employee(
                    "COVER", shift_mode="EXACT", required_shifts=3
                ),
            ],
            positive_demands={
                ("2024-10-01", period, "assistant"): 1
                for period in ("morning", "afternoon", "evening")
            },
        )
        payload["leave_requests"] = [
            {
                "employee_id": "ON_LEAVE",
                "date": "2024-10-01",
                "all_day": True,
            }
        ]

        normalized = validate_and_normalize(payload)
        result = solve_feasibility(normalized)

        expected_unavailable = {
            ("ON_LEAVE", date(2024, 10, 1), period) for period in Period
        }
        self.assertTrue(expected_unavailable <= normalized.unavailable_periods)
        self.assertFalse(
            any(key[0] == "ON_LEAVE" for key in normalized.allowed_assignments)
        )
        self.assertEqual(result.status, FeasibilityStatus.FEASIBLE)
        self.assertEqual({item.employee_id for item in result.assignments}, {"COVER"})


class PrecheckTests(unittest.TestCase):
    def test_total_capacity_shortage_accounts_for_class_a_daily_limit(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "A001",
                    full_time_class="A",
                    shift_mode="RANGE",
                    min_shifts=0,
                    max_shifts=3,
                )
            ],
            positive_demands={
                ("2024-10-01", period, "assistant"): 1
                for period in ("morning", "afternoon", "evening")
            },
        )

        result = run_prechecks(validate_and_normalize(payload))

        self.assertEqual(result.status, PrecheckStatus.PRECHECK_INFEASIBLE)
        self.assertEqual(result.total_demand, 3)
        self.assertEqual(result.total_capacity, 2)
        self.assertIn(
            PrecheckDiagnosticCode.TOTAL_CAPACITY_SHORTAGE,
            {item.code for item in result.diagnostics},
        )

    def test_employee_hard_minimum_reports_employee_and_capacity(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "LIMITED",
                    shift_mode="EXACT",
                    required_shifts=2,
                    available_slots=[slot("2024-10-01", "morning")],
                ),
                full_time_employee("BACKUP"),
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
                ("2024-10-01", "afternoon", "assistant"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code
            is PrecheckDiagnosticCode.EMPLOYEE_HARD_MINIMUM_EXCEEDS_CAPACITY
        )

        self.assertEqual(diagnostic.employee_id, "LIMITED")
        self.assertEqual((diagnostic.required, diagnostic.available), (2, 1))

    def test_b_class_morning_evening_only_capacity_is_one(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "B001",
                    shift_mode="EXACT",
                    required_shifts=2,
                    available_slots=[
                        slot("2024-10-01", "morning"),
                        slot("2024-10-01", "evening"),
                    ],
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
                ("2024-10-01", "evening", "assistant"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code
            is PrecheckDiagnosticCode.EMPLOYEE_HARD_MINIMUM_EXCEEDS_CAPACITY
        )

        self.assertEqual(result.employee_capacities["B001"], 1)
        self.assertEqual((diagnostic.required, diagnostic.available), (2, 1))

    def test_total_hard_minimum_cannot_exceed_total_demand(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    employee_id,
                    shift_mode="EXACT",
                    required_shifts=1,
                )
                for employee_id in ("E1", "E2")
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code
            is PrecheckDiagnosticCode.HARD_MINIMUM_EXCEEDS_TOTAL_DEMAND
        )

        self.assertEqual((diagnostic.required, diagnostic.available), (2, 1))

    def test_role_capacity_shortage_is_reported_across_dates(self) -> None:
        employees = [
            full_time_employee(
                "RECEPTION",
                roles=["reception"],
                max_shifts=1,
            ),
            full_time_employee("ASSISTANT1"),
            full_time_employee("ASSISTANT2"),
        ]
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-02",
            roles=["reception", "assistant"],
            employees=employees,
            positive_demands={
                (day, "morning", role): 1
                for day in ("2024-10-01", "2024-10-02")
                for role in ("reception", "assistant")
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code is PrecheckDiagnosticCode.ROLE_CAPACITY_SHORTAGE
        )

        self.assertEqual(diagnostic.role, "reception")
        self.assertEqual((diagnostic.required, diagnostic.available), (2, 1))

    def test_slot_matching_detects_multi_role_employee_competition(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["reception", "assistant"],
            employees=[
                full_time_employee(
                    "MULTI", roles=["reception", "assistant"], max_shifts=2
                ),
                full_time_employee(
                    "AFTERNOON_ONLY",
                    available_slots=[slot("2024-10-01", "afternoon")],
                    max_shifts=1,
                ),
            ],
            positive_demands={
                ("2024-10-01", "morning", "reception"): 1,
                ("2024-10-01", "morning", "assistant"): 1,
                ("2024-10-01", "afternoon", "assistant"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code is PrecheckDiagnosticCode.SLOT_MATCHING_SHORTAGE
        )

        self.assertEqual(diagnostic.date, date(2024, 10, 1))
        self.assertEqual(diagnostic.period, Period.MORNING)
        self.assertEqual((diagnostic.required, diagnostic.available), (2, 1))
        self.assertEqual(diagnostic.eligible_employee_ids, ("MULTI",))
        self.assertEqual(diagnostic.related_roles, ("assistant", "reception"))

    def test_slot_role_shortage_identifies_role_and_slot(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["reception", "assistant"],
            employees=[full_time_employee("ASSISTANT")],
            positive_demands={
                ("2024-10-01", "evening", "reception"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code is PrecheckDiagnosticCode.SLOT_ROLE_SHORTAGE
        )

        self.assertEqual(diagnostic.date, date(2024, 10, 1))
        self.assertEqual(diagnostic.period, Period.EVENING)
        self.assertEqual(diagnostic.role, "reception")
        self.assertEqual(diagnostic.shortage, 1)

    def test_zero_hard_maximum_is_not_counted_as_slot_supply(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "ZERO",
                    shift_mode="EXACT",
                    required_shifts=0,
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))
        diagnostic = next(
            item
            for item in result.diagnostics
            if item.code is PrecheckDiagnosticCode.SLOT_ROLE_SHORTAGE
        )

        self.assertEqual(diagnostic.eligible_employee_ids, ())
        self.assertEqual(diagnostic.available, 0)

    def test_target_without_hard_minimum_does_not_fail_capacity_precheck(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[
                part_time_employee(
                    "TARGET",
                    target_shifts=99,
                    available_slots=[slot("2024-10-01", "morning")],
                )
            ],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
            },
        )

        result = run_prechecks(validate_and_normalize(payload))

        self.assertEqual(result.status, PrecheckStatus.CONTINUE)

    def test_continue_does_not_claim_the_complete_model_is_feasible(self) -> None:
        day_one = [slot("2024-10-01", "morning")]
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-03",
            roles=["assistant"],
            employees=[
                full_time_employee(
                    "E1",
                    shift_mode="EXACT",
                    required_shifts=1,
                    available_slots=day_one,
                ),
                full_time_employee(
                    "E2",
                    shift_mode="EXACT",
                    required_shifts=1,
                    available_slots=day_one,
                ),
                full_time_employee(
                    "E3",
                    shift_mode="EXACT",
                    required_shifts=1,
                    available_slots=[
                        slot("2024-10-02", "morning"),
                        slot("2024-10-03", "morning"),
                    ],
                ),
            ],
            positive_demands={
                (day, "morning", "assistant"): 1
                for day in ("2024-10-01", "2024-10-02", "2024-10-03")
            },
        )

        normalized = validate_and_normalize(payload)
        precheck = run_prechecks(normalized)
        solved = solve_feasibility(normalized)

        self.assertEqual(precheck.status, PrecheckStatus.CONTINUE)
        self.assertEqual(precheck.diagnostics, ())
        self.assertEqual(solved.status, FeasibilityStatus.INFEASIBLE)
        self.assertEqual(solved.precheck, precheck)


if __name__ == "__main__":
    unittest.main()
