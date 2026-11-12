"""
SQL guard (app/sql/guard.py): what is allowed, what is rejected, and LIMIT enforcement.
"""

import pytest

from app.db.models import ALLOWED_TABLES
from app.sql.guard import SQLValidationError, validate_sql


def check(sql: str, dialect: str = "sqlite", max_rows: int = 100):
    return validate_sql(sql, dialect=dialect, allowed_tables=ALLOWED_TABLES, max_rows=max_rows)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT region, COUNT(*) FROM customers GROUP BY region",
        "WITH r AS (SELECT order_id FROM orders WHERE status = 'delivered') SELECT COUNT(*) FROM r",
        "SELECT o.order_id FROM orders o JOIN order_items oi ON oi.order_id = o.order_id LIMIT 10",
        "SELECT city FROM customers UNION SELECT category FROM products",
        "SELECT product_name, RANK() OVER (ORDER BY unit_price DESC) AS rk FROM products",
        "select * from orders where status like '%ship%';",
    ],
)
def test_allows_read_only_queries(sql):
    assert check(sql).sql


@pytest.mark.parametrize(
    "sql, fragment",
    [
        ("DELETE FROM orders", "only read-only"),
        ("UPDATE orders SET status = 'x'", "only read-only"),
        ("DROP TABLE orders", "only read-only"),
        ("INSERT INTO orders (order_id) VALUES (1)", "only read-only"),
        ("SELECT 1 FROM orders; DROP TABLE orders", "exactly one"),
        ("PRAGMA table_info(orders)", ""),
        ("SELECT * FROM users", "unknown table"),
        ("SELECT * FROM sqlite_master", "unknown table"),
        ("SELECT * FROM information_schema.tables", "schema-qualified"),
        ("SELECT * FROM pg_catalog.pg_user", "schema-qualified"),
        ("SELECT 1", "at least one"),
        ("", "empty"),
        ("SELEC * FRM orders", ""),
    ],
)
def test_rejects_unsafe_or_invalid(sql, fragment):
    with pytest.raises(SQLValidationError) as e:
        check(sql)
    assert fragment in str(e.value)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(10) FROM orders",
        "SELECT pg_read_file('/etc/passwd') FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * INTO backup FROM orders",
    ],
)
def test_rejects_dangerous_postgres(sql):
    with pytest.raises(SQLValidationError):
        check(sql, dialect="postgres")


def test_adds_limit_when_missing():
    v = check("SELECT * FROM orders", max_rows=50)
    assert v.limit_applied and "LIMIT 50" in v.sql


def test_clamps_large_limit():
    v = check("SELECT * FROM orders LIMIT 100000", max_rows=50)
    assert v.limit_applied and "LIMIT 50" in v.sql and "100000" not in v.sql


def test_keeps_small_limit():
    v = check("SELECT * FROM orders LIMIT 5", max_rows=50)
    assert not v.limit_applied and "LIMIT 5" in v.sql


def test_limits_union():
    v = check("SELECT city FROM customers UNION SELECT category FROM products", max_rows=7)
    assert "LIMIT 7" in v.sql


def test_cte_names_are_not_tables():
    v = check("WITH big AS (SELECT * FROM orders) SELECT COUNT(*) FROM big")
    assert v.tables == ["orders"]
