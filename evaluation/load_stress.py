"""
Load and stress tests (endpoints that do not call the AI model, so they cost nothing).

    python -m evaluation.load_stress local         # baseline + step load to the breaking point
    python -m evaluation.load_stress production URL  # gentle read-only step load on the deployment

Local: one uvicorn process (like one serverless instance) on an isolated SQLite database; the
load generator runs on the same machine, so both compete for its 4 logical CPUs. Steps raise the
number of concurrent virtual users until the error rate passes 1% or p95 passes 2 s.

Production: read-only GETs only (no writes, no AI), concurrency up to 50, 10 s per step.
Writes evaluation/results/load_local.json or load_production.json.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime

from evaluation.loadgen import Sampler, run_for
from evaluation.server import RESULTS, all_processes, running_server

ENDPOINTS = ["/api/health", "/api/datasets", "/api/schema?dataset=demo", "/api/kpis"]
STATIC = ["/", "/static/js/ask.js", "/static/css/components.css"]
LOCAL_STEPS = [1, 5, 10, 25, 50, 100, 200, 400]
PROD_STEPS = [1, 5, 10, 25, 50]
BREAK_ERROR_RATE = 0.01
BREAK_P95_MS = 2000


async def baseline(base: str, sampler_procs=None) -> dict:
    """One request at a time per endpoint: the unloaded response time of each endpoint."""
    out = {}
    for e in ENDPOINTS + STATIC:
        r = await run_for(base, [e], concurrency=1, seconds=6)
        out[e] = {k: r[k] for k in ("requests", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "error_rate")}
        print(f"baseline {e:<28} n={r['requests']:<5} avg={r['avg_ms']} p95={r['p95_ms']} ms")
    return out


LIGHT = ["/api/health", "/api/datasets", "/api/schema?dataset=demo"]  # without the dashboard KPIs


async def steps(
    base: str, levels: list[int], seconds: float, procs=None, stop_on_break: bool = True, endpoints=ENDPOINTS
) -> list[dict]:
    out = []
    for c in levels:
        sampler = Sampler(procs) if procs else None
        r = await run_for(base, endpoints, concurrency=c, seconds=seconds, sampler=sampler, timeout=30)
        broke = r["error_rate"] > BREAK_ERROR_RATE or (r["p95_ms"] or 0) > BREAK_P95_MS
        r["breaking_point"] = broke
        res = r.get("resources", {})
        print(
            f"c={c:<4} rps={r['rps']:<7} p50={r['p50_ms']:<8} p95={r['p95_ms']:<8} p99={r['p99_ms']:<8} "
            f"err={r['error_rate']:.2%} cpu={res.get('server_cpu_pct_avg', '-')}% rss={res.get('server_rss_mb_max', '-')}MB"
            f"{'  <- breaking point' if broke else ''}"
        )
        out.append(r)
        if broke and stop_on_break:
            break
    return out


def max_stable(results: list[dict]) -> dict | None:
    stable = [r for r in results if not r["breaking_point"]]
    return max(stable, key=lambda r: r["rps"]) if stable else None


def local() -> None:
    with running_server(port=8013) as srv:
        procs = all_processes(srv)
        idle = Sampler(procs)
        idle.prime()
        asyncio.run(asyncio.sleep(3))
        idle.sample()
        report = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "target": "local uvicorn, 1 process, SQLite",
            "server_startup_s": srv.startup_s,
            "idle_resources": idle.summary(),
            "baseline": asyncio.run(baseline(srv.url)),
        }
        print("-- scenario: mixed (health, datasets, schema, dashboard KPIs)")
        report["steps"] = asyncio.run(steps(srv.url, LOCAL_STEPS, seconds=15, procs=procs))
        print("-- scenario: light (without the dashboard KPIs)")
        report["steps_light"] = asyncio.run(steps(srv.url, LOCAL_STEPS, seconds=15, procs=procs, endpoints=LIGHT))
        for key in ("steps", "steps_light"):
            best = max_stable(report[key])
            report[f"max_stable_{key}"] = (
                {k: best[k] for k in ("concurrency", "rps", "p95_ms", "error_rate")} if best else None
            )
            report[f"breaking_{key}"] = next((r["concurrency"] for r in report[key] if r["breaking_point"]), None)
        report["break_rule"] = f"error rate > {BREAK_ERROR_RATE:.0%} or p95 > {BREAK_P95_MS} ms"
    (RESULTS / "load_local.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def production(url: str) -> None:
    url = url.rstrip("/")
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": url,
        "note": "read-only GETs, no AI calls; client in India, deployment in Washington DC (iad1)",
        "baseline": asyncio.run(baseline(url)),
        "steps": asyncio.run(steps(url, PROD_STEPS, seconds=10, stop_on_break=False)),
    }
    best = max_stable(report["steps"])
    report["max_stable"] = {k: best[k] for k in ("concurrency", "rps", "p95_ms", "error_rate")} if best else None
    (RESULTS / "load_production.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:2] == ["production"]:
        production(sys.argv[2])
    else:
        local()
