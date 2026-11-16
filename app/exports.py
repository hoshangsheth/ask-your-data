"""
Exports of an answered question: the result table as CSV or Excel, and a one-page PDF report.

    to_csv(columns, rows) -> bytes
    to_xlsx(columns, rows, title) -> bytes
    to_pdf(report) -> bytes            # question, answer, chart image, table, SQL, model details

Rows come from re-running the stored, already-validated SQL (up to EXPORT_MAX_ROWS), so
exports can hold more rows than the chat shows.
"""

import base64
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

PDF_TABLE_ROWS = 25


def filename_for(question: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", question)[:50].strip("_") or "result"
    return f"{stem}.{ext}"


def to_csv(columns: list[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel opens UTF-8 (e.g. ₹) correctly


def to_xlsx(columns: list[str], rows: list[list[Any]], title: str) -> bytes:
    from openpyxl import Workbook  # loaded on first export (keeps start-up fast)
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Result"
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    for r in rows:
        ws.append(r)
    for i, col in enumerate(columns, start=1):
        width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:200]])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 50)
    ws.freeze_panes = "A2"
    info = wb.create_sheet("About")
    info.append(["Question", title])
    info.append(["Exported", datetime.now().strftime("%Y-%m-%d %H:%M")])
    info.append(["Rows", len(rows)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@dataclass
class Report:
    question: str
    answer: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    dataset_name: str
    details: dict[str, str] = field(default_factory=dict)  # e.g. model, latency, date
    chart_png: bytes | None = None


def _latin1(text: Any) -> str:
    """The PDF core fonts are Latin-1: spell out the rupee sign, replace other symbols."""
    s = str(text).replace("₹", "Rs ").replace("−", "-").replace("–", "-").replace("—", "-").replace("’", "'")
    return s.encode("latin-1", "replace").decode("latin-1")


def decode_png_data_url(data_url: str) -> bytes | None:
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        return None
    try:
        raw = base64.b64decode(data_url[len(prefix) :], validate=True)
    except ValueError:
        return None
    return raw if raw.startswith(b"\x89PNG") else None


def to_pdf(r: Report) -> bytes:
    from fpdf import FPDF  # loaded on first PDF (keeps start-up fast)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(79, 70, 229)
    pdf.cell(w, 5, _latin1(f"ASK YOUR DATA  ·  {r.dataset_name}".replace("·", "-")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_text_color(17, 24, 39)
    pdf.set_font("Helvetica", "B", 15)
    pdf.multi_cell(w, 7, _latin1(r.question), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(w, 5.5, _latin1(r.answer), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if r.chart_png:
        try:
            pdf.image(io.BytesIO(r.chart_png), w=w)
            pdf.ln(3)
        except Exception:  # a bad image must not break the report
            pass

    if r.columns and r.rows:
        shown = r.rows[:PDF_TABLE_ROWS]
        pdf.set_font("Helvetica", "B", 8)
        col_w = w / len(r.columns)
        pdf.set_fill_color(238, 242, 255)
        for c in r.columns:
            pdf.cell(col_w, 6, _latin1(c)[:28], border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        for row in shown:
            for v in row:
                is_num = isinstance(v, (int, float)) and not isinstance(v, bool)
                text = f"{v:,.2f}" if isinstance(v, float) else str(v if v is not None else "")
                pdf.cell(col_w, 5.5, _latin1(text)[:32], border=1, align="R" if is_num else "L")
            pdf.ln()
        if len(r.rows) > len(shown):
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(w, 5, f"First {len(shown)} of {len(r.rows)} rows.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(w, 5, "SQL", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier", "", 8)
    pdf.set_fill_color(246, 247, 249)
    pdf.multi_cell(w, 4, _latin1(r.sql), fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if r.details:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(107, 114, 128)
        line = "   |   ".join(f"{k}: {v}" for k, v in r.details.items())
        pdf.multi_cell(w, 4, _latin1(line), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
