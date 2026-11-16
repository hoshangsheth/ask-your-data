"""
User feedback (👍 / 👎) with who gave it, for review in Excel or a Google Sheet.

    rows = feedback_rows(engine)                 # every rated answer, newest first, with name/company/email
    data = feedback_xlsx(rows)                    # an Excel workbook (bytes)
    sheet = SheetSync(url, token); sheet.send(row)   # append one row to a Google Sheet (optional)

Google Sheet sync uses a small Apps Script web app the owner pastes into their sheet once
(docs/GOOGLE_SHEETS.md): every rating is POSTed as JSON and appended as a row. It is off unless
FEEDBACK_SHEET_URL is set, and a failure never affects the user (it is logged and skipped).
"""

import io
import json
import urllib.request
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select

from app.db.app_tables import questions, users

COLUMNS = [
    ("time", "Time (UTC)", 18),
    ("rating", "Rating", 12),
    ("note", "Note", 40),
    ("name", "Name", 20),
    ("company", "Company", 22),
    ("email", "Email", 28),
    ("question", "Question", 45),
    ("understood_as", "Understood as", 45),
    ("answer", "Answer", 60),
    ("sql", "SQL", 60),
    ("dataset", "Dataset", 14),
    ("model", "Model", 18),
    ("seconds", "Answer time (s)", 14),
    ("question_id", "Question ID", 34),
]
RATING = {1: "👍 Helpful", -1: "👎 Not helpful", 0: "Cleared"}


def _ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "")[:19].replace("T", " ")


def make_row(q: Any, rating: int, note: str, name: str, company: str, email: str, when: Any = None) -> dict[str, Any]:
    """One feedback row from a stored question (anything with the question-log fields)."""
    return {
        "time": _ts(when or datetime.now(UTC)),
        "rating": RATING.get(rating, str(rating)),
        "note": note or "",
        "name": name or "Guest",
        "company": company or "",
        "email": email or "",
        "question": q.question,
        "understood_as": q.standalone_question if q.standalone_question != q.question else "",
        "answer": q.answer,
        "sql": q.sql,
        "dataset": "Demo store" if q.dataset_id == "demo" else "Upload",
        "model": q.sql_model,
        "seconds": round((q.latency_ms or 0) / 1000, 1),
        "question_id": q.id,
    }


def feedback_rows(engine: Engine, limit: int = 10_000) -> list[dict[str, Any]]:
    """Every answer that currently has a rating, newest first, with the user's details."""
    q, u = questions.c, users.c
    query = (
        select(
            q.id,
            q.created_at,
            q.question,
            q.standalone_question,
            q.answer,
            q.sql,
            q.dataset_id,
            q.sql_model,
            q.latency_ms,
            q.feedback,
            q.feedback_note,
            u.name,
            u.company,
            u.email,
        )
        .select_from(questions.outerjoin(users, q.user_id == u.id))
        .where(q.feedback.is_not(None))
        .order_by(q.created_at.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return [make_row(r, r.feedback, r.feedback_note, r.name, r.company, r.email, r.created_at) for r in rows]


def feedback_xlsx(rows: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook  # loaded on first download (keeps start-up fast)
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Feedback"
    ws.append([label for _, label, _ in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    for r in rows:
        ws.append([r[key] for key, _, _ in COLUMNS])
    for i, (_, _, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class SheetSync:
    """Append feedback rows to a Google Sheet through an Apps Script web app (optional)."""

    def __init__(self, url: str, token: str = "", timeout: float = 4.0):
        self.url = url.strip()
        self.token = token
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return self.url.startswith("https://")

    def send(self, row: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        body = json.dumps(
            {
                "token": self.token,
                "columns": [label for _, label, _ in COLUMNS],
                "row": [row[key] for key, _, _ in COLUMNS],
            }
        ).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as res:  # noqa: S310 - owner-configured https URL
            return 200 <= res.status < 400
