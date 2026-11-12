# Metrics

> **Latest full evaluation (12 Nov 2026):** [EVALUATION_REPORT.md](../EVALUATION_REPORT.md) supersedes the
> figures below: 48-item eval 97.9%, 191 tests (87.5% coverage), functional, browser, load, stress,
> soak and business analysis, with raw results in [`evaluation/results/`](../evaluation/results).

What was measured, how, and the latest numbers. Every number here is reproducible with the
command next to it; the raw reports are in [`metrics/`](../metrics) and the live numbers are on
the app's **Metrics** page (`/#metrics`, data from `GET /api/metrics`).

## 1. Answer quality: offline evaluation

`python -m evals.run_eval` → [`metrics/eval.json`](../metrics/eval.json)

41 hand-written items with reference SQL, run against the demo store (SQLite) with the deployed
configuration: `gemini-3.8-flash` writes SQL, `gemini-3.5-flash-lite` writes the answer, reasoning
"low". An item passes when executing the agent's SQL returns the same values as the reference
(order-insensitive, numeric tolerance, extra columns allowed).

| Metric | Result (12 Nov 2026) |
|---|---|
| **Execution accuracy** | **97.6%** (40 / 41) |
| Single questions | 96.6% (28 / 29) |
| **Follow-up questions** (multi-turn, incl. one 3-turn conversation) | **100%** (10 / 10) |
| Unanswerable questions correctly declined | 100% (2 / 2) |
| Correct on the first attempt | 97.6% |
| Latency, question → answer (p50 / p95) | 4.3 s / 5.4 s |
| Tokens per model call (avg in / out) | 1,886 / 247 |
| **Cost per question** | **$0.0020** (≈ ₹0.17); whole 52-call run $0.10 |

The one miss (`quarterly_revenue_2025`) returned the right revenue for every quarter but labelled
them `2025-Q1…` where the reference uses `Q1…`; the scorer compares labels strictly, and the
reported number keeps that strictness rather than changing the benchmark after the fact.

Follow-up items ask the earlier turns first in the same conversation and score only the last
answer, e.g. *"Top 5 products by revenue in 2025"* → *"Show the top 10 instead"*, or
*"Revenue by region in 2025"* → *"Which region was highest?"* → *"Break its revenue down by category"*.

## 2. Live usage: production telemetry

`GET /api/metrics` (computed from the `questions` and `usage_events` tables)

Every question asked on the deployment is logged with: status, attempts, per-step timings
(write SQL, safety check, run query, write answer), input/output tokens, estimated cost from the
model price table, whether it was a follow-up, and 👍/👎 feedback. Uploads are logged with size,
rows, tables and processing time. The Metrics page shows:

| Metric | Definition |
|---|---|
| Answer rate / decline rate / failure rate | share of questions answered / declined as not answerable / failed after 3 attempts |
| First-try rate, self-corrected | answered without / with a retry after a validation or database error |
| Latency p50 / p90 / p95 / p99 | end-to-end time per question, plus average time per agent step and a histogram |
| Cost per question, per 1,000 questions, total | tokens × model price (USD per 1M tokens, `app/telemetry/pricing.py`) |
| Satisfaction | 👍 / (👍 + 👎); rating rate = rated / all questions |
| Follow-up share and answer rate | questions that continued a conversation |
| Uploads | count, rows ingested, size, processing time p50 / p95, rows per second, formats |
| Volume | questions, conversations, accounts, signed-in users vs guests, questions per day (30 days) |

Answers rated 👎 can be exported by an admin (`ADMIN_EMAILS`) as eval-set candidates
(`GET /api/metrics/eval-candidates`), so real failures become new test cases.

## 3. Engineering quality

`python -m scripts.quality_report` → [`metrics/quality.json`](../metrics/quality.json)

| Metric | Result |
|---|---|
| Automated tests | **185 passing**, 0 failing (unit + integration, no API key needed) |
| Line coverage (`app/`, `evals/`) | **87.6%** (2,417 of 2,759 statements); CI fails below 85% |
| CI | ruff lint + the full suite on **SQLite and PostgreSQL** on every push |

## 4. API performance: load test

`python -m scripts.loadtest https://ask-your-data-chi.vercel.app --requests 400 --concurrency 20`
→ [`metrics/loadtest.json`](../metrics/loadtest.json)

Non-AI endpoints (health, dataset list, schema, dashboard KPIs) on the Vercel deployment (Neon
Postgres, iad1), measured from India, so every request includes a ~250 ms intercontinental
round trip.

| Metric | Result |
|---|---|
| Requests / errors | 400 / **0** (0.0% error rate) |
| Throughput | **35 requests/s** at 20 concurrent clients |
| Latency p50 / p95 / p99 | 330 ms / 1.25 s / 1.52 s |
| Fastest endpoint (health) p50 / p95 | 226 ms / 379 ms |
| Heaviest endpoint (KPIs: 5 aggregate queries) p50 / p95 | 1.19 s / 1.43 s |

## 5. Resume lines

Pick the ones that fit the role; every number above can be reproduced from this repository.

**Gen AI / LLM engineer**
- Built a text-to-SQL agent (LangGraph, Gemini) that answers business questions over any uploaded
  dataset, reaching **97.6% execution accuracy** on a 41-item evaluation set, including **100% on
  multi-turn follow-up questions**, at **$0.002 per question** and **4.3 s median latency**.
- Designed conversation memory for follow-ups ("same for 2024", "break that down by city"): the
  model rewrites each question to stand alone, and only the user's own answered turns are used as
  context.
- Made the LLM layer provider-agnostic (Gemini / Claude / OpenAI by configuration) with
  structured JSON output and a self-correction loop that feeds SQL validation and database errors
  back to the model.
- Instrumented every answer with per-step latency, token usage, cost and user feedback; a
  metrics dashboard reports accuracy, p50/p95 latency, cost per 1,000 questions and satisfaction,
  and 👎 answers export as new evaluation cases.

**Data analyst / analytics engineer**
- Built a self-serve analytics app: upload CSV, Excel, Parquet, JSON, PDF tables and 20 other
  formats, ask questions in plain English, and get the answer, chart, SQL and a CSV / Excel / PDF
  report.
- Defined a semantic layer (data dictionary + business glossary) so metrics like revenue, AOV and
  return rate are computed consistently; validated against 41 hand-written reference queries.

**Python / backend developer**
- Built and deployed a FastAPI service on Vercel with Neon Postgres and Vercel Blob: per-user
  private datasets (one schema each), multi-part uploads past the 4.5 MB request limit, email
  sign-in with scrypt hashes and signed HttpOnly cookies.
- **185 automated tests, 87.6% coverage**, CI on SQLite and PostgreSQL; load-tested at **35 req/s
  with 0 errors** (p95 1.25 s including intercontinental latency).
- Three layers of SQL safety for model-generated queries: AST validation (sqlglot), read-only
  transactions with timeouts, and per-dataset schema isolation.
