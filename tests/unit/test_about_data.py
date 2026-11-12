"""
Chatting about the data itself: the model can answer from the schema without writing SQL.
Checks how the SQL step's output is read (kinds, fallbacks for older or incomplete output).
"""

from app.llm.contracts import JSONResult
from app.llm.prompts import SQL_SCHEMA, SQL_SYSTEM
from app.llm.text_to_sql import SQLDraft, TextToSQL


class OneShot:
    name = "fake"

    def __init__(self, data):
        self.data = data
        self.calls = []

    def complete_json(self, **kw):
        self.calls.append(kw)
        return JSONResult(self.data, "m", 10, 5)


def draft(data) -> SQLDraft:
    return TextToSQL(OneShot(data), sql_model="m", summary_model="m").generate_sql(
        question="q", schema="TABLE t", dialect="sqlite"
    )


def test_schema_offers_three_kinds():
    assert SQL_SCHEMA["properties"]["kind"]["enum"] == ["query", "about", "unanswerable"]
    assert {"kind", "answer"} <= set(SQL_SCHEMA["required"])
    assert '"about"' in SQL_SYSTEM


def test_about_answer_has_no_sql():
    d = draft(
        {
            "kind": "about",
            "sql": "SELECT 1",
            "answer": "Four tables: ...",
            "explanation": "",
            "standalone_question": "q",
        }
    )
    assert d.mode == "about" and d.reply == "Four tables: ..." and d.sql == "" and d.answerable


def test_query_and_unanswerable():
    q = draft({"kind": "query", "sql": "SELECT 1 FROM t", "answer": "", "explanation": "x", "standalone_question": "q"})
    assert q.mode == "query" and q.sql == "SELECT 1 FROM t" and q.reply == ""
    u = draft(
        {"kind": "unanswerable", "sql": "", "answer": "", "explanation": "not stored", "standalone_question": "q"}
    )
    assert u.mode == "unanswerable" and not u.answerable


def test_about_without_text_falls_back():
    # An "about" with nothing to say is treated as a query if SQL came back, else unanswerable.
    assert draft({"kind": "about", "sql": "SELECT 1", "answer": " ", "explanation": ""}).mode == "query"
    assert draft({"kind": "about", "sql": "", "answer": "", "explanation": ""}).mode == "unanswerable"


def test_older_output_shape_still_works():
    assert draft({"answerable": True, "sql": "SELECT 1", "explanation": "x"}).mode == "query"
    assert draft({"answerable": False, "sql": "", "explanation": "x"}).mode == "unanswerable"
    assert SQLDraft(True, "SELECT 1", "x").mode == "query"  # test doubles without a kind
