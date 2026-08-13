"""Lazy public API for scheduling and user-document tooling.

Importing the package itself does not load OR-Tools or output dependencies.
Heavy modules are imported only when their public symbols are requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {}


def _exports(module: str, *names: str) -> None:
    _EXPORTS.update({name: (module, name) for name in names})


_exports("app_config", "APP_CONFIG_VERSION", "CandidateDiagnosticSettings", "DiagnosticTimeSettings", "SchedulerAppConfig", "SchedulerConfigDocument", "load_scheduler_config", "load_scheduler_config_document", "parse_scheduler_config", "parse_scheduler_config_document", "write_scheduler_config_document")
_exports("authoring", "WEEKLY_AUTHORING_VERSION", "expand_weekly_template", "load_weekly_authoring_document", "parse_weekly_authoring", "validate_and_normalize_weekly", "write_weekly_authoring_document")
_exports("authoring_models", "AuthoringAvailableSlot", "AuthoringEmployee", "AuthoringLeaveRequest", "AuthoringUnavailableSlot", "DateOverrideRule", "StaffingPlan", "WeeklyAuthoringDocument", "WeeklyDemandRule", "WeeklyPeriod")
_exports("application", "ScheduleApplicationCallbacks", "ScheduleApplicationError", "ScheduleApplicationFailureKind", "ScheduleApplicationRequest", "request_from_app_config", "run_schedule_application")
_exports("authoring_application", "AuthoringApplication", "AuthoringFileExistsError", "AuthoringSession", "AuthoringValidationResult", "default_month_filename")
_exports("config_application", "ConfigApplication", "ConfigSession", "ConfigValidationResult")
_exports("application_contracts", "CandidateExportConfig")
_exports("class_preferences", "ClassPreferenceDefinition", "ClassPreferenceMetric", "PreferenceDirection", "PreferenceRank", "class_opportunity_days")
_exports("optimization_policy", "CLASS_PREFERENCES", "FORMAL_OBJECTIVE_STAGES", "FORMAL_STAGE_POLICIES", "FORMAL_STAGE_SEQUENCE", "FormalStagePolicy")
_exports("errors", "InputValidationError", "ValidationIssue")
_exports("events", "CancellationToken", "DiagnosticIssue", "DiagnosticSeverity", "ExecutionPhase", "OperationCancelledError", "ProgressCallback", "ProgressEvent", "ProgressEventKind")
_exports("exporters", "DEFAULT_OUTPUT_DIRECTORY", "RESULT_CONTRACT_NAME", "RESULT_CONTRACT_VERSION", "WORKSHEET_NAMES", "ExportFileExistsError", "FormalExportError", "OutputPaths", "build_output_paths", "build_result_document", "build_workbook", "export_result_excel", "export_result_json", "export_schedule_pdf_from_excel")
_exports("solver_contracts", "Assignment", "FeasibilityResult", "FeasibilitySolverConfig", "FeasibilityStatus", "LexicographicResult")
_exports("daily_patterns", "DailyPattern")
_exports("feasibility", "build_feasibility_model", "solve_feasibility")
_exports("models", "NormalizedScheduleInput", "ScheduleInput")
_exports("optimization_contracts", "ClassPatternLockResult", "ConstantProof", "EquivalentSolutionDiagnosticConfig", "EquivalentSolutionDiagnosticResult", "EquivalentSolutionDiagnosticStatus", "FairnessMetric", "LexicographicSolverConfig", "ObjectiveDirection", "OptimizationStage", "OptimizationStageResult", "OptimizationStageStatus", "PreferenceBenchmarkResult")
_exports("optimization", "OptimizationModel", "build_optimization_model", "diagnose_equivalent_solutions", "solve_lexicographic")
_exports("output", "CategoryStatistics", "ClassPreferenceStatistics", "ExecutionTiming", "FairnessGroupStatistics", "FormalScheduleOutput", "IndividualStatistics", "MonthlyScheduleRow", "MonthlyScheduleTable", "OverallStatistics", "RatioValue", "ScheduleCell", "ScheduleCellKind", "finalize_schedule_output", "to_primitive")
_exports("precheck", "PrecheckDiagnostic", "PrecheckDiagnosticCode", "PrecheckResult", "PrecheckStatus", "run_prechecks")
_exports("result_metrics", "EmployeeResultMetrics", "RecomputedScheduleMetrics", "recompute_schedule_metrics")
_exports("result_validation", "ResultValidationIssue", "ResultValidationStatus", "ValidationReport", "validate_schedule_result")
_exports("runner", "CandidateScheduleExport", "ScheduleRunError", "ScheduleRunResult", "run_schedule_file")
_exports("validation", "validate_and_normalize")

__all__ = [
    "APP_CONFIG_VERSION",
    "Assignment",
    "AuthoringApplication",
    "AuthoringAvailableSlot",
    "AuthoringEmployee",
    "AuthoringLeaveRequest",
    "AuthoringUnavailableSlot",
    "AuthoringFileExistsError",
    "AuthoringSession",
    "AuthoringValidationResult",
    "CandidateDiagnosticSettings",
    "CandidateExportConfig",
    "CandidateScheduleExport",
    "CancellationToken",
    "ClassPatternLockResult",
    "ConstantProof",
    "CategoryStatistics",
    "ClassPreferenceDefinition",
    "ClassPreferenceMetric",
    "ClassPreferenceStatistics",
    "CLASS_PREFERENCES",
    "ConfigApplication",
    "ConfigSession",
    "ConfigValidationResult",
    "DailyPattern",
    "DiagnosticTimeSettings",
    "DiagnosticIssue",
    "DiagnosticSeverity",
    "DateOverrideRule",
    "DEFAULT_OUTPUT_DIRECTORY",
    "ExportFileExistsError",
    "ExecutionTiming",
    "ExecutionPhase",
    "EquivalentSolutionDiagnosticConfig",
    "EquivalentSolutionDiagnosticResult",
    "EquivalentSolutionDiagnosticStatus",
    "FeasibilityResult",
    "FeasibilitySolverConfig",
    "FeasibilityStatus",
    "FairnessMetric",
    "FairnessGroupStatistics",
    "FormalExportError",
    "InputValidationError",
    "IndividualStatistics",
    "LexicographicResult",
    "LexicographicSolverConfig",
    "NormalizedScheduleInput",
    "ObjectiveDirection",
    "OperationCancelledError",
    "OptimizationStage",
    "OptimizationStageResult",
    "OptimizationStageStatus",
    "OutputPaths",
    "OverallStatistics",
    "OptimizationModel",
    "PreferenceBenchmarkResult",
    "PreferenceDirection",
    "PreferenceRank",
    "ProgressEvent",
    "ProgressEventKind",
    "ProgressCallback",
    "PrecheckDiagnostic",
    "PrecheckDiagnosticCode",
    "PrecheckResult",
    "PrecheckStatus",
    "RatioValue",
    "RecomputedScheduleMetrics",
    "RESULT_CONTRACT_NAME",
    "RESULT_CONTRACT_VERSION",
    "WORKSHEET_NAMES",
    "ResultValidationIssue",
    "ResultValidationStatus",
    "ScheduleCell",
    "ScheduleCellKind",
    "ScheduleApplicationCallbacks",
    "ScheduleApplicationError",
    "ScheduleApplicationFailureKind",
    "ScheduleApplicationRequest",
    "ScheduleInput",
    "SchedulerAppConfig",
    "SchedulerConfigDocument",
    "ScheduleRunError",
    "ScheduleRunResult",
    "FormalScheduleOutput",
    "FormalStagePolicy",
    "FORMAL_OBJECTIVE_STAGES",
    "FORMAL_STAGE_POLICIES",
    "FORMAL_STAGE_SEQUENCE",
    "MonthlyScheduleRow",
    "MonthlyScheduleTable",
    "EmployeeResultMetrics",
    "ValidationReport",
    "ValidationIssue",
    "WEEKLY_AUTHORING_VERSION",
    "WeeklyAuthoringDocument",
    "WeeklyDemandRule",
    "WeeklyPeriod",
    "StaffingPlan",
    "build_feasibility_model",
    "class_opportunity_days",
    "build_optimization_model",
    "build_output_paths",
    "diagnose_equivalent_solutions",
    "default_month_filename",
    "build_result_document",
    "build_workbook",
    "expand_weekly_template",
    "export_result_json",
    "export_result_excel",
    "export_schedule_pdf_from_excel",
    "finalize_schedule_output",
    "recompute_schedule_metrics",
    "run_prechecks",
    "request_from_app_config",
    "run_schedule_application",
    "run_schedule_file",
    "load_scheduler_config",
    "load_scheduler_config_document",
    "load_weekly_authoring_document",
    "parse_scheduler_config",
    "parse_scheduler_config_document",
    "parse_weekly_authoring",
    "solve_feasibility",
    "solve_lexicographic",
    "validate_and_normalize",
    "validate_and_normalize_weekly",
    "write_scheduler_config_document",
    "write_weekly_authoring_document",
    "validate_schedule_result",
    "to_primitive",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    value = getattr(import_module(f".{module_name}", __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
