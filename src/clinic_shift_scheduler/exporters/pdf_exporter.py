"""Printable monthly-schedule PDF derived exclusively from the formal Excel file."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .excel_exporter import WORKSHEET_NAMES
from .files import FormalExportError, prepare_target


_SCHEDULE_SHEET = "月班表"
_INDIVIDUAL_SUMMARY_SHEET = "個人班型摘要"
_SOLVER_SHEET = "求解與驗證資訊"
_PDF_SUMMARY_HEADER_OVERRIDES = {"週日出勤天數": "週日天數"}
_CJK_FONT = "ClinicScheduleCJK"
_CJK_FONT_BOLD = "ClinicScheduleCJKBold"
_CJK_FONT_ENVIRONMENT_VARIABLE = "CLINIC_SCHEDULER_PDF_FONT"
_CJK_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/NotoSansTC-VF.ttf"),
    Path("C:/Windows/Fonts/msjh.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansTC-Regular.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)
_CJK_BOLD_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msjhbd.ttc"),
    Path("C:/Windows/Fonts/NotoSansTC-VF.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansTC-Bold.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)


def _register_cjk_font() -> None:
    configured = os.environ.get(_CJK_FONT_ENVIRONMENT_VARIABLE)
    candidates = (
        (Path(configured), *_CJK_FONT_CANDIDATES)
        if configured
        else _CJK_FONT_CANDIDATES
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FormalExportError(
            "PDF export requires an embeddable Traditional Chinese font; "
            f"set {_CJK_FONT_ENVIRONMENT_VARIABLE} to a TTF/TTC font path"
        )
    if _CJK_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_CJK_FONT, str(source)))
    bold_source = next(
        (path for path in _CJK_BOLD_FONT_CANDIDATES if path.is_file()),
        source,
    )
    if _CJK_FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_CJK_FONT_BOLD, str(bold_source)))


def _key_value(sheet: Worksheet, label: str) -> Any | None:
    for row in sheet.iter_rows(min_col=1, max_col=2):
        if row[0].value == label:
            return row[1].value
    return None


def _validate_formal_workbook(workbook: Any) -> tuple[Worksheet, Worksheet]:
    if tuple(workbook.sheetnames) != WORKSHEET_NAMES:
        raise FormalExportError(
            "PDF export requires the complete formal Excel workbook structure"
        )
    schedule = workbook[_SCHEDULE_SHEET]
    if schedule["A1"].value != "日期" or schedule["A2"].value != "星期":
        raise FormalExportError("PDF export requires a valid monthly schedule sheet")
    summary = workbook[_INDIVIDUAL_SUMMARY_SHEET]
    if summary["A1"].value != "姓名" or summary["E1"].value != "連續雙班日／出勤日":
        raise FormalExportError(
            "PDF export requires a valid individual pattern summary sheet"
        )
    solver = workbook[_SOLVER_SHEET]
    if _key_value(solver, "正式狀態") != "OPTIMAL":
        raise FormalExportError("PDF export requires Excel formal status OPTIMAL")
    if _key_value(solver, "Validation") != "PASS":
        raise FormalExportError("PDF export requires Excel validation PASS")
    return schedule, summary


def _cell_text(cell: Cell) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return f"{value.month}/{value.day}"
    return str(value)


def _fill_color(cell: Cell) -> colors.Color | None:
    fill = cell.fill
    if fill.fill_type != "solid":
        return None
    rgb = fill.fgColor.rgb
    if not isinstance(rgb, str) or len(rgb) not in (6, 8):
        return None
    return colors.HexColor(f"#{rgb[-6:]}")


def _font_color(cell: Cell) -> colors.Color | None:
    font_color = cell.font.color
    if font_color is None or font_color.type != "rgb":
        return None
    rgb = font_color.rgb
    if not isinstance(rgb, str) or len(rgb) not in (6, 8):
        return None
    return colors.HexColor(f"#{rgb[-6:]}")


def _paragraph(
    text: str,
    *,
    header: bool = False,
    text_color: colors.Color = colors.black,
) -> Paragraph:
    style = ParagraphStyle(
        name="schedule-header" if header else "schedule-cell",
        fontName=_CJK_FONT_BOLD,
        fontSize=7 if header else 6.2,
        leading=8 if header else 7.1,
        alignment=TA_CENTER,
        textColor=text_color,
        wordWrap="CJK",
    )
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(escaped, style)


def _schedule_table(sheet: Worksheet) -> Table:
    values: list[list[Paragraph]] = []
    table_style: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#7890A0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT_BOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.2),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]
    for row_index, row in enumerate(
        sheet.iter_rows(
            min_row=1,
            max_row=sheet.max_row,
            min_col=1,
            max_col=sheet.max_column,
        )
    ):
        rendered_row: list[Paragraph] = []
        for column_index, cell in enumerate(row):
            rendered_row.append(
                _paragraph(
                    _cell_text(cell),
                    header=row_index < 2 or column_index < 2,
                    text_color=_font_color(cell) or colors.black,
                )
            )
            background = _fill_color(cell)
            if background is not None:
                table_style.append(
                    (
                        "BACKGROUND",
                        (column_index, row_index),
                        (column_index, row_index),
                        background,
                    )
                )
        values.append(rendered_row)

    for merged_range in sheet.merged_cells.ranges:
        table_style.append(
            (
                "SPAN",
                (merged_range.min_col - 1, merged_range.min_row - 1),
                (merged_range.max_col - 1, merged_range.max_row - 1),
            )
        )

    usable_width = landscape(A4)[0] - 12 * mm
    period_width = 4.5 * mm
    role_width = 7.5 * mm
    date_width = (
        usable_width - period_width - role_width
    ) / max(1, sheet.max_column - 2)
    table = Table(
        values,
        colWidths=[
            period_width,
            role_width,
            *([date_width] * (sheet.max_column - 2)),
        ],
        repeatRows=2,
        hAlign="CENTER",
    )
    table.setStyle(TableStyle(table_style))
    return table


def _individual_summary_table(sheet: Worksheet) -> Table:
    values: list[list[Paragraph]] = []
    table_style: list[tuple[Any, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#7890A0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C5DFF0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
    ]
    for row_index, row in enumerate(
        sheet.iter_rows(
            min_row=1,
            max_row=sheet.max_row,
            min_col=1,
            max_col=sheet.max_column,
        )
    ):
        rendered_row: list[Paragraph] = []
        for column_index, cell in enumerate(row):
            text_color = colors.black
            if row_index > 0 and column_index == 0:
                text_color = _font_color(cell) or colors.black
            text = _cell_text(cell)
            if row_index == 0:
                text = _PDF_SUMMARY_HEADER_OVERRIDES.get(text, text)
            rendered_row.append(
                _paragraph(
                    text,
                    header=row_index == 0,
                    text_color=text_color,
                )
            )
        values.append(rendered_row)

    widths_mm = (11, 18, 12, 12, 36, 30, 36, 30, 18, 16)
    table = Table(
        values,
        colWidths=[width * mm for width in widths_mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(TableStyle(table_style))
    return table


def _render_pdf(source: Path, target: Path) -> None:
    workbook = load_workbook(source, read_only=False, data_only=True)
    try:
        schedule, summary = _validate_formal_workbook(workbook)
        title = workbook.properties.title or f"{source.stem} 月班表"
        _register_cjk_font()
        document = SimpleDocTemplate(
            str(target),
            pagesize=landscape(A4),
            leftMargin=6 * mm,
            rightMargin=6 * mm,
            topMargin=5 * mm,
            bottomMargin=5 * mm,
            title=f"{title}（本月班表）",
            author="clinic-shift-scheduler",
            subject="正式月班表列印版",
        )
        title_style = ParagraphStyle(
            name="schedule-title",
            fontName=_CJK_FONT_BOLD,
            fontSize=11,
            leading=13,
            alignment=TA_CENTER,
            spaceAfter=0,
        )
        document.build(
            [
                Paragraph(f"{title}（本月班表）", title_style),
                Spacer(1, 2 * mm),
                _schedule_table(schedule),
                Spacer(1, 3 * mm),
                _individual_summary_table(summary),
            ]
        )
    finally:
        workbook.close()


def export_schedule_pdf_from_excel(
    excel_path: str | Path,
    *,
    output_path: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Create an atomic, single-sheet PDF using only the formal Excel workbook."""

    source = Path(excel_path)
    if not source.is_file():
        raise FileNotFoundError(f"formal Excel file not found: {source}")
    target = Path(output_path) if output_path is not None else source.with_suffix(".pdf")
    prepare_target(target, overwrite=overwrite)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.",
            suffix=".pdf",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        _render_pdf(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target
