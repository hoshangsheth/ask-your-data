"""
Database layer against a real (seeded) database: demo data generation, read-only execution,
timeouts, schema description and dashboard KPIs.
"""

import pytest

from app.analytics.kpis import compute_kpis
from app.db.catalog import describe_schema
from app.db.engine import dialect_of
from app.db.executor import QueryError, run_readonly
from app.db.seed import generate


def test_generate_is_deterministic():
    a = generate(n_customers=50, n_orders=200, seed=7)
    b = generate(n_customers=50, n_orders=200, seed=7)
    assert a["orders"] == b["orders"] and a["order_items"] == b["order_items"]


def test_generate_referential_integrity():
    d = generate(n_customers=80, n_orders=500, seed=1)
    customer_ids = {c["customer_id"] for c in d["customers"]}
    order_ids = {o["order_id"] for o in d["orders"]}
    product_ids = {p["product_id"] for p in d["products"]}
    signup = {c["customer_id"]: c["signup_date"] for c in d["customers"]}
    assert all(o["customer_id"] in customer_ids for o in d["orders"])
    assert all(o["order_date"] >= signup[o["customer_id"]] for o in d["orders"])
    assert all(i["order_id"] in order_ids and i["product_id"] in product_ids for i in d["order_items"])


def test_relative_sqlite_path_is_anchored_to_project_root(tmp_path, monkeypatch):
    from app.core.config import PROJECT_ROOT
    from app.db.engine import make_engines

    monkeypatch.chdir(tmp_path)  # start "somewhere else", like running from inside app/
    owner, ro = make_engines("sqlite:///./data/shop.db")
    assert owner.url.database == (PROJECT_ROOT / "data" / "shop.db").resolve().as_posix()
    assert not (tmp_path / "data").exists()
    owner.dispose()
    ro.dispose()


def test_readonly_blocks_writes(ro_engine):
    with pytest.raises(QueryError):
        run_readonly(ro_engine, "DELETE FROM orders", max_rows=10, timeout_ms=2000)
    r = run_readonly(ro_engine, "SELECT COUNT(*) AS n FROM orders", max_rows=10, timeout_ms=2000)
    assert r.rows[0][0] > 0


def test_timeout_aborts_long_query(ro_engine):
    slow = "SELECT COUNT(*) FROM orders a, order_items b, order_items c"
    with pytest.raises(QueryError, match="time limit"):
        run_readonly(ro_engine, slow, max_rows=10, timeout_ms=200)


def test_truncation(ro_engine):
    r = run_readonly(ro_engine, "SELECT order_id FROM orders", max_rows=5, timeout_ms=2000)
    assert len(r.rows) == 5 and r.truncated


def test_percent_signs_are_not_bind_params(ro_engine):
    sql = "SELECT COUNT(*) FROM orders WHERE status LIKE '%deliv%'"
    assert run_readonly(ro_engine, sql, max_rows=5, timeout_ms=2000).rows[0][0] > 0


def test_schema_description_mentions_tables_and_glossary(ro_engine):
    text = describe_schema(ro_engine)
    for t in ("customers", "products", "orders", "order_items", "BUSINESS DEFINITIONS", "Values: East"):
        assert t in text


def test_kpis(ro_engine):
    k = compute_kpis(ro_engine)
    assert k["revenue"] > 0 and k["orders"] > 0
    assert 0 < k["cancellation_rate"] < 1 and 0 < k["return_rate"] < 1
    assert len(k["monthly"]) == 24
    assert {r["region"] for r in k["by_region"]} == {"North", "South", "East", "West"}
    assert dialect_of(ro_engine) in {"sqlite", "postgres"}
