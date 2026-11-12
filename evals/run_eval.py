"""
Run the agent on the eval set and report execution accuracy, retries, latency and tokens.

Uses whatever provider/models are configured (LLM_PROVIDER etc. in .env), so you can switch
provider, re-run, and compare. Every run calls the real model and costs money.

Usage (from the project root):
    python -m evals.run_eval                 # all questions
    python -m evals.run_eval --limit 5       # quick smoke run
    python -m evals.run_eval --out my.json   # custom report path
"""

import argparse
import json
import time
from pathlib import Path

from app.agent import SQLAgent
from app.core.config import get_settings
from app.db.engine import dialect_of, make_engines
from app.db.executor import run_readonly
from app.llm import build_llm
from evals.dataset import load_questions, reference_sql
from evals.scoring import results_match


def _passes(item: dict, out: dict, ro_engine, dialect: str) -> bool:
    """Score one agent output against its eval item."""
    if item.get("unanswerable"):
        return out["status"] == "unanswerable"
    if out["status"] != "ok":
        return False
    ref = run_readonly(ro_engine, reference_sql(item, dialect), max_rows=1000, timeout_ms=10_000)
    return results_match(ref.rows, out["rows"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the text-to-SQL agent.")
    parser.add_argument("--limit", type=int, default=0, help="only the first N questions")
    parser.add_argument("--out", default="evals/results.json", help="where to write the report")
    args = parser.parse_args()

    # Same wiring as the app, but without the HTTP layer.
    settings = get_settings()
    _, ro = make_engines(settings.database_url, settings.readonly_database_url)
    dialect = dialect_of(ro)
    llm = build_llm(settings)
    agent = SQLAgent(
        llm, ro, max_rows=settings.max_rows, max_attempts=settings.max_attempts, timeout_ms=settings.query_timeout_ms
    )

    items = load_questions()[: args.limit or None]
    results, passed = [], 0
    started = time.perf_counter()
    for item in items:
        out = agent.ask(item["question"])
        ok = _passes(item, out, ro, dialect)
        passed += ok
        results.append(
            {
                "id": item["id"],
                "pass": ok,
                "status": out["status"],
                "attempts": out["attempts"],
                "latency_ms": out["latency_ms"],
                **out["usage"],
                "sql": out["sql"],
            }
        )
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']:<28} attempts={out['attempts']} {out['latency_ms']} ms")

    n = len(items)
    summary = {
        **llm.describe(),
        "database": dialect,
        "questions": n,
        "passed": passed,
        "execution_accuracy": round(passed / n, 4) if n else 0,
        "self_corrected": sum(r["attempts"] > 1 for r in results),
        "median_latency_ms": sorted(r["latency_ms"] for r in results)[n // 2] if n else 0,
        "total_seconds": round(time.perf_counter() - started, 1),
        # Multiply by your provider's per-token prices to get the cost per question.
        "avg_input_tokens": round(sum(r["input_tokens"] for r in results) / n) if n else 0,
        "avg_output_tokens": round(sum(r["output_tokens"] for r in results) / n) if n else 0,
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
