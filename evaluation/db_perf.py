"""
Database and data-processing performance (no AI, no server):

    - demo store size and dashboard KPI time (6 aggregate queries)
    - every eval reference query (realistic analytical SQL), 10 runs each, read-only executor
    - SQL guard (safety check) cost per query
    - upload ingestion speed: CSV files of 10K / 100K / 500K rows and an Excel file, end to end
      (read -> clean -> profile -> store)

    python -m evaluation.db_perf          -> evaluation/results/db_perf.json
"""

import io
import json
import shutil
import statistics
import time
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import func, select

from app.analytics.kpis import compute_kpis
from app.datasets.service import DatasetService
from app.datasets.store import LocalDatasetStore
from app.db.engine import dialect_of, make_engines
from app.db.executor import run_readonly
from app.db.models import ALLOWED_TABLES, metadata
from app.db.seed import seed
from app.sql.guard import validate_sql
from app.telemetry.metrics import percentile
from evals.dataset import load_questions, reference_sql
from evaluation.server import EVAL_DATA, RESULTS


def timed(fn, n: int) -> list[float]:
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def stats(ms: list[float]) -> dict:
    return {
        "n": len(ms),
        "avg_ms": round(statistics.mean(ms), 2),
        "p50_ms": round(percentile(ms, 50), 2),
        "p95_ms": round(percentile(ms, 95), 2),
        "max_ms": round(max(ms), 2),
    }


def synthetic(rows: int) -> pd.DataFrame:
    regions = ["North", "South", "East", "West"]
    return pd.DataFrame(
        {
            "order_id": range(1, rows + 1),
            "order_date": pd.date_range("2024-01-01", periods=rows, freq="min").strftime("%Y-%m-%d"),
            "region": [regions[i % 4] for i in range(rows)],
            "product": [f"Product {i % 250}" for i in range(rows)],
            "quantity": [(i % 7) + 1 for i in range(rows)],
            "amount": [round(((i * 37) % 5000) + 99.5, 2) for i in range(rows)],
        }
    )


def main() -> None:
    folder = EVAL_DATA / "dbperf"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    owner, ro = make_engines(f"sqlite:///{(folder / 'shop.db').as_posix()}")
    t = time.perf_counter()
    seed(owner, force=True)
    seed_s = time.perf_counter() - t
    dialect = dialect_of(ro)
    with ro.connect() as conn:
        sizes = {
            tb.name: conn.execute(select(func.count()).select_from(tb)).scalar_one() for tb in metadata.sorted_tables
        }

    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "database": "SQLite (local file)"}
    report["demo_store"] = {"rows": sizes, "total_rows": sum(sizes.values()), "seed_seconds": round(seed_s, 2)}
    print("demo store:", report["demo_store"])

    compute_kpis(ro)  # warm the page cache
    report["dashboard_kpis"] = stats(timed(lambda: compute_kpis(ro), 20))
    print("dashboard KPIs:", report["dashboard_kpis"])

    per_query, guard_us = {}, []
    for item in [q for q in load_questions() if "sql" in q]:
        sql = reference_sql(item, dialect)
        run_readonly(ro, sql, max_rows=1000, timeout_ms=10_000)  # warm
        per_query[item["id"]] = stats(
            timed(lambda sql=sql: run_readonly(ro, sql, max_rows=1000, timeout_ms=10_000), 10)
        )
        g = timed(lambda sql=sql: validate_sql(sql, dialect=dialect, allowed_tables=ALLOWED_TABLES, max_rows=500), 50)
        guard_us.append(statistics.mean(g) * 1000)
    p50s = [v["p50_ms"] for v in per_query.values()]
    report["analytical_queries"] = {
        "queries": len(per_query),
        "median_of_p50_ms": round(statistics.median(p50s), 2),
        "p95_of_p50_ms": round(percentile(p50s, 95), 2),
        "slowest": max(per_query.items(), key=lambda kv: kv[1]["p50_ms"])[0],
        "slowest_p50_ms": max(p50s),
        "under_50ms": sum(p < 50 for p in p50s),
        "under_100ms": sum(p < 100 for p in p50s),
        "per_query": per_query,
    }
    report["sql_guard"] = {
        "queries": len(guard_us),
        "avg_us": round(statistics.mean(guard_us), 1),
        "max_us": round(max(guard_us), 1),
    }
    print("analytical queries:", {k: v for k, v in report["analytical_queries"].items() if k != "per_query"})
    print("sql guard:", report["sql_guard"])

    store = LocalDatasetStore(folder / "uploads")
    service = DatasetService(store, max_upload_mb=200)
    ingest = []
    for rows in (10_000, 100_000, 500_000):
        data = synthetic(rows).to_csv(index=False).encode()
        t = time.perf_counter()
        meta = service.ingest(data, f"orders_{rows}.csv")
        s = time.perf_counter() - t
        ingest.append(
            {
                "format": "csv",
                "rows": rows,
                "mb": round(len(data) / 1_048_576, 2),
                "seconds": round(s, 2),
                "rows_per_s": round(rows / s),
                "mb_per_s": round(len(data) / 1_048_576 / s, 2),
            }
        )
        store.delete(meta.id)
        print("ingest:", ingest[-1])
    buf = io.BytesIO()
    synthetic(50_000).to_excel(buf, index=False)
    data = buf.getvalue()
    t = time.perf_counter()
    meta = service.ingest(data, "orders_50000.xlsx")
    s = time.perf_counter() - t
    ingest.append(
        {
            "format": "xlsx",
            "rows": 50_000,
            "mb": round(len(data) / 1_048_576, 2),
            "seconds": round(s, 2),
            "rows_per_s": round(50_000 / s),
            "mb_per_s": round(len(data) / 1_048_576 / s, 2),
        }
    )
    store.delete(meta.id)
    print("ingest:", ingest[-1])
    report["upload_ingestion"] = ingest
    owner.dispose()
    ro.dispose()
    (RESULTS / "db_perf.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
