"""
AI answer quality and behaviour under concurrent users (real model; costs about $0.20).

    python -m evaluation.ai_quality

1. The evaluation set (evals/run_eval.py): 48 items with reference SQL or expected content ->
   metrics/eval.json (accuracy by category, latency, tokens, cost).
2. Concurrency: 1, 3, 5 and 8 simultaneous users each ask 2 different questions over HTTP on a
   local server -> latency, errors and time spent per agent step (model vs database).

Writes evaluation/results/ai_concurrency.json (and metrics/eval.json via the eval runner).
"""

import asyncio
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime

import httpx

from app.telemetry.metrics import percentile
from evaluation.server import RESULTS, ROOT, running_server

QUESTIONS = [
    "Top 5 products by revenue in 2025",
    "Revenue by region in 2025",
    "What is the cancellation rate for each payment method?",
    "Average order value by channel in 2025",
    "How many customers signed up each month in 2025?",
    "Which category had the highest gross margin in 2025?",
    "What is this data about?",
    "Show monthly revenue for 2024",
]


async def wave(base: str, users: int) -> dict:
    results = []

    async def user(n: int) -> None:
        async with httpx.AsyncClient(base_url=base, timeout=180) as c:
            for k in range(2):
                q = QUESTIONS[(n * 2 + k) % len(QUESTIONS)]
                t = time.perf_counter()
                try:
                    r = await c.post("/api/ask", json={"question": q})
                    body = r.json() if r.status_code == 200 else {}
                    results.append(
                        {
                            "status_code": r.status_code,
                            "status": body.get("status"),
                            "ms": (time.perf_counter() - t) * 1000,
                            "trace": body.get("trace", []),
                            "cost": body.get("cost_usd"),
                        }
                    )
                except httpx.HTTPError as e:
                    results.append(
                        {
                            "status_code": 0,
                            "status": type(e).__name__,
                            "ms": (time.perf_counter() - t) * 1000,
                            "trace": [],
                            "cost": None,
                        }
                    )

    started = time.perf_counter()
    await asyncio.gather(*(user(n) for n in range(users)))
    elapsed = time.perf_counter() - started
    ms = [r["ms"] for r in results]
    steps: dict[str, list[float]] = {}
    for r in results:
        for s in r["trace"]:
            steps.setdefault(s["step"], []).append(s["ms"])
    ok = [r for r in results if r["status_code"] == 200 and r["status"] in ("ok", "unanswerable")]
    return {
        "users": users,
        "questions": len(results),
        "answered": sum(r["status"] == "ok" for r in results),
        "http_errors": sum(r["status_code"] != 200 for r in results),
        "success_rate": round(len(ok) / len(results), 4),
        "wall_seconds": round(elapsed, 1),
        "questions_per_minute": round(len(results) / elapsed * 60, 1),
        "latency_ms": {
            "avg": round(statistics.mean(ms)),
            "p50": round(percentile(ms, 50)),
            "p95": round(percentile(ms, 95)),
            "max": round(max(ms)),
        },
        "avg_step_ms": {k: round(statistics.mean(v)) for k, v in steps.items()},
        "avg_cost_usd": round(statistics.mean([r["cost"] for r in results if r["cost"] is not None]), 6),
    }


def main() -> None:
    print("== evaluation set ==")
    subprocess.run([sys.executable, "-m", "evals.run_eval"], cwd=ROOT, check=False)

    print("\n== concurrent users ==")
    with running_server(port=8015) as srv:
        waves = []
        for users in (1, 3, 5, 8):
            w = asyncio.run(wave(srv.url, users))
            print(json.dumps({k: v for k, v in w.items()}, default=str))
            waves.append(w)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": "local uvicorn + real Gemini",
        "waves": waves,
    }
    (RESULTS / "ai_concurrency.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
