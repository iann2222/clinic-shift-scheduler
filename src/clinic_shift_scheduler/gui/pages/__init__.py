"""Input workflow pages for the desktop editor."""

from .availability_page import AvailabilityPage
from .date_override_page import DateOverridePage
from .employee_page import EmployeePage
from .month_clinic_page import MonthClinicPage
from .review_save_page import ReviewSavePage
from .weekly_demand_page import WeeklyDemandPage

__all__ = [
    "AvailabilityPage",
    "DateOverridePage",
    "EmployeePage",
    "MonthClinicPage",
    "ReviewSavePage",
    "WeeklyDemandPage",
]
