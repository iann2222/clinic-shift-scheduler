"""User-facing configuration for the one-command scheduling entry point."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import AbstractSet, Any, Mapping

from .input_contracts import (
    CONFIG_CANDIDATE_FIELDS,
    CONFIG_DIAGNOSTIC_TIME_FIELDS,
    CONFIG_PRESERVATION_FIELDS,
    CONFIG_ROOT_FIELDS,
    CONFIG_SETTINGS_FIELDS,
)
from .errors import InputValidationError, ValidationIssue
from .events import ExecutionPhase
from .json_io import read_json_object, write_json_object_atomic


APP_CONFIG_VERSION = "1"
SUPPORTED_CANDIDATE_EXPORT_FORMATS = frozenset({"json", "excel", "pdf"})
DIAGNOSTIC_TIME_MODES = frozenset({"定值", "比例"})
DEFAULT_OVERWRITE_EXISTING_RESULTS = True
DEFAULT_PROGRESS_UPDATE_SECONDS = 5.0
DEFAULT_CANDIDATE_DIAGNOSTIC_ENABLED = True
DEFAULT_CANDIDATE_SEARCH_LIMIT = 100
DEFAULT_DIAGNOSTIC_TIME_MODE = "比例"
DEFAULT_DIAGNOSTIC_TIME_RATIO = 0.2
DEFAULT_CANDIDATE_EXPORT_COUNT = 3
DEFAULT_CANDIDATE_EXPORT_FORMATS = ("json", "excel", "pdf")
DEFAULT_PRESERVATION_EXPORT_FORMATS = ("json", "excel", "pdf")

_EXPORT_FORMAT_LABELS = {
    "json": "JSON",
    "excel": "Excel",
    "pdf": "PDF",
}


def _require_object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} 必須是 JSON object")
    return value


def _reject_unknown_fields(
    payload: Mapping[str, Any],
    allowed: AbstractSet[str],
    field: str,
) -> None:
    unknown = sorted(
        key
        for key in set(payload) - allowed
        if not (key.startswith("__") and key.endswith("__"))
    )
    if unknown:
        raise ValueError(f"{field} 含有未知欄位：{', '.join(unknown)}")


@dataclass(frozen=True, slots=True)
class DiagnosticTimeSettings:
    mode: str = DEFAULT_DIAGNOSTIC_TIME_MODE
    fixed_seconds: float | None = None
    scheduling_time_ratio: float | None = DEFAULT_DIAGNOSTIC_TIME_RATIO

    def __post_init__(self) -> None:
        if self.mode not in DIAGNOSTIC_TIME_MODES:
            raise ValueError("診斷時間上限.模式只接受『定值』或『比例』")
        if self.mode == "定值":
            if (
                isinstance(self.fixed_seconds, bool)
                or not isinstance(self.fixed_seconds, (int, float))
                or self.fixed_seconds <= 0
            ):
                raise ValueError("定值模式必須提供大於 0 的診斷時間上限.秒數")
            if self.scheduling_time_ratio is not None:
                raise ValueError("定值模式不可提供診斷時間上限.排班時間比例")
        else:
            if self.fixed_seconds is not None:
                raise ValueError("比例模式不可提供診斷時間上限.秒數")
            if (
                isinstance(self.scheduling_time_ratio, bool)
                or not isinstance(self.scheduling_time_ratio, (int, float))
                or self.scheduling_time_ratio <= 0
            ):
                raise ValueError(
                    "比例模式必須提供大於 0 的診斷時間上限.排班時間比例"
                )


@dataclass(frozen=True, slots=True)
class CandidateDiagnosticSettings:
    enabled: bool = DEFAULT_CANDIDATE_DIAGNOSTIC_ENABLED
    search_limit: int = DEFAULT_CANDIDATE_SEARCH_LIMIT
    time: DiagnosticTimeSettings = field(default_factory=DiagnosticTimeSettings)
    export_count: int = DEFAULT_CANDIDATE_EXPORT_COUNT
    export_formats: tuple[str, ...] = DEFAULT_CANDIDATE_EXPORT_FORMATS

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("候選診斷.啟用必須是布林值")
        if (
            isinstance(self.search_limit, bool)
            or not isinstance(self.search_limit, int)
            or self.search_limit <= 0
        ):
            raise ValueError(
                "候選診斷.搜尋上限必須是正整數"
            )
        if (
            isinstance(self.export_count, bool)
            or not isinstance(self.export_count, int)
            or self.export_count < 0
        ):
            raise ValueError(
                "候選診斷.額外輸出候選班表份數上限必須是非負整數"
            )
        if self.export_count > self.search_limit:
            raise ValueError(
                "候選診斷.額外輸出候選班表份數上限不可超過搜尋上限"
            )
        if not self.enabled and self.export_count:
            raise ValueError(
                "停用候選診斷時，額外輸出候選班表份數上限必須為 0"
            )
        if len(set(self.export_formats)) != len(self.export_formats):
            raise ValueError("候選診斷.輸出格式不可重複")
        unsupported = sorted(
            set(self.export_formats) - SUPPORTED_CANDIDATE_EXPORT_FORMATS
        )
        if unsupported:
            raise ValueError(
                "候選診斷.輸出格式包含不支援的值："
                + ", ".join(unsupported)
            )
        if self.export_count and not self.export_formats:
            raise ValueError("輸出候選班表時，候選診斷.輸出格式不可留空")


@dataclass(frozen=True, slots=True)
class PreservationOutputSettings:
    export_formats: tuple[str, ...] = DEFAULT_PRESERVATION_EXPORT_FORMATS

    def __post_init__(self) -> None:
        if not self.export_formats:
            raise ValueError("當前最佳班表輸出.輸出格式至少選擇一種")
        if len(set(self.export_formats)) != len(self.export_formats):
            raise ValueError("當前最佳班表輸出.輸出格式不可重複")
        unsupported = sorted(
            set(self.export_formats) - SUPPORTED_CANDIDATE_EXPORT_FORMATS
        )
        if unsupported:
            raise ValueError(
                "當前最佳班表輸出.輸出格式包含不支援的值："
                + ", ".join(unsupported)
            )


@dataclass(frozen=True, slots=True)
class SchedulerAppConfig:
    input_file: str
    overwrite: bool = DEFAULT_OVERWRITE_EXISTING_RESULTS
    progress_update_seconds: float = DEFAULT_PROGRESS_UPDATE_SECONDS
    preservation_output: PreservationOutputSettings = field(
        default_factory=PreservationOutputSettings
    )
    candidate_diagnostic: CandidateDiagnosticSettings = field(
        default_factory=CandidateDiagnosticSettings
    )
    config_version: str = APP_CONFIG_VERSION

    def __post_init__(self) -> None:
        if self.config_version != APP_CONFIG_VERSION:
            raise ValueError(
                f"不支援的設定版本：{self.config_version!r}；"
                f"目前必須為 {APP_CONFIG_VERSION!r}"
            )
        if not isinstance(self.input_file, str) or not self.input_file.strip():
            raise ValueError("輸入檔名必須是非空白檔名")
        input_path = Path(self.input_file)
        if input_path.is_absolute() or input_path.name != self.input_file:
            raise ValueError("輸入檔名只能填寫 input 資料夾內的檔名")
        if input_path.suffix.lower() != ".json":
            raise ValueError("輸入檔名必須是 JSON 檔案")
        if not isinstance(self.overwrite, bool):
            raise ValueError("覆寫既有結果必須是布林值")
        if (
            isinstance(self.progress_update_seconds, bool)
            or not isinstance(self.progress_update_seconds, (int, float))
            or self.progress_update_seconds <= 0
        ):
            raise ValueError("進度更新秒數必須大於 0")


def default_scheduler_config(input_file: str) -> SchedulerAppConfig:
    """Build the single executable default configuration."""

    return SchedulerAppConfig(input_file=input_file)


def scheduler_config_to_user_settings(
    config: SchedulerAppConfig,
) -> dict[str, Any]:
    """Serialize typed settings using the stable user-facing Chinese keys."""

    diagnostic_time = config.candidate_diagnostic.time
    time_settings: dict[str, Any] = {"模式": diagnostic_time.mode}
    if diagnostic_time.mode == "定值":
        time_settings["秒數"] = diagnostic_time.fixed_seconds
    else:
        time_settings["排班時間比例"] = (
            diagnostic_time.scheduling_time_ratio
        )
    return {
        "設定版本": config.config_version,
        "輸入檔名": config.input_file,
        "覆寫既有結果": config.overwrite,
        "進度更新秒數": config.progress_update_seconds,
        "當前最佳班表輸出": {
            "輸出格式": [
                _EXPORT_FORMAT_LABELS[item]
                for item in config.preservation_output.export_formats
            ]
        },
        "候選診斷": {
            "啟用": config.candidate_diagnostic.enabled,
            "搜尋上限": config.candidate_diagnostic.search_limit,
            "診斷時間上限": time_settings,
            "額外輸出候選班表份數上限": (
                config.candidate_diagnostic.export_count
            ),
            "輸出格式": [
                _EXPORT_FORMAT_LABELS[item]
                for item in config.candidate_diagnostic.export_formats
            ],
        },
    }


@dataclass(frozen=True, slots=True)
class SchedulerConfigDocument:
    """Typed user/default settings plus preserved ``__...__`` annotations."""

    user_config: SchedulerAppConfig
    default_config: SchedulerAppConfig
    _template: Mapping[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> SchedulerConfigDocument:
        """Validate both config sections before constructing a document."""

        return parse_scheduler_config_document(payload)

    def to_dict(self) -> dict[str, Any]:
        template = deepcopy(dict(self._template))

        def merge_annotations(
            existing: object,
            values: Mapping[str, Any],
        ) -> dict[str, Any]:
            source = existing if isinstance(existing, Mapping) else {}
            result = {
                key: deepcopy(value)
                for key, value in source.items()
                if key.startswith("__") and key.endswith("__")
            }
            for key, value in values.items():
                prior = source.get(key)
                result[key] = (
                    merge_annotations(prior, value)
                    if isinstance(value, Mapping)
                    else deepcopy(value)
                )
            return result

        root_annotations = {
            key: deepcopy(value)
            for key, value in template.items()
            if key.startswith("__") and key.endswith("__")
        }
        root_annotations["使用者設定"] = merge_annotations(
            template.get("使用者設定"),
            scheduler_config_to_user_settings(self.user_config),
        )
        root_annotations["預設設定"] = merge_annotations(
            template.get("預設設定"),
            scheduler_config_to_user_settings(self.default_config),
        )
        return root_annotations


def _collect_config_structure_issues(
    payload: Mapping[str, Any],
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                path=path,
                message=message,
                phase=ExecutionPhase.CONFIG,
            )
        )

    unknown_root = sorted(
        key
        for key in set(payload) - CONFIG_ROOT_FIELDS
        if not (key.startswith("__") and key.endswith("__"))
    )
    for key in unknown_root:
        add("unknown_field", f"$.{key}", "config 含有未知欄位")
    for section_name in ("使用者設定", "預設設定"):
        section = payload.get(section_name)
        path = f"$.{section_name}"
        if section is None:
            add("missing_field", path, "此欄位為必填")
            continue
        if not isinstance(section, Mapping):
            add("invalid_type", path, "必須是 JSON object")
            continue
        unknown_settings = sorted(
            key
            for key in set(section) - CONFIG_SETTINGS_FIELDS
            if not (key.startswith("__") and key.endswith("__"))
        )
        for key in unknown_settings:
            add("unknown_field", f"{path}.{key}", "設定含有未知欄位")
        if "輸入檔名" not in section:
            add("missing_field", f"{path}.輸入檔名", "此欄位為必填")
        candidate = section.get("候選診斷")
        preservation = section.get("當前最佳班表輸出")
        if preservation is not None and not isinstance(preservation, Mapping):
            add(
                "invalid_type",
                f"{path}.當前最佳班表輸出",
                "必須是 JSON object",
            )
        elif isinstance(preservation, Mapping):
            for key in sorted(
                key
                for key in set(preservation) - CONFIG_PRESERVATION_FIELDS
                if not (key.startswith("__") and key.endswith("__"))
            ):
                add(
                    "unknown_field",
                    f"{path}.當前最佳班表輸出.{key}",
                    "當前最佳班表輸出含有未知欄位",
                )
        if candidate is not None and not isinstance(candidate, Mapping):
            add("invalid_type", f"{path}.候選診斷", "必須是 JSON object")
        elif isinstance(candidate, Mapping):
            for key in sorted(
                key
                for key in set(candidate) - CONFIG_CANDIDATE_FIELDS
                if not (key.startswith("__") and key.endswith("__"))
            ):
                add(
                    "unknown_field",
                    f"{path}.候選診斷.{key}",
                    "候選診斷含有未知欄位",
                )
            timing = candidate.get("診斷時間上限")
            if timing is not None and not isinstance(timing, Mapping):
                add(
                    "invalid_type",
                    f"{path}.候選診斷.診斷時間上限",
                    "必須是 JSON object",
                )
            elif isinstance(timing, Mapping):
                for key in sorted(
                    key
                    for key in set(timing) - CONFIG_DIAGNOSTIC_TIME_FIELDS
                    if not (key.startswith("__") and key.endswith("__"))
                ):
                    add(
                        "unknown_field",
                        f"{path}.候選診斷.診斷時間上限.{key}",
                        "診斷時間上限含有未知欄位",
                    )
    return tuple(issues)


def _parse_scheduler_config(payload: Mapping[str, Any]) -> SchedulerAppConfig:
    """Validate and normalize a user-facing configuration object."""

    _reject_unknown_fields(
        payload,
        CONFIG_ROOT_FIELDS,
        "config",
    )
    if "使用者設定" not in payload:
        raise ValueError("config.使用者設定為必填")
    if "預設設定" not in payload:
        raise ValueError("config.預設設定為必填")
    settings = _require_object(payload["使用者設定"], "使用者設定")
    _require_object(payload["預設設定"], "預設設定")
    _reject_unknown_fields(
        settings,
        CONFIG_SETTINGS_FIELDS,
        "使用者設定",
    )
    if "輸入檔名" not in settings:
        raise ValueError("使用者設定.輸入檔名為必填")

    defaults = default_scheduler_config(settings["輸入檔名"])
    candidate_defaults = defaults.candidate_diagnostic
    preservation_defaults = defaults.preservation_output
    preservation_payload = _require_object(
        settings.get("當前最佳班表輸出", {}),
        "當前最佳班表輸出",
    )
    _reject_unknown_fields(
        preservation_payload,
        CONFIG_PRESERVATION_FIELDS,
        "當前最佳班表輸出",
    )
    raw_preservation_formats = preservation_payload.get(
        "輸出格式",
        [
            _EXPORT_FORMAT_LABELS[item]
            for item in preservation_defaults.export_formats
        ],
    )
    if not isinstance(raw_preservation_formats, list) or not all(
        isinstance(item, str) for item in raw_preservation_formats
    ):
        raise ValueError("當前最佳班表輸出.輸出格式必須是字串陣列")
    preservation_output = PreservationOutputSettings(
        export_formats=tuple(
            item.lower() for item in raw_preservation_formats
        )
    )
    candidate_payload = _require_object(
        settings.get("候選診斷", {}),
        "候選診斷",
    )
    _reject_unknown_fields(
        candidate_payload,
        CONFIG_CANDIDATE_FIELDS,
        "候選診斷",
    )
    time_payload = _require_object(
        candidate_payload.get(
            "診斷時間上限",
            {
                "模式": candidate_defaults.time.mode,
                "排班時間比例": (
                    candidate_defaults.time.scheduling_time_ratio
                ),
            },
        ),
        "候選診斷.診斷時間上限",
    )
    _reject_unknown_fields(
        time_payload,
        CONFIG_DIAGNOSTIC_TIME_FIELDS,
        "候選診斷.診斷時間上限",
    )
    time_mode = time_payload.get("模式", candidate_defaults.time.mode)
    time = DiagnosticTimeSettings(
        mode=time_mode,
        fixed_seconds=time_payload.get("秒數"),
        scheduling_time_ratio=time_payload.get(
            "排班時間比例",
            (
                candidate_defaults.time.scheduling_time_ratio
                if time_mode == "比例"
                else None
            ),
        ),
    )

    raw_formats = candidate_payload.get(
        "輸出格式",
        [
            _EXPORT_FORMAT_LABELS[item]
            for item in candidate_defaults.export_formats
        ],
    )
    if not isinstance(raw_formats, list) or not all(
        isinstance(item, str) for item in raw_formats
    ):
        raise ValueError("候選診斷.輸出格式必須是字串陣列")
    normalized_formats = tuple(item.lower() for item in raw_formats)

    diagnostic = CandidateDiagnosticSettings(
        enabled=candidate_payload.get("啟用", candidate_defaults.enabled),
        search_limit=candidate_payload.get(
            "搜尋上限", candidate_defaults.search_limit
        ),
        time=time,
        export_count=candidate_payload.get(
            "額外輸出候選班表份數上限",
            candidate_defaults.export_count,
        ),
        export_formats=normalized_formats,
    )
    return SchedulerAppConfig(
        config_version=settings.get("設定版本", defaults.config_version),
        input_file=settings["輸入檔名"],
        overwrite=settings.get("覆寫既有結果", defaults.overwrite),
        progress_update_seconds=settings.get(
            "進度更新秒數", defaults.progress_update_seconds
        ),
        preservation_output=preservation_output,
        candidate_diagnostic=diagnostic,
    )


def parse_scheduler_config(payload: Mapping[str, Any]) -> SchedulerAppConfig:
    """Validate config and expose failures through the shared issue contract."""

    issues = _collect_config_structure_issues(payload)
    if issues:
        raise InputValidationError(issues)
    try:
        return _parse_scheduler_config(payload)
    except InputValidationError:
        raise
    except (TypeError, ValueError) as error:
        raise InputValidationError(
            (
                ValidationIssue(
                    code="invalid_config_value",
                    path="$",
                    message=str(error),
                    phase=ExecutionPhase.CONFIG,
                ),
            )
        ) from error


def parse_scheduler_config_document(
    payload: Mapping[str, Any],
) -> SchedulerConfigDocument:
    """Validate both effective and restore-default sections."""

    user_config = parse_scheduler_config(payload)
    default_payload = _require_object(payload["預設設定"], "預設設定")
    default_document = {
        "使用者設定": default_payload,
        "預設設定": default_payload,
    }
    default_config = parse_scheduler_config(default_document)
    return SchedulerConfigDocument(
        user_config=user_config,
        default_config=default_config,
        _template=deepcopy(dict(payload)),
    )


def load_scheduler_config(path: str | Path) -> SchedulerAppConfig:
    """Read one UTF-8 JSON configuration file."""

    return load_scheduler_config_document(path).user_config


def load_scheduler_config_document(
    path: str | Path,
) -> SchedulerConfigDocument:
    """Read and validate a complete versioned config document."""

    return parse_scheduler_config_document(read_json_object(path))


def write_scheduler_config_document(
    path: str | Path,
    document: SchedulerConfigDocument,
) -> Path:
    """Atomically persist both config sections and preserved annotations."""

    payload = document.to_dict()
    validated = parse_scheduler_config_document(payload)
    return write_json_object_atomic(path, validated.to_dict())
