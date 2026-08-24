"""Lightweight request contracts shared by application adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .app_config import SUPPORTED_CANDIDATE_EXPORT_FORMATS


DEFAULT_INTERMEDIATE_DIRECTORY = Path("runtime/expanded-input")


@dataclass(frozen=True, slots=True)
class CandidateExportConfig:
    """How many diagnosed candidates to persist and in which media."""

    max_candidates: int = 0
    formats: tuple[str, ...] = ("json",)

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_candidates, bool)
            or not isinstance(self.max_candidates, int)
            or self.max_candidates < 0
        ):
            raise ValueError("candidate export count must be a non-negative integer")
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("candidate export formats cannot contain duplicates")
        unsupported = sorted(set(self.formats) - SUPPORTED_CANDIDATE_EXPORT_FORMATS)
        if unsupported:
            raise ValueError(
                "unsupported candidate export formats: " + ", ".join(unsupported)
            )
        if self.max_candidates and not self.formats:
            raise ValueError("candidate export formats cannot be empty")


@dataclass(frozen=True, slots=True)
class ProvisionalExportConfig:
    """Media selected when preserving a validated partial schedule."""

    formats: tuple[str, ...] = ("json", "excel", "pdf")

    def __post_init__(self) -> None:
        if not self.formats:
            raise ValueError("provisional export formats cannot be empty")
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("provisional export formats cannot contain duplicates")
        unsupported = sorted(
            set(self.formats) - SUPPORTED_CANDIDATE_EXPORT_FORMATS
        )
        if unsupported:
            raise ValueError(
                "unsupported provisional export formats: "
                + ", ".join(unsupported)
            )
