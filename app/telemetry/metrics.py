"""
Live metrics, computed from the question log and upload events.

    compute_live_metrics(engine) -> dict      (served by GET /api/metrics)

Covers outcome rates, first-try vs self-corrected answers, latency percentiles (total and per
step), tokens and cost, user feedback, follow-up usage, daily volume and upload processing.
Aggregation is done in Python over the most recent rows, which is plenty at portfolio scale and
works the same on SQLite and Postgres.
"""

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, select

from app.db.app_tables import questions, usage_events, users

MAX_ROWS = 50_000  # most recent questions considered
LATENCY_BUCKETS_S = [1, 2, 3, 5, 8, 13, 20, 30]  # histogram upper bounds (seconds); last bucket is open


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (p in 0..100); None for no data."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1))
    return s[k]


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _as_utc(ts: Any) -> datetime:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)  # SQLite returns naive UTC timestamps


def _question_metrics(rows: list[Any], now: datetime) -> dict[str, Any]:
    n = len(rows)
    ok = [r for r in rows if r.status == "ok"]
    status = Counter(r.status for r in rows)
    latency = [r.latency_ms for r in rows]
    costs = [r.cost_usd for r in rows if r.cost_usd is not None]
    rated = [r for r in rows if r.feedback in (1, -1)]
    follow = [r for r in rows if r.is_follow_up]

    hist = [0] * (len(LATENCY_BUCKETS_S) + 1)
    for ms in latency:
        i = next((i for i, b in enumerate(LATENCY_BUCKETS_S) if ms <= b * 1000), len(LATENCY_BUCKETS_S))
        hist[i] += 1

    days: dict[str, list[Any]] = defaultdict(list)
    start = (now - timedelta(days=29)).date()
    for r in rows:
        d = _as_utc(r.created_at).date()
        if d >= start:
            days[d.isoformat()].append(r)
    daily = []
    for i in range(30):
        d = (start + timedelta(days=i)).isoformat()
        day = days.get(d, [])
        daily.append(
            {
                "date": d,
                "questions": len(day),
                "answered": sum(r.status == "ok" for r in day),
                "p50_latency_ms": percentile([r.latency_ms for r in day], 50),
            }
        )

    by_kind = {}
    for kind in ("demo", "upload"):
        sub = [r for r in rows if r.dataset_kind == kind]
        by_kind[kind] = {"questions": len(sub), "answer_rate": _rate(sum(r.status == "ok" for r in sub), len(sub))}

    return {
        "questions": n,
        "conversations": len({r.conversation_id for r in rows}),
        "signed_in_users": len({r.user_id for r in rows if r.user_id}),
        "guests": len({r.guest_id for r in rows if r.guest_id and not r.user_id}),
        "outcomes": {
            "answered": status.get("ok", 0),
            "unanswerable": status.get("unanswerable", 0),
            "failed": status.get("failed", 0),
            "answer_rate": _rate(status.get("ok", 0), n),
            "decline_rate": _rate(status.get("unanswerable", 0), n),
            "failure_rate": _rate(status.get("failed", 0), n),
            "first_try_rate": _rate(sum(r.attempts == 1 for r in ok), n),
            # answered from the schema without SQL ("what columns are there?", "what is AOV?")
            "about_data": sum(bool(getattr(r, "about_data", False)) for r in ok),
            "about_data_share": _rate(sum(bool(getattr(r, "about_data", False)) for r in ok), n),
            "self_corrected": sum(r.attempts > 1 for r in ok),
            "self_correction_share_of_answers": _rate(sum(r.attempts > 1 for r in ok), len(ok)),
            "avg_attempts": _avg([r.attempts for r in rows if r.attempts]),
        },
        "latency_ms": {
            "p50": percentile(latency, 50),
            "p90": percentile(latency, 90),
            "p95": percentile(latency, 95),
            "p99": percentile(latency, 99),
            "avg_by_step": {
                "write_sql": _avg([r.sql_ms for r in rows]),
                "safety_check": _avg([r.validate_ms for r in rows]),
                "run_query": _avg([r.execute_ms for r in rows]),
                "write_answer": _avg([r.summary_ms for r in ok]),
            },
            "histogram": {
                "buckets_s": LATENCY_BUCKETS_S,
                "counts": hist,  # last count = slower than the last bucket
            },
        },
        "tokens": {
            "avg_input": _avg([r.input_tokens for r in rows]),
            "avg_output": _avg([r.output_tokens for r in rows]),
            "total": sum(r.input_tokens + r.output_tokens for r in rows),
        },
        "cost_usd": {
            "total": round(sum(costs), 4) if costs else 0.0,
            "avg_per_question": round(sum(costs) / len(costs), 6) if costs else None,
            "per_1000_questions": round(1000 * sum(costs) / len(costs), 2) if costs else None,
        },
        "feedback": {
            "rated": len(rated),
            "helpful": sum(r.feedback == 1 for r in rated),
            "not_helpful": sum(r.feedback == -1 for r in rated),
            "satisfaction": _rate(sum(r.feedback == 1 for r in rated), len(rated)),
            "rating_rate": _rate(len(rated), n),
        },
        "follow_ups": {
            "questions": len(follow),
            "share": _rate(len(follow), n),
            "answer_rate": _rate(sum(r.status == "ok" for r in follow), len(follow)),
        },
        "by_dataset": by_kind,
        "models": dict(Counter(r.sql_model for r in rows if r.sql_model)),
        "daily": daily,
    }


def _upload_metrics(rows: list[Any]) -> dict[str, Any]:
    data = [r.data for r in rows if isinstance(r.data, dict)]
    ms = [d.get("processing_ms", 0) for d in data]
    return {
        "uploads": len(data),
        "rows_ingested": sum(d.get("rows", 0) for d in data),
        "tables_created": sum(d.get("tables", 0) for d in data),
        "total_mb": round(sum(d.get("size_bytes", 0) for d in data) / 1_048_576, 2),
        "avg_mb": round(sum(d.get("size_bytes", 0) for d in data) / 1_048_576 / len(data), 2) if data else None,
        "processing_ms": {"p50": percentile(ms, 50), "p95": percentile(ms, 95)},
        "rows_per_second": round(sum(d.get("rows", 0) for d in data) / (sum(ms) / 1000), 0) if sum(ms) else None,
        "formats": dict(Counter(d.get("format", "?") for d in data)),
    }


def compute_live_metrics(engine: Engine, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    q_cols = [
        questions.c[c]
        for c in [
            "created_at",
            "user_id",
            "guest_id",
            "conversation_id",
            "dataset_kind",
            "status",
            "attempts",
            "latency_ms",
            "sql_ms",
            "validate_ms",
            "execute_ms",
            "summary_ms",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "feedback",
            "is_follow_up",
            "sql_model",
        ]
    ]
    with engine.connect() as conn:
        # about_data: answered without SQL (a question about the dataset itself)
        about = ((questions.c.status == "ok") & (questions.c.sql == "")).label("about_data")
        q_rows = conn.execute(select(*q_cols, about).order_by(questions.c.created_at.desc()).limit(MAX_ROWS)).all()
        u_rows = conn.execute(select(usage_events.c.data).where(usage_events.c.kind == "upload")).all()
        accounts = conn.execute(select(func.count()).select_from(users)).scalar_one()
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "accounts": accounts,
        **_question_metrics(q_rows, now),
        "uploads": _upload_metrics(u_rows),
    }
