"""Presentation-neutral diagnostics, progress events, and cancellation."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from collections.abc import Callable
from typing import Any, Mapping


class DiagnosticSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ExecutionPhase(StrEnum):
    INPUT = "INPUT"
    CONFIG = "CONFIG"
    NORMALIZATION = "NORMALIZATION"
    PRECHECK = "PRECHECK"
    OPTIMIZATION = "OPTIMIZATION"
    VALIDATION = "VALIDATION"
    OUTPUT = "OUTPUT"
    CANDIDATE_SEARCH = "CANDIDATE_SEARCH"
    APPLICATION = "APPLICATION"


class ProgressEventKind(StrEnum):
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    HEARTBEAT = "HEARTBEAT"
    INFORMATION = "INFORMATION"
    CANDIDATE_COUNT = "CANDIDATE_COUNT"


@dataclass(frozen=True, slots=True)
class DiagnosticIssue:
    code: str
    path: str
    message: str
    phase: ExecutionPhase = ExecutionPhase.INPUT
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    details: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "phase": self.phase.value,
            "severity": self.severity.value,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    phase: ExecutionPhase
    kind: ProgressEventKind
    message: str
    elapsed_seconds: float | None = None
    current: int | None = None
    total: int | None = None
    details: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


ProgressCallback = Callable[[ProgressEvent], None]


class CancellationToken:
    """Thread-safe cooperative cancellation shared by CLI and future UI."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelledError("operation cancelled")


class PreservationToken:
    """Thread-safe request to stop optimization and preserve a legal result."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    @property
    def is_requested(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


class OperationCancelledError(RuntimeError):
    """Raised when a cooperative cancellation request is observed."""
