"""
Load-test a deployment's API and write metrics/loadtest.json (shown on the Metrics page).

Only endpoints that don't call the AI model are hit (health, dataset list, schema, dashboard
KPIs), so a run costs nothing; question latency is measured separately by the eval and the
question log.

Usage (from the project root):
    python -m scripts.loadtest https://ask-your-data-chi.vercel.app --requests 400 --concurrency 20

Reports per endpoint and overall: requests, errors, throughput (req/s) and latency p50/p95/p99.
"""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.telemetry.metrics import percentile

ENDPOINTS = ["/api/health", "/api/datasets", "/api/schema?dataset=demo", "/api/kpis"]
OUT = Path(__file__).resolve().parents[1] / "metrics" / "loadtest.json"


async def run(base: str, total: int, concurrency: int) -> dict:
    results: list[tuple[str, float, bool]] = []
    queue: asyncio.Queue[str] = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(ENDPOINTS[i % len(ENDPOINTS)])

    async with httpx.AsyncClient(base_url=base, timeout=30, headers={"User-Agent": "ayd-loadtest"}) as client:
        for path in ENDPOINTS:  # warm up: cold starts are not what this measures
            await client.get(path)

        async def worker() -> None:
            while not queue.empty():
                path = queue.get_nowait()
                t = time.perf_counter()
                try:
                    ok = (await client.get(path)).status_code == 200
                except httpx.HTTPError:
                    ok = False
                results.append((path, (time.perf_counter() - t) * 1000, ok))

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        elapsed = time.perf_counter() - started

    def stats(rows: list[tuple[str, float, bool]], seconds: float) -> dict:
        ms = [r[1] for r in rows]
        return {
            "requests": len(rows),
            "errors": sum(not r[2] for r in rows),
            "error_rate": round(sum(not r[2] for r in rows) / len(rows), 4) if rows else 0,
            "rps": round(len(rows) / seconds, 1),
            "p50_ms": round(percentile(ms, 50), 1),
            "p95_ms": round(percentile(ms, 95), 1),
            "p99_ms": round(percentile(ms, 99), 1),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": base,
        "requests": total,
        "concurrency": concurrency,
        "duration_s": round(elapsed, 2),
        "overall": stats(results, elapsed),
        "by_endpoint": {p: stats([r for r in results if r[0] == p], elapsed) for p in ENDPOINTS},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load-test the API (no AI calls).")
    parser.add_argument("base_url")
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    report = asyncio.run(run(args.base_url.rstrip("/"), args.requests, args.concurrency))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
