"""Transactional coordination for one complete formal output bundle."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from ..models import NormalizedScheduleInput
from ..output import FormalScheduleOutput
from .excel_exporter import export_result_excel
from .files import (
    DEFAULT_OUTPUT_DIRECTORY,
    FormalExportError,
    OutputPaths,
    build_output_paths,
    prepare_target,
)
from .json_exporter import export_result_json
from .pdf_exporter import export_schedule_pdf_from_excel


@dataclass(frozen=True, slots=True)
class FormalExportBundle:
    """Committed formal paths and per-medium generation timings."""

    json_path: Path
    excel_path: Path
    pdf_path: Path
    json_export_seconds: float
    excel_export_seconds: float
    pdf_export_seconds: float


class FormalExportCommitError(FormalExportError):
    """Raised when a staged bundle cannot be committed or restored safely."""


def export_formal_result_bundle(
    data: NormalizedScheduleInput,
    output: FormalScheduleOutput,
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    overwrite: bool = False,
) -> FormalExportBundle:
    """Generate all formal media before transactionally replacing the bundle."""

    targets = build_output_paths(data, output_directory)
    for target in _bundle_paths(targets):
        prepare_target(target, overwrite=overwrite)

    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{targets.stem}.staging-",
            dir=targets.directory,
        ) as temporary_directory:
            staging_directory = Path(temporary_directory)

            started = perf_counter()
            staged_json = export_result_json(
                data,
                output,
                output_directory=staging_directory,
                overwrite=True,
                filename_stem=targets.stem,
            )
            json_seconds = perf_counter() - started

            started = perf_counter()
            staged_excel = export_result_excel(
                data,
                output,
                output_directory=staging_directory,
                overwrite=True,
                filename_stem=targets.stem,
            )
            excel_seconds = perf_counter() - started

            started = perf_counter()
            staged_pdf = export_schedule_pdf_from_excel(
                staged_excel,
                output_path=staging_directory / targets.pdf.name,
                overwrite=True,
            )
            pdf_seconds = perf_counter() - started

            staged = (staged_json, staged_excel, staged_pdf)
            if not all(path.is_file() for path in staged):
                raise FormalExportCommitError(
                    "formal output staging did not produce a complete bundle"
                )
            _commit_bundle(
                staged,
                _bundle_paths(targets),
                staging_directory=staging_directory,
                overwrite=overwrite,
            )
    except FormalExportCommitError:
        raise
    except Exception as error:
        raise FormalExportCommitError(
            f"formal output bundle failed: {error}"
        ) from error

    return FormalExportBundle(
        json_path=targets.json,
        excel_path=targets.excel,
        pdf_path=targets.pdf,
        json_export_seconds=json_seconds,
        excel_export_seconds=excel_seconds,
        pdf_export_seconds=pdf_seconds,
    )


def _bundle_paths(paths: OutputPaths) -> tuple[Path, Path, Path]:
    return paths.json, paths.excel, paths.pdf


def _commit_bundle(
    staged_paths: tuple[Path, Path, Path],
    target_paths: tuple[Path, Path, Path],
    *,
    staging_directory: Path,
    overwrite: bool,
) -> None:
    """Commit staged files and restore the previous bundle on any failure."""

    if not overwrite:
        for target in target_paths:
            prepare_target(target, overwrite=False)

    backup_directory = staging_directory / "previous"
    backup_directory.mkdir()
    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        if overwrite:
            for target in target_paths:
                if target.exists():
                    backup = backup_directory / target.name
                    os.replace(target, backup)
                    backups[target] = backup
        for staged, target in zip(staged_paths, target_paths, strict=True):
            os.replace(staged, target)
            committed.append(target)
    except Exception as commit_error:
        restoration_errors: list[OSError] = []
        for target in reversed(committed):
            try:
                target.unlink(missing_ok=True)
            except OSError as error:
                restoration_errors.append(error)
        for target, backup in backups.items():
            try:
                if backup.exists():
                    os.replace(backup, target)
            except OSError as error:
                restoration_errors.append(error)
        if restoration_errors:
            raise FormalExportCommitError(
                "formal output commit failed and the previous bundle could not "
                "be fully restored"
            ) from commit_error
        raise
