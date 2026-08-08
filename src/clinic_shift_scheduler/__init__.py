"""Clinic shift scheduler data contracts.

Phase one intentionally exposes only input parsing, validation, and
normalization. Solver and output APIs will be introduced in later phases.
"""

from .errors import InputValidationError, ValidationIssue
from .models import NormalizedScheduleInput, ScheduleInput
from .validation import validate_and_normalize

__all__ = [
    "InputValidationError",
    "NormalizedScheduleInput",
    "ScheduleInput",
    "ValidationIssue",
    "validate_and_normalize",
]

