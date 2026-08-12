from __future__ import annotations

import unittest

from clinic_shift_scheduler.gui.field_location import resolve_field_location
from clinic_shift_scheduler.gui.navigation import PageId


class GuiFieldLocationTests(unittest.TestCase):
    def test_collection_level_errors_route_to_their_input_pages(self) -> None:
        self.assertEqual(
            resolve_field_location("$.employees").page_id,
            PageId.EMPLOYEE,
        )
        self.assertEqual(
            resolve_field_location("$.weekly_demands").page_id,
            PageId.WEEKLY_DEMAND,
        )
        self.assertEqual(
            resolve_field_location("$.leave_requests").page_id,
            PageId.AVAILABILITY,
        )

    def test_employee_field_resolves_to_exact_employee_and_field(self) -> None:
        location = resolve_field_location("$.employees[3].target_shifts")

        self.assertEqual(location.page_id, PageId.EMPLOYEE)
        self.assertEqual(location.employee_index, 3)
        self.assertEqual(location.field, "target_shifts")

    def test_available_slot_resolves_to_availability_page(self) -> None:
        location = resolve_field_location(
            "$.employees[4].available_slots[7].roles"
        )

        self.assertEqual(location.page_id, PageId.AVAILABILITY)
        self.assertEqual(location.employee_index, 4)
        self.assertEqual(location.available_slot_index, 7)
        self.assertEqual(location.field, "roles")

    def test_weekly_staffing_resolves_period_and_dynamic_role(self) -> None:
        location = resolve_field_location(
            "$.weekly_demands[2].staffing.evening.nursing"
        )

        self.assertEqual(location.page_id, PageId.WEEKLY_DEMAND)
        self.assertEqual(location.weekly_index, 2)
        self.assertEqual(location.period, "evening")
        self.assertEqual(location.role, "nursing")

    def test_date_override_and_leave_records_resolve(self) -> None:
        override = resolve_field_location(
            "$.date_overrides[1].staffing.morning.reception"
        )
        leave = resolve_field_location("$.leave_requests[8].date")

        self.assertEqual(override.page_id, PageId.DATE_OVERRIDE)
        self.assertEqual(override.override_index, 1)
        self.assertEqual(override.period, "morning")
        self.assertEqual(override.role, "reception")
        self.assertEqual(leave.page_id, PageId.AVAILABILITY)
        self.assertEqual(leave.record_type, "leave_requests")
        self.assertEqual(leave.record_index, 8)


if __name__ == "__main__":
    unittest.main()
