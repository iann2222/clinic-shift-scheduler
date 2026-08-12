"""Application service for editing and atomically saving ``config.json``."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .app_config import (
    SchedulerConfigDocument,
    load_scheduler_config_document,
    write_scheduler_config_document,
)
from .errors import InputValidationError
from .events import DiagnosticIssue, ExecutionPhase
from .gui.drafts import ConfigDraft


@dataclass(frozen=True, slots=True)
class ConfigValidationResult:
    is_valid: bool
    issues: tuple[DiagnosticIssue, ...]
    document: SchedulerConfigDocument | None = None


@dataclass(slots=True)
class ConfigSession:
    path: Path
    document: SchedulerConfigDocument
    draft: ConfigDraft
    _clean_snapshot: str

    @property
    def is_dirty(self) -> bool:
        return self.draft.snapshot() != self._clean_snapshot

    def restore_defaults(self) -> None:
        self.draft.replace_from(self.document.default_config)

    def mark_clean(self, document: SchedulerConfigDocument) -> None:
        self.document = document
        self._clean_snapshot = self.draft.snapshot()


class ConfigApplication:
    """Keep config parsing, validation, and persistence outside Qt widgets."""

    def open_document(self, path: str | Path) -> ConfigSession:
        resolved = Path(path)
        document = load_scheduler_config_document(resolved)
        draft = ConfigDraft.from_config(document.user_config)
        return ConfigSession(
            path=resolved,
            document=document,
            draft=draft,
            _clean_snapshot=draft.snapshot(),
        )

    def validate(self, session: ConfigSession) -> ConfigValidationResult:
        try:
            user_config = session.draft.to_config()
            document = replace(
                session.document,
                user_config=user_config,
            )
            # Round-trip through the stable JSON contract before any write.
            validated = SchedulerConfigDocument.from_dict(document.to_dict())
        except InputValidationError as error:
            return ConfigValidationResult(False, tuple(error.issues))
        except (TypeError, ValueError) as error:
            return ConfigValidationResult(
                False,
                (
                    DiagnosticIssue(
                        code="invalid_config_value",
                        path="$.使用者設定",
                        message=str(error),
                        phase=ExecutionPhase.CONFIG,
                    ),
                ),
            )
        return ConfigValidationResult(True, (), validated)

    def save(self, session: ConfigSession) -> Path:
        result = self.validate(session)
        if not result.is_valid or result.document is None:
            raise InputValidationError(result.issues)
        saved = write_scheduler_config_document(session.path, result.document)
        session.mark_clean(result.document)
        return saved
