"""
Dashboard KPIs, computed with fixed SQL that follows the same definitions as the business glossary
(app/db/catalog.py), so the dashboard and the agent's answers always agree.

Usage:
    from app.analytics.kpis import compute_kpis
    kpis = compute_kpis(readonly_engine)   # dict served by GET /api/kpis
"""

from typing import Any

from sqlalchemy import Engine

from app.db.executor import run_readonly

# Shared SQL fragments (aliases: o = orders, oi = order_items).
REVENUE = "oi.quantity * oi.unit_price * (1 - oi.discount)"
VALID = "o.status IN ('delivered', 'shipped')"


def _month_expr(engine: Engine) -> str:
    """'YYYY-MM' bucket expression for the engine's dialect."""
    if engine.dialect.name == "postgresql":
        return "to_char(o.order_date, 'YYYY-MM')"
    return "strftime('%Y-%m', o.order_date)"


def _rows(engine: Engine, sql: str) -> list[dict[str, Any]]:
    """Run a KPI query read-only and return rows as dicts."""
    r = run_readonly(engine, sql, max_rows=1000, timeout_ms=10_000)
    return [dict(zip(r.columns, row, strict=True)) for row in r.rows]


def compute_kpis(engine: Engine) -> dict[str, Any]:
    """Headline numbers, monthly trend, and revenue by region and category."""
    month = _month_expr(engine)

    totals = _rows(
        engine,
        f"""
        SELECT ROUND(SUM({REVENUE}), 2) AS revenue,
               COUNT(DISTINCT o.order_id) AS orders,
               COUNT(DISTINCT o.customer_id) AS active_customers
        FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
        WHERE {VALID}""",
    )[0]

    rates = _rows(
        engine,
        """
        SELECT ROUND(1.0 * SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) / COUNT(*), 4)
                   AS cancellation_rate,
               ROUND(1.0 * SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END)
                     / SUM(CASE WHEN status IN ('delivered', 'returned') THEN 1 ELSE 0 END), 4)
                   AS return_rate
        FROM orders""",
    )[0]

    monthly = _rows(
        engine,
        f"""
        SELECT {month} AS month, ROUND(SUM({REVENUE}), 2) AS revenue, COUNT(DISTINCT o.order_id) AS orders
        FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
        WHERE {VALID} GROUP BY 1 ORDER BY 1""",
    )

    by_region = _rows(
        engine,
        f"""
        SELECT c.region, ROUND(SUM({REVENUE}), 2) AS revenue
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN customers c ON c.customer_id = o.customer_id
        WHERE {VALID} GROUP BY 1 ORDER BY 2 DESC""",
    )

    by_category = _rows(
        engine,
        f"""
        SELECT p.category, ROUND(SUM({REVENUE}), 2) AS revenue
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN products p ON p.product_id = oi.product_id
        WHERE {VALID} GROUP BY 1 ORDER BY 2 DESC""",
    )

    revenue = totals["revenue"] or 0
    last, prev = (monthly[-1], monthly[-2]) if len(monthly) >= 2 else (None, None)
    return {
        "revenue": revenue,
        "orders": totals["orders"],
        "aov": round(revenue / totals["orders"], 2) if totals["orders"] else 0,
        "active_customers": totals["active_customers"],
        "cancellation_rate": rates["cancellation_rate"],
        "return_rate": rates["return_rate"],
        "latest_month": last["month"] if last else None,
        "latest_month_revenue": last["revenue"] if last else None,
        "mom_change": round(last["revenue"] / prev["revenue"] - 1, 4) if last and prev and prev["revenue"] else None,
        "monthly": monthly,
        "by_region": by_region,
        "by_category": by_category,
    }
