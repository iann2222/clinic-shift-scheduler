"""Versioned JSON adapter for finalized schedule output."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..enums import PERIODS_V1
from ..models import NormalizedScheduleInput
from ..output import FormalScheduleOutput, to_primitive
from .files import (
    DEFAULT_OUTPUT_DIRECTORY,
    build_output_paths,
    prepare_target,
    require_formal_result,
    schedule_month,
)


RESULT_CONTRACT_NAME = "clinic-shift-scheduler-formal-result"
RESULT_CONTRACT_VERSION = "1.10"


def _validation_document(output: FormalScheduleOutput) -> dict[str, Any]:
    report = output.validation_report
    assert report is not None
    return {
        "status": report.status.value,
        "checks": dict(report.checks),
        "issues": to_primitive(report.issues),
    }


def _schedule_document(output: FormalScheduleOutput) -> dict[str, Any]:
    schedule = output.monthly_schedule
    assert schedule is not None
    return {
        "dates": to_primitive(schedule.dates),
        "weekdays": to_primitive(schedule.weekdays),
        "rows": to_primitive(schedule.rows),
    }


def build_result_document(
    data: NormalizedScheduleInput,
    output: FormalScheduleOutput,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the stable JSON contract directly from the formal output model."""

    require_formal_result(output)
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    overall = output.overall_statistics
    assert overall is not None
    assignments = sorted(
        output.assignments,
        key=lambda item: (
            item.date,
            PERIODS_V1.index(item.period),
            item.role,
            item.employee_id,
        ),
    )
    return {
        "contract": {
            "name": RESULT_CONTRACT_NAME,
            "version": RESULT_CONTRACT_VERSION,
        },
        "input_schema_version": data.source.schema_version,
        "generated_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "month": schedule_month(data),
        "period": {
            "start_date": data.source.period.start_date.isoformat(),
            "end_date": data.source.period.end_date.isoformat(),
        },
        "status": output.status.value,
        "execution_timing": to_primitive(output.execution_timing),
        "objective_vector": dict(overall.objective_vector),
        "validation": _validation_document(output),
        "stage_records": to_primitive(output.optimization_stages),
        "preference_benchmarks": to_primitive(output.preference_benchmarks),
        "class_pattern_locks": to_primitive(output.class_pattern_locks),
        "assignments": to_primitive(assignments),
        "statistics": {
            "individual": to_primitive(output.individual_statistics),
            "category": to_primitive(output.category_statistics),
            "class_preferences": to_primitive(
                output.class_preference_statistics
            ),
            "fairness_groups": to_primitive(output.fairness_group_statistics),
            "overall": to_primitive(overall),
        },
        "monthly_schedule": _schedule_document(output),
    }


def export_result_json(
    data: NormalizedScheduleInput,
    output: FormalScheduleOutput,
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    overwrite: bool = False,
    generated_at: datetime | None = None,
    filename_stem: str | None = None,
) -> Path:
    """Atomically persist the formal result contract as UTF-8 JSON."""

    document = build_result_document(data, output, generated_at=generated_at)
    target = build_output_paths(
        data,
        output_directory,
        stem=filename_stem,
    ).json
    prepare_target(target, overwrite=overwrite)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.stem}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary = Path(stream.name)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target
