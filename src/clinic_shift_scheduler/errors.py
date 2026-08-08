"""Structured INPUT_INVALID errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One actionable validation failure."""

    code: str
    path: str
    message: str


class InputValidationError(ValueError):
    """Raised when input must be reported as INPUT_INVALID."""

    status = "INPUT_INVALID"

    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("InputValidationError requires at least one issue")
        summary = "; ".join(
            f"{issue.path}: {issue.message}" for issue in self.issues
        )
        super().__init__(f"{self.status}: {summary}")

