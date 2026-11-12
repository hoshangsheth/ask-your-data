"""
Run the agent on the eval set and report accuracy, retries, latency, tokens and cost.

Uses whatever provider/models are configured (LLM_PROVIDER etc. in .env), so you can switch
provider, re-run, and compare. Every run calls the real model and costs money (~$0.10 for the
full set with the default Gemini models).

Item kinds (evals/questions.jsonl):
    single_turn     one question, scored by executing the agent's SQL vs the reference SQL
    follow_up       earlier "turns" are asked first in the same conversation; only the last
                    question is scored (tests that context like "same for 2024" is carried over)
    unanswerable    the agent must decline instead of inventing an answer

Usage (from the project root):
    python -m evals.run_eval                       # all questions -> metrics/eval.json
    python -m evals.run_eval --limit 5             # quick smoke run
    python -m evals.run_eval --out my.json         # custom report path
"""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from app.agent import SQLAgent
from app.core.config import get_settings
from app.db.engine import dialect_of, make_engines
from app.db.executor import run_readonly
from app.llm import build_llm
from app.sources import build_demo_source
from app.telemetry.metrics import percentile
from app.telemetry.pricing import estimate_cost_usd, price_table
from evals.dataset import category, load_questions, reference_sql
from evals.scoring import results_match

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "metrics" / "eval.json"


def _passes(item: dict, out: dict, ro_engine, dialect: str) -> bool:
    """Score one agent output against its eval item."""
    if item.get("unanswerable"):
        return out["status"] == "unanswerable"
    if out["status"] != "ok":
        return False
    ref = run_readonly(ro_engine, reference_sql(item, dialect), max_rows=1000, timeout_ms=10_000)
    return results_match(ref.rows, out["rows"])


def _run_item(agent: SQLAgent, item: dict, prices: dict) -> tuple[dict, list[dict]]:
    """Ask the item's earlier turns (if any), then its question. Returns (final output, all outputs)."""
    history: list[dict[str, str]] = []
    outputs = []
    for q in [*item.get("turns", []), item["question"]]:
        out = agent.ask(q, history=history)
        out["cost_usd"] = estimate_cost_usd(out["trace"], prices)
        outputs.append(out)
        if out["status"] == "ok":  # same rule as the app: only answered turns become context
            history = [*history, {"question": out["standalone_question"], "sql": out["sql"], "answer": out["answer"]}][
                -3:
            ]
    return outputs[-1], outputs


def summarize(results: list[dict], calls: list[dict], describe: dict, dialect: str, seconds: float) -> dict:
    n = len(results)
    passed = sum(r["pass"] for r in results)
    lat = [r["latency_ms"] for r in results]
    costs = [c["cost_usd"] for c in calls if c["cost_usd"] is not None]
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"questions": 0, "passed": 0})
        c["questions"] += 1
        c["passed"] += r["pass"]
    for c in by_cat.values():
        c["accuracy"] = round(c["passed"] / c["questions"], 4)
    return {
        **describe,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database": dialect,
        "questions": n,
        "passed": passed,
        "execution_accuracy": round(passed / n, 4) if n else 0,
        "first_try_accuracy": round(sum(r["pass"] and r["attempts"] <= 1 for r in results) / n, 4) if n else 0,
        "self_corrected": sum(r["attempts"] > 1 for r in results),
        "by_category": by_cat,
        "median_latency_ms": percentile(lat, 50),
        "p95_latency_ms": percentile(lat, 95),
        "model_calls": len(calls),
        "avg_input_tokens": round(sum(c["usage"]["input_tokens"] for c in calls) / len(calls)) if calls else 0,
        "avg_output_tokens": round(sum(c["usage"]["output_tokens"] for c in calls) / len(calls)) if calls else 0,
        "avg_cost_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "total_cost_usd": round(sum(costs), 4) if costs else None,
        "total_seconds": round(seconds, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the text-to-SQL agent.")
    parser.add_argument("--limit", type=int, default=0, help="only the first N questions")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="where to write the report")
    args = parser.parse_args()

    # Same wiring as the app, but without the HTTP layer.
    settings = get_settings()
    _, ro = make_engines(settings.database_url, settings.readonly_database_url)
    dialect = dialect_of(ro)
    llm = build_llm(settings)
    prices = price_table(settings.llm_prices)
    agent = SQLAgent(
        llm,
        build_demo_source(ro),
        max_rows=settings.max_rows,
        max_attempts=settings.max_attempts,
        timeout_ms=settings.query_timeout_ms,
    )

    items = load_questions()[: args.limit or None]
    results, calls = [], []
    started = time.perf_counter()
    for item in items:
        out, outs = _run_item(agent, item, prices)
        calls += outs
        ok = _passes(item, out, ro, dialect)
        results.append(
            {
                "id": item["id"],
                "category": category(item),
                "pass": ok,
                "status": out["status"],
                "attempts": out["attempts"],
                "latency_ms": out["latency_ms"],
                "cost_usd": out["cost_usd"],
                **out["usage"],
                "understood_as": out["standalone_question"],
                "sql": out["sql"],
            }
        )
        print(f"{'PASS' if ok else 'FAIL'}  {item['id']:<30} attempts={out['attempts']} {out['latency_ms']} ms")

    summary = summarize(results, calls, llm.describe(), dialect, time.perf_counter() - started)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
