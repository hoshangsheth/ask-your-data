# Ask Your Data: End-to-End Evaluation Report

**Date:** 12 November 2026 · **Version tested:** commit `7530de8` (production: https://ask-your-data-chi.vercel.app)
**Scope:** functionality, reliability, performance, load/stress, stability, AI answer quality, business value.

Every number below is labelled **[M] measured**, **[C] calculated** from measurements, or **[A] assumption**.
Raw results and logs are in [`evaluation/results/`](evaluation/results); every test can be re-run with
the commands in §3.4.

---

## 1. Executive Summary

Ask Your Data lets a business user ask questions about a dataset in plain English and get a direct
answer, chart, table and the SQL behind it, or chat about the data itself without SQL. It runs in
production on Vercel with Neon Postgres and Vercel Blob.

| Area | Result |
|---|---|
| Functional success rate (API matrix) | **100%**: 108 / 108 operations [M] |
| Browser end-to-end checks (Chromium) | **100%**: 27 / 27 checks [M] |
| Automated test suite | **191 / 191 passing**, 87.5% line coverage [M] |
| AI answer accuracy (48-item eval, real model) | **97.9%**: 47 / 48 [M] |
| Follow-up and "about the data" questions | **100%**: 10 / 10 and 7 / 7 [M] |
| Requests processed in load / stress / soak tests | **64,968**, 1 error (**0.0015%**) [M] |
| 10-minute soak (36,131 requests) | 0 errors, flat p95 (290–332 ms/min), memory −1.9 MB [M] |
| API response time, unloaded (local) | 3.5–5.9 ms for core endpoints; 113 ms for dashboard KPIs [M] |
| Peak throughput, 1 process (local) | **245 req/s** at p95 53 ms (core endpoints) [M] |
| Answer time, question → answer | median **4.4 s**, p95 10.6 s; ~97% of it is the AI model [M] |
| Model cost per answered question | **$0.0021 (≈ ₹0.18)** [M] |
| Production runtime errors during all testing | **0** (Vercel runtime error log, 24 h) [M] |
| Estimated analyst time saved per question | **~95%** (mid scenario; assumption-based) [C/A] |

**Issues found and fixed during this evaluation:** an unreliable theme-switch animation (fell back
to an instant toggle after any page change), clicks being swallowed during the transition, the
sign-in dialog reopening in "create account" mode (sign-in after sign-out failed with *account
exists*), and the hidden admin-only Metrics menu item being visible to users. §11 lists what is
still open.

---

## 2. Application Overview

**Problem.** Answering an ad-hoc business question ("which region's revenue dropped last
quarter?") normally needs an analyst who knows SQL and the schema. Non-technical users wait;
analysts spend time on repetitive queries.

**What the app does**
- Natural-language questions → SQL (LangGraph agent, Gemini) → validated, read-only execution →
  answer + chart + table + SQL, with self-correction on errors.
- **Chat with the data:** questions about the dataset itself ("what is this data about?", "what
  does this column mean?", "how is revenue defined?") are answered from the schema, without SQL.
- **Follow-ups** ("same for 2024", "break that down by city") use the conversation's context.
- **Own data:** upload 25 file types (CSV, Excel, JSON, Parquet, PDF, Word, …) up to 50 MB;
  private per account.
- Export to CSV / Excel / PNG / PDF report; 👍/👎 feedback; dashboard for the demo store.

**Architecture.** FastAPI (Python 3.12) · LangGraph agent · provider-agnostic LLM layer (Gemini
3.8 Flash for SQL, 3.5 Flash-Lite for summaries) · sqlglot SQL guard · SQLAlchemy · SQLite
(local) / Neon Postgres (cloud, one schema per dataset) · Vercel Blob · vanilla JS frontend.

**Target users.** Business and operations teams (sales, marketing, finance, e-commerce ops) at
small and mid-sized companies without a dedicated BI team; analysts who want quick first answers.

---

## 3. Testing Environment and Methodology

### 3.1 Environments

| | Local (most tests) | Production |
|---|---|---|
| Machine | Windows 10 Pro; Intel Core i5-4278U (2 cores / 4 threads, 2.6 GHz, 2014); 7.9 GB RAM; Intel Iris 5100 integrated GPU | Vercel Functions, region iad1 (Washington DC); Neon Postgres; Vercel Blob |
| App | 1 uvicorn process (as one serverless instance), isolated SQLite DB seeded fresh per run (`data/eval/`) | deployed commit `7530de8` |
| AI | Gemini 3.8 Flash + 3.5 Flash-Lite (real API calls) | same |
| Client | same machine (load generator competes for the 4 threads; background load ≈ 31% CPU idle) | same machine in **India**: every request crosses ~220 ms of network round trip |

### 3.2 Tools

pytest 9.2 + pytest-cov · httpx 0.28 (functional + async load generator) · Playwright 1.58
(Chromium headless; Microsoft Edge headed with GPU for frame timing) · psutil 7.2 (CPU / memory
sampling every 0.5 s) · the app's own eval runner · Vercel runtime error log.

### 3.3 Rules followed

- **No production writes:** production was only read (GET endpoints, page loads, read-only UI
  checks). All tests that create accounts, upload, ask or delete ran on the local isolated DB.
- **No destructive tests:** the breaking point was searched only locally; production load stopped
  at 50 concurrent users.
- Test accounts use generated values on the local server; nothing is stored in the repo.

### 3.4 Reproduce

```bash
pytest -q                                   # 191 tests
python -m scripts.quality_report            # tests + coverage -> metrics/quality.json
python -m evaluation.functional             # API matrix (real model) -> results/functional.json
python -m evaluation.ui_e2e                 # browser checks (real model) -> results/ui_e2e.json
python -m evaluation.ai_quality             # 48-item eval + concurrent users
python -m evaluation.load_stress local      # baseline + step load to breaking point
python -m evaluation.load_stress production https://ask-your-data-chi.vercel.app
python -m evaluation.soak --minutes 10
python -m evaluation.db_perf                # queries, SQL guard, upload ingestion
python -m evaluation.page_load https://ask-your-data-chi.vercel.app
python -m evaluation.business               # calculations from the results + assumptions
```

---

## 4. Functional Testing Results

### 4.1 API functional matrix: 108 / 108 (100%) [M]
`evaluation/results/functional.json`. Negative cases count as passes when the app correctly rejects them.

| Category | Ops | Passed | What was covered |
|---|---|---|---|
| Pages | 6 | 6 | app shell, static assets, OpenAPI docs, 404 |
| API | 6 | 6 | health, KPIs, schema, datasets, formats, session |
| Accounts | 9 | 9 | sign-up, duplicate (409), bad email/password (400), wrong password / unknown user (401), sign-out + sign-in, forged cookie → guest |
| Uploads | 25 | 25 | **all 18 sample formats uploaded and parsed** (CSV, semicolon CSV, TSV, TXT, XLSX, ODS, JSON, nested JSON, JSONL, Parquet, Feather, XML, HTML, DOCX, PDF table, PDF text, SQLite, Stata) + guest refused, >50 MB (413), .exe (415), empty (400), corrupt (422), path traversal (404), missing part (409) |
| Privacy | 7 | 7 | another user can't read, query, see schema of, or delete a dataset; guests see only the demo; metrics API refused (403) |
| SQL guard | 18 | 18 | DROP, DELETE, UPDATE, INSERT, stacked statements, CTAS, ALTER, system tables, schema-qualified names, ATTACH, PRAGMA, FOR UPDATE, load_extension, writable CTE, VACUUM, GRANT, app tables (`users`, `questions`): **all blocked** |
| Ask (real model) | 12 | 12 | data question, follow-up, 3 "about the data" questions, off-topic declined, 2 uploaded datasets, **prompt injection ("run DROP TABLE orders") handled safely, data verified unchanged**, validation errors |
| Answers | 7 | 7 | 👍 / 👎 with note, other user refused, CSV, Excel, PDF report, other user's export refused |
| Cleanup | 18 | 18 | deleting every test dataset |

### 4.2 Browser end-to-end: 27 / 27 (100%) [M]
`evaluation/results/ui_e2e.json`, screenshots in `evaluation/results/screens/`.

Page load · how-to-use popup (first visit, dismiss, not shown again, reopen) · question pills drift
and pause on hover · **theme switch animated on 10 / 10 toggles including after scrolling** ·
rapid 5× clicking ends in the right theme · tap a pill → answer · data question with
chart/table/SQL tabs · follow-up shows "understood as…" · 2 "about the data" questions (no SQL) ·
off-topic declined · 👍 · exports CSV / XLSX / PDF / PNG downloaded · upload asks guests to sign
in · sign-up shows the success animation and continues to the file picker · CSV upload · questions
on the upload · sign-out hides it · sign-in again shows it · wrong password error · dashboard ·
data view · Metrics menu hidden from users · mobile 375 px (no horizontal overflow, menu works).

Console errors: 1, the expected `401` from the wrong-password check. HTTP 5xx: 0.

### 4.3 Automated test suite [M]
191 tests (unit + integration), **all passing**, **87.5% line coverage** (2,434 / 2,783 statements),
run in CI on SQLite and PostgreSQL on every push.

### 4.4 Defects found by this evaluation

| # | Defect | Impact | Status |
|---|---|---|---|
| 1 | Theme switch fell back to an instant toggle whenever the page had changed or scrolled in the last ~1.2 s (pre-captured snapshots invalidated) | the reported "transition isn't smooth / sometimes just toggles" | **Fixed**: rebuilt on the View Transitions API; 10 / 10 toggles animate |
| 2 | Clicks during the ~1 s theme transition were swallowed by the transition overlay | first click after a switch sometimes did nothing | **Fixed** (`::view-transition { pointer-events: none }`) |
| 3 | Sign-in dialog reopened in "create account" mode after sign-out → signing back in failed (409) | users could not sign back in without switching mode | **Fixed** (dialog always opens on "Sign in") |
| 4 | Elements with the `hidden` attribute could still render (component CSS overrode it) | admin-only Metrics menu item visible to users | **Fixed** (global `[hidden]` rule) |

**Overall functional success rate [M]: 326 / 326 checks (108 API + 27 browser + 191 automated) = 100%**,
after the fixes above; AI accuracy is reported separately (§5.4).

---

## 5. Technical Performance Metrics

### 5.1 API response time, one request at a time [M]

| Endpoint | Local avg / p50 / p95 / p99 (ms) | Production avg / p50 / p95 (ms, incl. ~220 ms network) |
|---|---|---|
| `/api/health` | 3.5 / 3.1 / 5.0 / 5.6 | 237 / 223 / 284 |
| `/api/datasets` | 5.5 / 5.1 / 6.9 / 7.6 | 296 / 288 / 309 |
| `/api/schema` | 5.9 / 5.5 / 7.3 / 8.1 | 265 / 264 / 282 |
| `/api/kpis` (6 aggregate queries) | 113 / 111 / 134 / 140 | 500 / 438 / 1,065 |
| `/` (app shell) | 5.2 / 4.8 / 7.3 / 8.8 | 225 / 222 / 255 |
| static JS / CSS | 4.3–4.6 / 4.0–4.3 / 5.8–6.4 | 240–314 / 236–237 / 248–454 |

**Average API response time (core endpoints, local, unloaded): 4.9 ms** [C: mean of health, datasets, schema].

### 5.2 Application load time [M]

| | First visit (empty cache) | Repeat visit |
|---|---|---|
| Local: first paint / app ready | 244 ms / **531 ms** (median of 5) | 104 ms / **186 ms** |
| Production: TTFB / first paint / app ready | 38 ms / 820 ms / **2.5 s** (median of 5) | 22 ms / 716 ms / 2.3 s |

App files transferred: 12 KB HTML. One of five production first visits took **21.7 s** because a
third-party CDN script (Chart.js / GSAP) stalled; a local run saw a 7.7 s first load for the same
reason. "App ready" waits on two sequential API calls (~300–550 ms each from India).

### 5.3 Database and data processing (SQLite, local) [M]
`evaluation/results/db_perf.json`

| Measure | Result |
|---|---|
| Demo store | 45,077 rows (2,500 customers, 96 products, 15,779 orders, 26,702 order lines); seeded in 0.87 s |
| 39 realistic analytical queries (eval reference SQL), 10 runs each | median **10 ms**, p95 27 ms, slowest 49 ms; **all under 50 ms** |
| Dashboard KPIs (6 queries) | p50 103 ms, p95 113 ms |
| SQL safety check (sqlglot parse + rules) | **3.0 ms** average per query (max 8 ms) |
| Upload ingestion, CSV (read → clean → profile → store) | 10K rows 0.31 s · 100K rows **2.65 s** · 500K rows (21 MB) **13.0 s**: ~**38,000 rows/s** |
| Upload ingestion, Excel 50K rows | 9.1 s (5,500 rows/s; Excel parsing is the cost) |
| Upload API round trip, 18 sample formats | 67 ms (JSONL) – 1,140 ms (PDF table) |

Neon (production) query time was not measured in isolation: it would need the production
database credentials on this machine. End-to-end production timings above include it.

### 5.4 AI answer quality and speed (real model) [M]
`metrics/eval.json`

| Category | Items | Passed | Accuracy |
|---|---|---|---|
| Single questions (reference SQL, execution match) | 29 | 28 | 96.6% |
| Follow-up conversations (2–3 turns) | 10 | 10 | 100% |
| "About the data" (no SQL, must name the right tables/terms) | 7 | 7 | 100% |
| Must decline (data not stored) | 2 | 2 | 100% |
| **Total** | **48** | **47** | **97.9%** |

The one miss returned the correct revenue for every quarter but labelled them `2025-Q1` instead of
`Q1`; the scorer is strict and this was not adjusted after the fact.

Latency: median 4.4 s, p95 10.6 s. Tokens per question (SQL call + answer call): 2,048 in / 242 out.
Cost: **$0.0021 per question** (60 model calls cost $0.128 in total).
Where the time goes (single user): writing SQL 3.4 s · safety check 17 ms · database 22 ms ·
writing the answer 1.0 s. **The model is ~97% of answer time; the app's own work is under 50 ms.**

### 5.5 CPU and memory [M]

| State | Server CPU | Server memory (RSS) |
|---|---|---|
| Idle | 0% | 197 MB |
| 10 users, core endpoints (245 req/s) | 99% of one core | 228 MB |
| 50 users, mixed with dashboard | 283% (multi-core via the thread pool) | 255 MB |
| 10-minute soak (5 users, 60 req/s) | 255% avg, 369% max | 213 MB avg, 219 MB max; **no growth** |

Production CPU / memory per function invocation is not exposed outside the Vercel dashboard and
was not measured.

### 5.6 Theme switch smoothness [M]
Frame pacing over 1.2 s (budget ≤ 34 ms per frame ≈ 30 fps; 100% when idle in both browsers):
headless Chromium 80% of frames on time during the switch (56–93% across five runs); headed Edge
on this 2014 integrated GPU 60% (23–63%). A plain theme flip **with no animation** also drops frames on this machine (whole-page
restyle), so these numbers mostly reflect the test hardware. Reliability (the reported problem) is
fixed: 10 / 10 switches animate.

---

## 6. Load and Stress Testing Results

### 6.1 Local step load (1 process), core endpoints (health, datasets, schema) [M]

| Users | req/s | p50 ms | p95 ms | p99 ms | Errors | Server CPU |
|---|---|---|---|---|---|---|
| 1 | 189.5 | 5.2 | 7.2 | 8.5 | 0 | 73% |
| 5 | 227.1 | 21.5 | 33.3 | 44.2 | 0 | 95% |
| **10** | **245.4** | 40.8 | **52.9** | 62.7 | 0 | 99% |
| 25 | 175.4 | 102.9 | 384.3 | 740.0 | 0.04% | 75% |
| 50 | 90.5 | 377.4 | 1,531.8 | 2,386.5 | 0 | 56% |
| 100 | 52.4 | 1,171.0 | 5,419.5 | 7,064.1 | 0 | 43% (**breaking point**: p95 > 2 s) |

### 6.2 Local step load, mixed incl. dashboard KPIs [M]

| Users | req/s | p50 ms | p95 ms | Errors | Machine CPU |
|---|---|---|---|---|---|
| 1 | 32.1 | 5.9 | 109.1 | 0 | 45% |
| 10 | 65.1 | 47.3 | 528.7 | 0 | 96% |
| 50 | 65.7 | 661.7 | 1,378.2 | 0 | 95% |
| 100 | 50.3 | 1,541.3 | 5,213.8 | 0 | 88% (**breaking point**) |

### 6.3 Production step load (read-only, from India) [M]

| Users | req/s | p50 ms | p95 ms | p99 ms | Errors |
|---|---|---|---|---|---|
| 1 | 3.3 | 278 | 439 | 440 | 0 |
| 5 | 15.8 | 283 | 481 | 497 | 0 |
| 10 | 28.6 | 292 | 611 | 670 | 0 |
| **25** | **43.6** | 316 | 1,590 | 1,680 | 0 |
| 50 | 25.1 | 386 | 2,685 | 10,930 | 0 |

### 6.4 Concurrent users asking the AI (local server, real model) [M]

| Users (2 questions each) | Success | Questions/min | p50 s | p95 s |
|---|---|---|---|---|
| 1 | 100% | 11.0 | 4.4 | 6.2 |
| 3 | 100% | 34.4 | 4.2 | 5.2 |
| 5 | 100% | 40.0 | 4.6 | 8.5 |
| 8 | 100% | 40.7 | 4.9 | 18.2 |

### 6.5 Stability: 10-minute soak [M]
5 users, mixed endpoints: **36,131 requests, 0 errors**, 60 req/s, p50 17 ms, p95 301 ms; p95 per
minute between 290 and 332 ms (no drift); memory 214 → 213 MB (no leak); server never restarted.

### 6.6 Maximum stable throughput (no errors, p95 ≤ 2 s) [M]
- Core endpoints, one local process: **245 req/s** at 10 users (p95 53 ms).
- Mixed with dashboard: **66 req/s** at 50 users (p95 1.38 s).
- Production (from India): **44 req/s** at 25 users (p95 1.59 s).
- AI questions: **~40 questions/min** sustained by one instance with 5–8 concurrent users, 0 errors.

**Interpretation.** One Python process saturates one core at ~245 req/s for light endpoints. The
dashboard KPI queries (110 ms of CPU each) are the main server-side bottleneck. Beyond ~25
concurrent users locally the load generator and the server compete for the same 4 threads, so
those steps understate the server. On production, p95/p99 at 50 users (2.7 s / 10.9 s) is
consistent with Vercel starting new instances (cold starts). **No step on either environment
produced server errors**; degradation was in latency, not correctness.

---

## 7. Business Impact Assessment

**Business problem.** Time-to-insight for routine data questions depends on analyst availability;
non-technical staff can't query data themselves; analysts spend time on repetitive SQL.

**Use cases.** Sales and regional performance questions; e-commerce operations (cancellations,
returns, payment mix); finance summaries (revenue, margin, AOV); quick analysis of exported
spreadsheets or reports; onboarding to an unfamiliar dataset ("what is this data about?").

**KPIs a business would track** (all instrumented in the app's question log, owner-only):
answer accuracy (eval + 👍 rate), self-serve rate (questions answered without an analyst),
time-to-insight (question → answer), cost per answered question, adoption (weekly active users,
questions per user), follow-up rate (depth of exploration), export rate (answers reused in reports).

**Commercial viability (qualitative).** Marginal cost per question is very low ($0.0021 [M]), and
infrastructure is serverless (scales to zero). Main risks: accuracy on messy real-world schemas is
untested beyond the eval set; trust requires users to check the SQL; data-privacy expectations for
uploaded files; a crowded market of BI / text-to-SQL tools. **No customers or real usage exist
yet, so no real-world impact is claimed.**

---

## 8. Operational Efficiency Analysis

### 8.1 Process steps [C]
Manual (request → analyst → SQL → check → chart → summary → reply): **10 steps, 2 people**.
With the app: **3 steps, 1 person** (ask · read answer/chart/SQL · optional one-click export).
**7 of 10 steps eliminated (70%)**; the analyst hand-off disappears for questions the app answers.

**Tasks automated:** schema lookup and business definitions · SQL writing and error correction ·
SQL safety validation · chart selection · plain-language summary · follow-up context · file import
(format detection, cleaning, typing, profiling) · report and spreadsheet export.

### 8.2 Time per task [M] and estimated savings [C/A]

| Task | With the app [M] | Manual [A] | Saved [C] |
|---|---|---|---|
| Answer one ad-hoc question | 4.4 s median model time + ~1 min reading [A] | 10 / 20 / 45 min (low / mid / high) | **94–95%** |
| Load a 100K-row CSV for analysis | 2.65 s processing + ~1 min [A] | 10 / 30 / 60 min | **90–98%** |
| Produce a PDF report of an answer | 0.3 s (measured in UI test) | 5–15 min [A] | ~99% |

**Productivity [M].** One user completes ~11 questions/min of model time end to end; one instance
served 40 questions/min across 5–8 concurrent users with 0 errors.

---

## 9. Cost-Benefit Analysis

`evaluation/results/business.json`. Assumptions are in `evaluation/business.py` and can be edited.

| Per question | Low | Mid | High |
|---|---|---|---|
| Manual cost (analyst minutes × rate [A]: 10 min @ ₹400/h · 20 min @ ₹700/h · 45 min @ ₹1,200/h) | ₹66.7 | ₹233.3 | ₹900.0 |
| With the app (human minutes [A] + model ₹0.18 [M]) | ₹3.5 | ₹11.9 | ₹40.2 |
| **Cost reduction** [C] | **94.7%** | **94.9%** | **95.5%** |

| Per month | Low | Mid | High |
|---|---|---|---|
| Questions [A] | 200 | 1,000 | 5,000 |
| Self-serve share [C] (97.9% accuracy × acceptance 60 / 80 / 95% [A]) | 58.8% | 78.3% | 93.0% |
| Analyst hours freed [C] | 18.5 | 247 | 3,328 |
| Model cost [C] | ₹36 | ₹179 | ₹897 |
| Net saving [C] | ₹7.4K | ₹1.74 lakh | ₹40 lakh |

**Biggest cost drivers.** (1) The SQL-writing model call, which carries the schema and business
definitions with every question (the bulk of the ~2K input tokens per question; the split between
the two calls was not measured); (2) the answer-writing call; (3) at scale, serverless compute and Postgres
storage. Gemini 3.8 Flash's price doubles on 1 Jan 2027 [external fact], which would raise the
model cost to ≈ $0.004 per question; still negligible against labour.

**ROI.** Not calculable as a measured figure: there are no development-cost or real-usage numbers.
Under the mid assumptions, monthly savings (₹1.74 lakh) exceed model costs (₹179) about 970×; the
binding factors are accuracy on the customer's own data and user trust, not running cost.

---

## 10. Scalability Assessment

- **Horizontal:** stateless API (sessions are signed cookies; the signing key lives in the
  database), so Vercel can run many instances; tested to 50 concurrent users in production, 0 errors.
- **Per instance:** ~245 req/s for light endpoints, ~40 AI questions/min.
- **Data:** each dataset is its own Postgres schema; queries are capped at 500 rows and 5 s;
  uploads up to 50 MB (≈ 1M rows) process at ~38K rows/s.
- **Limits:** in-memory rate limiting is per instance; the AI provider's rate limits cap question
  throughput; dashboard KPIs are recomputed on every request; cold starts add seconds to the
  first request on a new instance; the function region (US East) adds ~220 ms per call for users
  in India.

---

## 11. Identified Issues and Limitations

1. **Dashboard KPIs recomputed per request** (110 ms CPU each): the main server-side bottleneck under load.
2. **Third-party CDN dependencies** (Google Fonts, Chart.js, GSAP) caused 7.7 s and 21.7 s outlier first loads.
3. **Sequential start-up API calls** (`/api/auth/me` then `/api/datasets`) add one extra round trip to "app ready".
4. **Region:** functions and database in US East; ~220 ms per request for users in India.
5. **AI latency tail:** p95 10.6 s in the eval, 18 s at 8 concurrent users (model-side variance).
6. **Quarter-label formatting** can differ from expectations (the single eval miss).
7. **Rate limiting is per instance** (in memory), so it is a speed bump on serverless, not a guarantee.
8. **Not measured:** production CPU / memory, Neon query time in isolation, real-user accuracy on
   customer data, true manual task times (needs a time study with real analysts).
9. **Theme-switch frame rate** on old integrated GPUs (~60% of frames on time on the test machine).

## 12. Recommendations for Improvement

| Priority | Recommendation | Expected effect |
|---|---|---|
| High | Cache dashboard KPIs (the demo data is static; invalidate on re-seed) | removes the main load bottleneck (110 ms → ~0) |
| High | Self-host fonts and the JS libraries (or add `preconnect` + `font-display: swap`) | removes CDN-stall outliers in first load |
| High | Fetch `/api/auth/me` and `/api/datasets` in parallel | ~300–500 ms faster "app ready" in production |
| Medium | Move functions to a region near the users (Vercel `bom1`, Mumbai) with a nearby Postgres region | up to ~200 ms less per request |
| Medium | Stream answers (show SQL as soon as it is written, then the summary) | perceived latency halves |
| Medium | Prompt caching of the schema (2K tokens per call) | lower cost and latency per question |
| Medium | Shared rate limiting (Postgres / Redis) | real per-user limits on serverless |
| Low | Normalise period labels in answers (Q1 vs 2025-Q1) | small accuracy gain |
| Low | Time study with real analysts | replace §8–9 assumptions with measurements |

## 13. Final Application Scorecard

| Dimension | Score | Basis |
|---|---|---|
| Functionality | 10 / 10 | 326 / 326 checks pass after fixing 4 defects |
| Reliability and stability | 9 / 10 | 64,968 requests, 1 error; 10-min soak flat; 0 production runtime errors |
| AI answer quality | 9 / 10 | 97.9% on 48 items; untested on real customer schemas |
| Performance | 7 / 10 | sub-10 ms core APIs; dashboard and model latency dominate; CDN and region issues |
| Scalability | 7 / 10 | stateless, serverless; per-instance limits and cold starts |
| Security | 8 / 10 | 18 / 18 malicious SQL blocked, private data isolation, injection handled; per-instance rate limit |
| UX | 8 / 10 | reliable theme switch, onboarding, follow-ups, exports; first-load outliers |
| Business value | 7 / 10 | strong cost case on assumptions; no real users yet |
| **Overall** | **8.1 / 10** | |

---

## 14. Resume-Ready Project Metrics

All figures come from this evaluation; ✓ = measured, ≈ = calculated from stated assumptions.

- ✓ Built an AI analytics assistant whose text-to-SQL agent answers business questions at **97.9%
  execution accuracy** on a 48-question benchmark, including **100% on multi-turn follow-ups** and
  questions about the dataset itself.
- ✓ Delivered answers in a **median of 4.4 s** at **$0.0021 per question**; profiled the pipeline
  and showed the app's own work (SQL safety check + database) takes **under 50 ms** of that.
- ✓ Achieved a **100% functional test success rate** across **326 automated checks** (108 API, 27
  browser end-to-end, 191 unit/integration; 87.5% code coverage), and found and fixed 4 defects
  in the process.
- ✓ Processed **64,968 requests** in load, stress and soak testing with a **0.0015% error rate**;
  sustained **245 requests/s** per instance at **p95 53 ms**; ran **10 minutes (36K requests)**
  with **zero errors and no memory growth**.
- ✓ Supported **50 concurrent users** on the production deployment (Vercel + Neon) with **zero
  errors**, and **8 concurrent users asking the AI** with 100% success.
- ✓ Average API response time of **4.9 ms** (core endpoints, unloaded); 39 analytical queries all
  under **50 ms** (median 10 ms).
- ✓ Ingested uploaded files at **~38,000 rows/s** (500K-row CSV in 13 s) across **18 tested file
  formats**, 100% parsed correctly.
- ✓ Blocked **18 / 18** destructive or unsafe SQL attempts and a prompt-injection attack, with
  per-user data isolation verified.
- ≈ Reduces the steps to answer a data question from **10 to 3 (−70%)** and removes the analyst
  hand-off; estimated **~95% less time and cost per routine question** (assumption-based; see §9).
