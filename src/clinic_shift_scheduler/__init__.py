"""Clinic shift scheduler data contracts and hard-feasibility API.

Optimization and formal output APIs will be introduced in later phases.
"""

from .errors import InputValidationError, ValidationIssue
from .feasibility import (
    Assignment,
    DailyPattern,
    FeasibilityResult,
    FeasibilitySolverConfig,
    FeasibilityStatus,
    build_feasibility_model,
    solve_feasibility,
)
from .models import NormalizedScheduleInput, ScheduleInput
from .validation import validate_and_normalize

__all__ = [
    "InputValidationError",
    "Assignment",
    "DailyPattern",
    "FeasibilityResult",
    "FeasibilitySolverConfig",
    "FeasibilityStatus",
    "NormalizedScheduleInput",
    "ScheduleInput",
    "ValidationIssue",
    "build_feasibility_model",
    "solve_feasibility",
    "validate_and_normalize",
]
