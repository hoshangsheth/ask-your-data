"""
Soak test: constant moderate load for N minutes; checks stability (errors, latency drift) and
memory growth of the server process.

    python -m evaluation.soak --minutes 10 --concurrency 5

Mixed non-AI endpoints (incl. the dashboard KPIs) on one local uvicorn process.
Writes evaluation/results/soak.json.
"""

import argparse
import asyncio
import json
import statistics
from datetime import UTC, datetime

from evaluation.load_stress import ENDPOINTS
from evaluation.loadgen import Sampler, run_for
from evaluation.server import RESULTS, all_processes, running_server


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()
    with running_server(port=8014) as srv:
        sampler = Sampler(all_processes(srv))
        r = asyncio.run(
            run_for(srv.url, ENDPOINTS, args.concurrency, args.minutes * 60, sampler=sampler, per_minute=True)
        )
        rss = sampler.rss_mb
        n = max(1, len(rss) // 10)  # first and last tenth of the run
        first, last = statistics.mean(rss[:n]), statistics.mean(rss[-n:])
        exited = srv.process.poll() if hasattr(srv.process, "poll") else None
        report = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "minutes": args.minutes,
            "concurrency": args.concurrency,
            **{
                k: r[k]
                for k in ("requests", "errors", "error_rate", "rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms")
            },
            "resources": r["resources"],
            "memory_mb_first_10pct": round(first, 1),
            "memory_mb_last_10pct": round(last, 1),
            "memory_growth_mb": round(last - first, 1),
            "memory_samples": len(rss),
            "server_still_running": srv.process.is_running() and exited is None,
            "per_minute": r["per_minute"],
        }
    (RESULTS / "soak.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_minute"}, indent=2))
    for m in report["per_minute"]:
        print(f"minute {m['minute']:>2}: {m['requests']} req, p95 {m['p95_ms']} ms, errors {m['errors']}")


if __name__ == "__main__":
    main()
