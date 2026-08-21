from __future__ import annotations

import unittest
from datetime import date

from clinic_shift_scheduler import InputValidationError, validate_and_normalize
from clinic_shift_scheduler.enums import Period, ShiftMode

from tests.fixtures import clone_fixture


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, payload: dict, code: str) -> InputValidationError:
        with self.assertRaises(InputValidationError) as caught:
            validate_and_normalize(payload)
        self.assertEqual(caught.exception.status, "INPUT_INVALID")
        self.assertIn(code, {issue.code for issue in caught.exception.issues})
        return caught.exception

    def test_valid_input_is_normalized_to_immutable_domain_data(self) -> None:
        normalized = validate_and_normalize(clone_fixture())

        self.assertEqual(normalized.source.schema_version, "v1")
        self.assertEqual(normalized.dates, (date(2024, 10, 1),))
        self.assertEqual(normalized.open_dates, (date(2024, 10, 1),))
        self.assertEqual(normalized.employees["FT002"].shift_mode, ShiftMode.RANGE)
        self.assertEqual(
            normalized.demands[(date(2024, 10, 1), Period.EVENING, "reception")],
            0,
        )

        # Full-time defaults to all open, qualified, positive-demand assignments.
        self.assertIn(
            ("FT001", date(2024, 10, 1), Period.AFTERNOON, "reception"),
            normalized.allowed_assignments,
        )
        self.assertNotIn(
            ("FT001", date(2024, 10, 1), Period.EVENING, "reception"),
            normalized.allowed_assignments,
        )
        # Part-time has no implicit availability beyond available_slots.
        self.assertIn(
            ("PT001", date(2024, 10, 1), Period.MORNING, "assistant"),
            normalized.allowed_assignments,
        )
        self.assertNotIn(
            ("PT001", date(2024, 10, 1), Period.AFTERNOON, "assistant"),
            normalized.allowed_assignments,
        )
        with self.assertRaises(TypeError):
            normalized.employees["NEW"] = normalized.employees["FT001"]  # type: ignore[index]

    def test_target_above_capacity_without_explicit_bounds_is_valid(self) -> None:
        payload = clone_fixture()
        employee = payload["employees"][2]
        employee["shift_mode"] = "TARGET"
        employee["target_shifts"] = 999
        del employee["min_shifts"]
        del employee["max_shifts"]

        normalized = validate_and_normalize(payload)

        employee = normalized.employees["PT001"]
        self.assertEqual(employee.target_shifts, 999)
        self.assertIsNone(employee.min_shifts)
        self.assertIsNone(employee.max_shifts)

    def test_target_conflicting_with_explicit_min_is_invalid(self) -> None:
        payload = clone_fixture()
        employee = payload["employees"][2]
        employee["shift_mode"] = "TARGET"
        employee["target_shifts"] = 5
        employee["min_shifts"] = 6
        del employee["max_shifts"]

        self.assert_invalid(payload, "target_outside_bounds")

    def test_target_conflicting_with_explicit_max_is_invalid(self) -> None:
        payload = clone_fixture()
        employee = payload["employees"][2]
        employee["shift_mode"] = "TARGET"
        employee["target_shifts"] = 5
        employee["max_shifts"] = 4
        del employee["min_shifts"]

        self.assert_invalid(payload, "target_outside_bounds")

    def test_shift_modes_reject_mixed_or_missing_fields(self) -> None:
        cases = []

        exact_with_target = clone_fixture()
        exact_with_target["employees"][0]["target_shifts"] = 2
        cases.append(exact_with_target)

        range_without_max = clone_fixture()
        del range_without_max["employees"][2]["max_shifts"]
        cases.append(range_without_max)

        target_with_required = clone_fixture()
        target_employee = target_with_required["employees"][2]
        target_employee["shift_mode"] = "TARGET"
        target_employee["target_shifts"] = 1
        target_employee["required_shifts"] = 1
        del target_employee["min_shifts"]
        del target_employee["max_shifts"]
        cases.append(target_with_required)

        for payload in cases:
            with self.subTest(payload=payload):
                self.assert_invalid(payload, "invalid_shift_fields")

    def test_full_time_target_is_not_supported_in_v1(self) -> None:
        payload = clone_fixture()
        employee = payload["employees"][1]
        employee["shift_mode"] = "TARGET"
        employee["target_shifts"] = 1
        del employee["min_shifts"]
        del employee["max_shifts"]

        self.assert_invalid(payload, "unsupported_full_time_target")

    def test_part_time_target_is_supported_in_v1(self) -> None:
        payload = clone_fixture()
        employee = payload["employees"][2]
        employee["shift_mode"] = "TARGET"
        employee["target_shifts"] = 1
        del employee["min_shifts"]
        del employee["max_shifts"]

        normalized = validate_and_normalize(payload)

        self.assertEqual(normalized.employees["PT001"].shift_mode, ShiftMode.TARGET)

    def test_missing_demand_is_not_treated_as_zero(self) -> None:
        payload = clone_fixture()
        payload["demands"].pop()

        self.assert_invalid(payload, "missing_demand")

    def test_explicit_zero_demand_is_valid(self) -> None:
        normalized = validate_and_normalize(clone_fixture())

        self.assertEqual(
            normalized.demands[(date(2024, 10, 1), Period.EVENING, "reception")],
            0,
        )

    def test_demand_on_closed_date_is_invalid(self) -> None:
        payload = clone_fixture()
        payload["period"]["closed_dates"] = ["2024-10-01"]

        self.assert_invalid(payload, "demand_on_closed_date")

    def test_conflicting_duplicate_demand_is_invalid(self) -> None:
        payload = clone_fixture()
        duplicate = dict(payload["demands"][0])
        duplicate["count"] = 2
        payload["demands"].append(duplicate)

        self.assert_invalid(payload, "conflicting_duplicate")

    def test_identical_duplicate_records_are_deduplicated(self) -> None:
        payload = clone_fixture()
        payload["demands"].append(dict(payload["demands"][0]))
        payload["unavailable_slots"] = [
            {"employee_id": "FT001", "date": "2024-10-01", "period": "morning"}
        ] * 2

        normalized = validate_and_normalize(payload)

        self.assertEqual(len(normalized.source.demands), 6)
        self.assertEqual(len(normalized.source.unavailable_slots), 1)

    def test_employee_ids_must_be_unique_even_when_names_may_repeat(self) -> None:
        duplicate_id = clone_fixture()
        duplicate_id["employees"][1]["employee_id"] = "FT001"
        self.assert_invalid(duplicate_id, "duplicate_employee_id")

        duplicate_name = clone_fixture()
        duplicate_name["employees"][1]["name"] = duplicate_name["employees"][0]["name"]
        validate_and_normalize(duplicate_name)

    def test_all_cross_references_use_known_employee_ids(self) -> None:
        payload = clone_fixture()
        payload["leave_requests"] = [
            {
                "employee_id": "UNKNOWN",
                "date": "2024-10-01",
                "all_day": True,
            }
        ]

        self.assert_invalid(payload, "unknown_employee_id")

    def test_fairness_group_cannot_mix_incompatible_types(self) -> None:
        payload = clone_fixture()
        payload["employees"][2]["fairness_group"] = "A_GENERAL"

        self.assert_invalid(payload, "incompatible_fairness_group")

    def test_periods_are_fixed_and_ordered_in_v1(self) -> None:
        payload = clone_fixture()
        payload["periods"] = ["afternoon", "morning", "evening"]

        self.assert_invalid(payload, "invalid_periods_v1")

    def test_leave_and_unavailable_override_availability(self) -> None:
        payload = clone_fixture()
        payload["unavailable_slots"] = [
            {"employee_id": "PT001", "date": "2024-10-01", "period": "morning"}
        ]
        payload["leave_requests"] = [
            {"employee_id": "FT001", "date": "2024-10-01", "all_day": True}
        ]

        normalized = validate_and_normalize(payload)

        self.assertFalse(any(key[0] == "PT001" for key in normalized.allowed_assignments))
        self.assertFalse(any(key[0] == "FT001" for key in normalized.allowed_assignments))
        self.assertEqual(
            {
                period
                for employee_id, day, period in normalized.unavailable_periods
                if employee_id == "FT001" and day == date(2024, 10, 1)
            },
            set(Period),
        )

    def test_explicit_full_time_availability_restricts_default(self) -> None:
        payload = clone_fixture()
        payload["employees"][0]["available_slots"] = [
            {"date": "2024-10-01", "period": "evening", "roles": ["assistant"]}
        ]

        normalized = validate_and_normalize(payload)

        ft_assignments = {item for item in normalized.allowed_assignments if item[0] == "FT001"}
        self.assertEqual(
            ft_assignments,
            {("FT001", date(2024, 10, 1), Period.EVENING, "assistant")},
        )

    def test_available_slot_role_must_be_known_and_qualified(self) -> None:
        payload = clone_fixture()
        payload["employees"][1]["available_slots"] = [
            {"date": "2024-10-01", "period": "morning", "roles": ["reception"]}
        ]

        self.assert_invalid(payload, "unqualified_available_role")

    def test_all_day_leave_forbids_period_and_partial_leave_requires_it(self) -> None:
        all_day_with_period = clone_fixture()
        all_day_with_period["leave_requests"] = [
            {
                "employee_id": "FT001",
                "date": "2024-10-01",
                "all_day": True,
                "period": "morning",
            }
        ]
        self.assert_invalid(all_day_with_period, "invalid_leave_period")

        partial_without_period = clone_fixture()
        partial_without_period["leave_requests"] = [
            {"employee_id": "FT001", "date": "2024-10-01", "all_day": False}
        ]
        self.assert_invalid(partial_without_period, "invalid_enum")

    def test_unknown_fields_are_rejected(self) -> None:
        payload = clone_fixture()
        payload["employees"][0]["daily_max_shifts"] = 2

        self.assert_invalid(payload, "unknown_field")


if __name__ == "__main__":
    unittest.main()
