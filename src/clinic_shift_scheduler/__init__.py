"""Clinic scheduler data contracts, feasibility, and optimization APIs.

Later optimization objectives and formal output APIs remain future phases.
"""

from .authoring import (
    WEEKLY_AUTHORING_VERSION,
    expand_weekly_template,
    validate_and_normalize_weekly,
)
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
from .optimization import (
    ConstantProof,
    FairnessMetric,
    LexicographicResult,
    LexicographicSolverConfig,
    ObjectiveDirection,
    OptimizationStage,
    OptimizationStageResult,
    OptimizationStageStatus,
    OptimizationModel,
    build_optimization_model,
    build_phase_four_model,
    solve_lexicographic,
)
from .precheck import (
    PrecheckDiagnostic,
    PrecheckDiagnosticCode,
    PrecheckResult,
    PrecheckStatus,
    run_prechecks,
)
from .validation import validate_and_normalize

__all__ = [
    "Assignment",
    "ConstantProof",
    "DailyPattern",
    "FeasibilityResult",
    "FeasibilitySolverConfig",
    "FeasibilityStatus",
    "FairnessMetric",
    "InputValidationError",
    "LexicographicResult",
    "LexicographicSolverConfig",
    "NormalizedScheduleInput",
    "ObjectiveDirection",
    "OptimizationStage",
    "OptimizationStageResult",
    "OptimizationStageStatus",
    "OptimizationModel",
    "PrecheckDiagnostic",
    "PrecheckDiagnosticCode",
    "PrecheckResult",
    "PrecheckStatus",
    "ScheduleInput",
    "ValidationIssue",
    "WEEKLY_AUTHORING_VERSION",
    "build_feasibility_model",
    "build_optimization_model",
    "build_phase_four_model",
    "expand_weekly_template",
    "run_prechecks",
    "solve_feasibility",
    "solve_lexicographic",
    "validate_and_normalize",
    "validate_and_normalize_weekly",
]
