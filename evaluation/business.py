"""
Business calculations: combines MEASURED results (evaluation/results/*.json, metrics/eval.json)
with explicit ASSUMPTIONS (below, editable) into time, effort and cost estimates.

Nothing here is a measured business outcome: there are no real customers yet. Every derived
number is labelled with the measurements and assumptions it depends on, and a low / mid / high
range shows how sensitive it is.

    python -m evaluation.business        -> evaluation/results/business.json
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from evaluation.server import RESULTS, ROOT

# ---- ASSUMPTIONS (not measured; change them to match a real team) -----------------------------
ASSUMPTIONS = {
    # Minutes for an analyst who knows SQL and the schema to answer one ad-hoc question by hand:
    # understand the request, find tables, write + debug SQL, check the result, make a chart, reply.
    "manual_minutes_per_question": {"low": 10, "mid": 20, "high": 45},
    # Minutes of human time with the app per question: type it, read the answer, glance at the SQL.
    "app_human_minutes_per_question": {"low": 0.5, "mid": 1.0, "high": 2.0},
    # Minutes to load a new file for analysis by hand (open, clean headers, fix types, import into a
    # database or BI tool) vs. the app's measured processing time plus ~1 minute of clicking.
    "manual_minutes_per_file_load": {"low": 10, "mid": 30, "high": 60},
    # Fully loaded analyst cost in INR per hour (salary + overhead); an assumption, not a market quote.
    "analyst_cost_inr_per_hour": {"low": 400, "mid": 700, "high": 1200},
    "usd_to_inr": 84.0,
    # Questions a team of business users asks per month.
    "questions_per_month": {"low": 200, "mid": 1000, "high": 5000},
    # Share of questions the app answers that a user accepts without an analyst (bounded above by
    # the measured accuracy; real acceptance is likely lower).
    "self_serve_share_of_correct": {"low": 0.6, "mid": 0.8, "high": 0.95},
}

# Manual workflow vs. the app, step by step (a process comparison, not a timing).
MANUAL_STEPS = [
    "Business user writes the request to an analyst (email / ticket)",
    "Analyst clarifies the question and definitions (e.g. what counts as revenue)",
    "Analyst finds the right tables and columns",
    "Analyst writes the SQL",
    "Analyst runs, debugs and fixes the SQL",
    "Analyst checks the numbers are plausible",
    "Analyst exports the result to a spreadsheet",
    "Analyst builds a chart",
    "Analyst writes a short summary of the finding",
    "Analyst sends the result back; follow-up questions restart the loop",
]
APP_STEPS = [
    "Business user types the question (or taps a suggestion)",
    "User reads the answer, chart and table (SQL shown for checking)",
    "Optional: export CSV / Excel / PDF in one click",
]
AUTOMATED = [
    "Schema lookup and business definitions (semantic layer sent with every question)",
    "SQL writing (LLM) and self-correction on errors",
    "Safety validation of the SQL and read-only execution",
    "Chart selection and plain-language summary",
    'Follow-up context ("same for 2024") without restating the question',
    "File import: format detection, header cleaning, number/date typing, table creation, profiling",
    "Report generation (PDF with chart, table and SQL) and spreadsheet export",
]


def load(name: str):
    path = (ROOT / "metrics" / "eval.json") if name == "eval" else RESULTS / f"{name}.json"
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def main() -> None:
    ev, func, ui, ai, db = (load(n) for n in ("eval", "functional", "ui_e2e", "ai_concurrency", "db_perf"))
    s = ev["summary"]
    measured = {
        "eval_accuracy": s["execution_accuracy"],
        "eval_questions": s["questions"],
        "answer_latency_p50_s": s["median_latency_ms"] / 1000,
        "answer_latency_p95_s": s["p95_latency_ms"] / 1000,
        "model_cost_usd_per_question": s["avg_cost_usd"],
        "functional_success_rate": func["success_rate"] if func else None,
        "ui_success_rate": ui["success_rate"] if ui else None,
        "upload_100k_rows_seconds": next(
            (r["seconds"] for r in (db or {}).get("upload_ingestion", []) if r["rows"] == 100_000), None
        ),
        "single_user_questions_per_minute": ai["waves"][0]["questions_per_minute"] if ai else None,
        "eight_user_questions_per_minute": ai["waves"][-1]["questions_per_minute"] if ai else None,
    }
    a = ASSUMPTIONS
    cost_per_question_inr = measured["model_cost_usd_per_question"] * a["usd_to_inr"]
    scenarios = {}
    for k in ("low", "mid", "high"):
        manual_min = a["manual_minutes_per_question"][k]
        app_min = a["app_human_minutes_per_question"][k] + measured["answer_latency_p50_s"] / 60
        saved_min = manual_min - app_min
        rate = a["analyst_cost_inr_per_hour"][k]
        q = a["questions_per_month"][k]
        self_serve = measured["eval_accuracy"] * a["self_serve_share_of_correct"][k]
        manual_cost = manual_min / 60 * rate
        app_cost = a["app_human_minutes_per_question"][k] / 60 * rate + cost_per_question_inr
        scenarios[k] = {
            "time_saved_per_question_pct": round(saved_min / manual_min * 100, 1),
            "minutes_saved_per_question": round(saved_min, 1),
            "manual_cost_inr_per_question": round(manual_cost, 1),
            "app_cost_inr_per_question": round(app_cost, 2),
            "cost_reduction_pct": round((manual_cost - app_cost) / manual_cost * 100, 1),
            "questions_per_month": q,
            "self_serve_share": round(self_serve, 3),
            "analyst_hours_saved_per_month": round(q * self_serve * saved_min / 60, 1),
            "net_saving_inr_per_month": round(q * self_serve * (manual_cost - app_cost), 0),
            "model_cost_inr_per_month": round(q * cost_per_question_inr, 0),
            "file_load_time_saved_pct": round(
                (a["manual_minutes_per_file_load"][k] - (1 + (measured["upload_100k_rows_seconds"] or 0) / 60))
                / a["manual_minutes_per_file_load"][k]
                * 100,
                1,
            ),
        }
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "measured": measured,
        "assumptions": ASSUMPTIONS,
        "process": {
            "manual_steps": MANUAL_STEPS,
            "app_steps": APP_STEPS,
            "steps_eliminated": len(MANUAL_STEPS) - len(APP_STEPS),
            "steps_eliminated_pct": round((len(MANUAL_STEPS) - len(APP_STEPS)) / len(MANUAL_STEPS) * 100, 1),
            "automated_tasks": AUTOMATED,
        },
        "model_cost_inr_per_question": round(cost_per_question_inr, 3),
        "scenarios": scenarios,
    }
    (RESULTS / "business.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"measured": measured, "scenarios": scenarios}, indent=2))


if __name__ == "__main__":
    main()
