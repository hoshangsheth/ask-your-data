"""
Feedback storage: the users-table migration for name/company, the Excel workbook and the
Google Sheet sync payload (no network: urlopen is replaced).
"""

import io
import json
from types import SimpleNamespace

from openpyxl import load_workbook
from sqlalchemy import create_engine, inspect, text

from app.db.app_tables import add_missing_columns
from app.telemetry import feedback
from app.telemetry.feedback import COLUMNS, SheetSync, feedback_xlsx, make_row

Q = SimpleNamespace(
    id="a" * 32,
    question="and by segment?",
    standalone_question="Customers by segment?",
    answer="Consumer leads.",
    sql="SELECT 1",
    dataset_id="demo",
    sql_model="gemini",
    latency_ms=2340,
)


def test_old_users_table_gets_name_and_company():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR(32) PRIMARY KEY, email VARCHAR(254))"))
        conn.execute(text("INSERT INTO users VALUES ('u1', 'old@example.test')"))
        assert add_missing_columns(conn) == ["users.name", "users.company"]
        assert add_missing_columns(conn) == []  # idempotent
        cols = {c["name"] for c in inspect(conn).get_columns("users")}
        assert {"name", "company"} <= cols
        assert conn.execute(text("SELECT name, company FROM users")).one() == ("", "")  # existing rows keep working


def test_make_row_and_workbook():
    row = make_row(Q, -1, "wrong", "", "", "")
    assert row["name"] == "Guest" and row["rating"].endswith("Not helpful")
    assert row["understood_as"] == "Customers by segment?" and row["seconds"] == 2.3 and row["dataset"] == "Demo store"
    ws = load_workbook(io.BytesIO(feedback_xlsx([row])))["Feedback"]
    assert [c.value for c in ws[1]] == [label for _, label, _ in COLUMNS]
    assert ws.cell(2, 3).value == "wrong" and ws.freeze_panes == "A2"


def test_sheet_sync_is_off_without_an_https_url():
    assert not SheetSync("").enabled and not SheetSync("http://insecure.example").enabled
    assert SheetSync("").send({}) is False


def test_sheet_sync_posts_columns_row_and_token(monkeypatch):
    seen = {}

    class Res:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), timeout=timeout)
        return Res()

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)
    sync = SheetSync(" https://script.google.com/macros/s/x/exec ", "secret", timeout=2)
    assert sync.send(make_row(Q, 1, "", "Asha", "Acme", "asha@example.test")) is True
    body = seen["body"]
    assert seen["url"] == "https://script.google.com/macros/s/x/exec" and seen["timeout"] == 2
    assert body["token"] == "secret" and len(body["columns"]) == len(body["row"]) == len(COLUMNS)
    assert body["row"][body["columns"].index("Company")] == "Acme"
