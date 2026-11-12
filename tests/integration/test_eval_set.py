"""
The eval set itself must be valid: unique ids, enough questions, and every reference query
passes the SQL guard and returns rows on the test database.
"""

import pytest

from app.db.engine import dialect_of
from app.db.executor import run_readonly
from app.db.models import ALLOWED_TABLES
from app.sql.guard import validate_sql
from evals.dataset import load_questions, reference_sql

ANSWERABLE = [q for q in load_questions() if not q.get("unanswerable")]


def test_eval_set_size_and_ids():
    items = load_questions()
    assert len(items) >= 30
    assert len({q["id"] for q in items}) == len(items)


@pytest.mark.parametrize("item", ANSWERABLE, ids=[q["id"] for q in ANSWERABLE])
def test_reference_sql_runs(item, ro_engine):
    dialect = dialect_of(ro_engine)
    sql = reference_sql(item, dialect)
    validate_sql(sql, dialect=dialect, allowed_tables=ALLOWED_TABLES, max_rows=1000)
    r = run_readonly(ro_engine, sql, max_rows=1000, timeout_ms=10_000)
    assert r.rows, f"{item['id']} returned no rows"
