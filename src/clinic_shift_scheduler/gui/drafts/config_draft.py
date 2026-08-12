"""Mutable GUI draft for the versioned scheduler configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ...app_config import (
    CandidateDiagnosticSettings,
    DiagnosticTimeSettings,
    SchedulerAppConfig,
)


@dataclass(slots=True)
class ConfigDraft:
    """UI-owned mutable values converted back through the formal config types."""

    input_file: str
    overwrite: bool
    progress_update_seconds: float
    candidate_enabled: bool
    candidate_search_limit: int
    diagnostic_time_mode: str
    diagnostic_fixed_seconds: float
    diagnostic_time_ratio: float
    candidate_export_count: int
    candidate_export_formats: list[str]
    config_version: str

    @classmethod
    def from_config(cls, config: SchedulerAppConfig) -> ConfigDraft:
        timing = config.candidate_diagnostic.time
        return cls(
            input_file=config.input_file,
            overwrite=config.overwrite,
            progress_update_seconds=float(config.progress_update_seconds),
            candidate_enabled=config.candidate_diagnostic.enabled,
            candidate_search_limit=config.candidate_diagnostic.search_limit,
            diagnostic_time_mode=timing.mode,
            diagnostic_fixed_seconds=float(timing.fixed_seconds or 60.0),
            diagnostic_time_ratio=float(timing.scheduling_time_ratio or 0.2),
            candidate_export_count=config.candidate_diagnostic.export_count,
            candidate_export_formats=list(
                config.candidate_diagnostic.export_formats
            ),
            config_version=config.config_version,
        )

    def to_config(self) -> SchedulerAppConfig:
        """Build the canonical immutable config and run all value checks."""

        timing = DiagnosticTimeSettings(
            mode=self.diagnostic_time_mode,
            fixed_seconds=(
                self.diagnostic_fixed_seconds
                if self.diagnostic_time_mode == "定值"
                else None
            ),
            scheduling_time_ratio=(
                self.diagnostic_time_ratio
                if self.diagnostic_time_mode == "比例"
                else None
            ),
        )
        diagnostic = CandidateDiagnosticSettings(
            enabled=self.candidate_enabled,
            search_limit=self.candidate_search_limit,
            time=timing,
            export_count=self.candidate_export_count,
            export_formats=tuple(self.candidate_export_formats),
        )
        return SchedulerAppConfig(
            input_file=self.input_file.strip(),
            overwrite=self.overwrite,
            progress_update_seconds=self.progress_update_seconds,
            candidate_diagnostic=diagnostic,
            config_version=self.config_version,
        )

    def replace_from(self, config: SchedulerAppConfig) -> None:
        """Restore every editable value from a validated immutable config."""

        restored = self.from_config(config)
        for field_name in self.__dataclass_fields__:
            value = getattr(restored, field_name)
            setattr(
                self,
                field_name,
                list(value) if isinstance(value, list) else value,
            )

    def snapshot(self) -> str:
        """Return a deterministic value snapshot for dirty-state comparisons."""

        return json.dumps(
            {
                field_name: getattr(self, field_name)
                for field_name in self.__dataclass_fields__
            },
            ensure_ascii=False,
            sort_keys=True,
        )
