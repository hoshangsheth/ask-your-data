"""
Page load timing with a per-resource breakdown (what makes the first load slow).

    python -m evaluation.page_load https://ask-your-data-chi.vercel.app [--runs 5]

Each run uses a fresh browser context (empty cache = a first visit); then 3 reloads in the last
context measure repeat visits. Records TTFB, first contentful paint, DOMContentLoaded, load, "app
ready" (questions rendered) and the slowest resources. Writes evaluation/results/page_load_<host>.json.
"""

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from evaluation.server import RESULTS

NAV = """() => { const n = performance.getEntriesByType('navigation')[0];
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  const res = performance.getEntriesByType('resource').map(r => ({ name: r.name.split('?')[0].slice(-70),
    host: new URL(r.name).host, ms: Math.round(r.duration), kb: Math.round(r.transferSize / 1024),
    blocking: r.renderBlockingStatus || '' }));
  return { ttfb: Math.round(n.responseStart), dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd),
    fcp: fcp ? Math.round(fcp.startTime) : null, resources: res }; }"""


def one(page, url: str) -> dict:
    t = time.perf_counter()
    page.goto(url + "/#ask", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_function("() => document.querySelectorAll('.pill').length > 0", timeout=90_000)
    ready = round((time.perf_counter() - t) * 1000)
    page.wait_for_load_state("load", timeout=90_000)
    d = page.evaluate(NAV)
    d["ready_ms"] = ready
    d["slowest"] = sorted(d.pop("resources"), key=lambda r: -r["ms"])[:6]
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    url = args.url.rstrip("/")
    cold, warm = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for i in range(args.runs):
            ctx = b.new_context(viewport={"width": 1366, "height": 860})
            ctx.add_init_script("localStorage.setItem('ayd-help-seen', '1')")
            page = ctx.new_page()
            cold.append(one(page, url))
            print("first visit", i + 1, {k: v for k, v in cold[-1].items() if k != "slowest"})
            if i == args.runs - 1:
                for j in range(3):
                    warm.append(one(page, f"{url}/?r={j}"))
                    print("repeat visit", j + 1, {k: v for k, v in warm[-1].items() if k != "slowest"})
            ctx.close()
        b.close()

    def agg(rows, key):
        vals = [r[key] for r in rows if r[key] is not None]
        return {"median": statistics.median(vals), "min": min(vals), "max": max(vals)} if vals else None

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": url,
        "first_visit": {k: agg(cold, k) for k in ("ttfb", "fcp", "dcl", "load", "ready_ms")},
        "repeat_visit": {k: agg(warm, k) for k in ("ttfb", "fcp", "dcl", "load", "ready_ms")},
        "slowest_resources_first_visit": cold[0]["slowest"],
        "runs": {"first_visit": cold, "repeat_visit": warm},
    }
    host = urlparse(url).hostname.replace(".", "_")
    (RESULTS / f"page_load_{host}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({k: report[k] for k in ("first_visit", "repeat_visit", "slowest_resources_first_visit")}, indent=1)
    )


if __name__ == "__main__":
    main()
