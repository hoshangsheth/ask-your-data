# Ask Your Data

Ask business questions in plain English — about the built-in demo store or **your own uploaded
file** — and get back a direct answer, the SQL that produced it, a results table and a chart.

A LangGraph agent writes the SQL with an LLM, a guard checks it, the database runs it read-only,
and if anything fails the error goes back to the model to fix (up to 3 attempts). The AI provider
is a config setting: Gemini by default, Claude or OpenAI with a one-line change.

**Upload your own data** (drag and drop anywhere, up to 50 MB): CSV / TSV / TXT, Excel (.xlsx .xlsm
.xls), OpenDocument (.ods), JSON / JSON Lines, Parquet, Feather, XML, HTML tables, Word (.docx
tables), PDF (tables, or text lines), SQLite databases, Stata (.dta) and SAS (.sas7bdat .xpt).
Column names are cleaned, numbers like `"₹1,200"` and dates are detected, every sheet or table
becomes a SQL table, and starter questions are suggested for the file.

<!-- Add a screenshot or GIF of the app here: ![demo](docs/demo.gif) -->

## How it works

```mermaid
flowchart LR
    Q[Question] --> G[generate_sql<br/>LLM + schema + glossary]
    G -->|not answerable| E((End))
    G --> V[validate<br/>sqlglot guard]
    V -->|error| G
    V --> X[execute<br/>read-only, timeout]
    X -->|DB error| G
    X --> S[summarize<br/>LLM: answer + chart]
    S --> E
```

| Layer | What it does |
|---|---|
| **Semantic layer** (`app/db/catalog.py`) | Data dictionary + business glossary sent with every question, so "revenue" always excludes cancelled/returned orders. |
| **Agent** (`app/agent/`) | LangGraph state machine: generate → validate → execute → summarize, with self-correction on validation or database errors. |
| **LLM layer** (`app/llm/`) | Provider-agnostic: one `complete_json()` contract, adapters for Gemini, Claude and OpenAI, all using structured JSON-schema output. Prompts are written once and shared by every provider. Token usage is tracked per step. |
| **SQL guard** (`app/sql/guard.py`) | Parses with sqlglot: single statement, SELECT only, allow-listed tables, no system catalogs, no `pg_sleep`/file functions, no `FOR UPDATE`, enforced `LIMIT`. |
| **Execution** (`app/db/executor.py`) | Read-only transaction, statement timeout, row cap; on Postgres a dedicated `app_readonly` role. Three independent layers of protection. |
| **Uploads** (`app/datasets/`) | Read any supported file → clean and type the columns → profile them → store one read-only SQLite file per dataset. The profile (types, ranges, values, original headers) is what the model sees. |
| **Data sources** (`app/sources/`) | The agent only sees a `DataSource` (engine, allowed tables, schema text, currency), so the demo store and uploads work the same way, and a question about one dataset can never read another. |
| **API** (`app/api/`) | FastAPI with one router per feature: `/api/ask`, `/api/datasets` (upload, list, delete), `/api/schema`, `/api/kpis`, `/api/health`; typed request/response models; optional API key and per-IP rate limit; JSON request logs with token counts. |
| **UI** (`app/web/static/`) | Chat-style answers (chart, table, SQL, step trace), new chat, dataset switcher with drag-and-drop upload and progress, KPI dashboard, data browser, light/dark theme with an animated ink-bleed transition (WebGL, ported from MIT-licensed "Ink Bleed"; see `THIRD_PARTY_NOTICES.md`). |
| **Evaluation** (`evals/`) | 31 questions with hand-written reference SQL; execution-accuracy scoring; works with any provider, so models can be compared on the same set. |

The demo data is a synthetic Indian e-commerce store (2,500 customers, ~16K orders, 2024–2025) with
patterns planted on purpose: a Diwali-season spike, East-region slump in Q4 2025, higher COD
cancellations and Fashion returns.

## Choosing the AI provider

Set these in `.env` — no code changes:

| Provider | `LLM_PROVIDER` | Key | Default models (SQL / summary) |
|---|---|---|---|
| Google Gemini | `gemini` | `GEMINI_API_KEY` from aistudio.google.com/apikey | `gemini-3.8-flash` / `gemini-3.5-flash-lite` |
| Anthropic Claude | `anthropic` | `ANTHROPIC_API_KEY` from console.anthropic.com | `claude-opus-5-5` / `claude-opus-5-5` |
| OpenAI | `openai` | `OPENAI_API_KEY` from platform.openai.com | none — set `LLM_SQL_MODEL` and `LLM_SUMMARY_MODEL` |

Override either model with `LLM_SQL_MODEL` / `LLM_SUMMARY_MODEL`, and reasoning depth with
`LLM_SQL_REASONING` / `LLM_SUMMARY_REASONING` (`low | medium | high`, mapped to Gemini thinking level,
Claude effort or OpenAI reasoning effort). SQL writing gets the stronger model; the summary step uses
a cheaper one.

**Adding another provider:** write a class with `name` and `complete_json()` in `app/llm/providers/`,
register it in `app/llm/providers/__init__.py`, and add default models in `app/llm/factory.py`.

## Run it locally (Windows / macOS / Linux)

Needs Python 3.11+ and an API key for your chosen provider.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env  — then paste your key into .env
uvicorn app.main:app --reload
```

Open http://localhost:8000. The SQLite demo database is created and seeded on first start.
The dashboard works without a key; asking questions needs one.

## Run with PostgreSQL (Docker)

```bash
docker compose up --build
```

Starts Postgres 16, creates a read-only role, seeds the data and serves the app on port 8000.

## Tests

```bash
pytest -q
```

145 tests, no API key needed (models and SDK clients are replaced by stubs), split into
`tests/unit` (SQL guard, LLM adapters and provider switching, file parsing for every upload
format, chart choice, eval scoring) and `tests/integration` (read-only execution, timeouts, KPIs,
agent retry paths, upload → ask → delete over HTTP, dataset isolation, auth and rate limiting,
eval reference SQL). Sample files for every format are generated by `tests/sample_files.py`.
CI (GitHub Actions) lints with ruff and runs the suite against both SQLite and PostgreSQL.

## Deploying

Local uploads are stored as SQLite files, which won't persist on serverless hosting. See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the cloud plan: original files in Vercel Blob (direct
browser upload past the 4.5 MB request limit), tables in Postgres (Neon) with one schema per
dataset, and the read-only role scoped to that schema.

```bash
ruff check .        # lint
ruff format .       # format (VS Code does this on save)
```

## Working in VS Code

Open the folder (`code "D:\Ask Your Data"`) and accept the recommended extensions. The workspace
settings select `.venv` automatically, format and lint with Ruff on save, and discover the tests.
Run configurations (Run and Debug panel): **API server**, **Seed demo data**, **Run eval**,
**Debug current test file**.

## Evaluation

```bash
python -m evals.run_eval            # calls the real model: costs a little per run
```

Each question's reference SQL and the agent's SQL are both executed; a question passes when the
result values match (order-insensitive, extra columns allowed, numeric tolerance). Two questions are
deliberately unanswerable and pass only if the agent declines. Results, including average tokens per
question, go to `evals/results.json`. Change `LLM_PROVIDER` / models and re-run to compare.

| Provider | SQL model | Execution accuracy | Self-corrected | Median latency | Avg tokens in / out |
|---|---|---|---|---|---|
| gemini | gemini-3.8-flash | _run the eval and fill in_ | | | |

## Project layout

Each package owns one concern and each module one responsibility. Every file starts with a
docstring saying what it does and how to use it. Dependencies point one way:
`api → agent → llm / sql / db → core`.

```
app/
  main.py                 ASGI entry point (uvicorn app.main:app)
  core/                   cross-cutting, no business logic
    config.py             settings from env / .env
    logging.py            JSON-lines logging
  db/                     data access
    models.py             table definitions
    catalog.py            data dictionary, business glossary, schema text for the model
    engine.py             owner + read-only engines
    executor.py           read-only execution with timeout and row cap
    seed.py               demo data (python -m app.db.seed)
  sql/
    guard.py              static SQL validation
  datasets/               user uploads
    formats.py            one reader per file format -> raw tables
    cleaning.py           safe names, number/date detection, size limits
    profile.py            column profiles, schema text for the model, starter questions
    store.py              one read-only SQLite file + metadata per dataset
    service.py            upload pipeline: validate -> read -> clean -> profile -> store
  sources/                what the agent queries
    base.py               DataSource (engine, allowed tables, schema text, currency)
    demo.py, upload.py    the demo store / an uploaded dataset as a DataSource
  llm/                    provider-agnostic AI layer
    contracts.py          the provider interface (complete_json)
    errors.py             provider-neutral errors
    prompts.py            prompts + JSON schemas (shared by all providers)
    text_to_sql.py        generate_sql() and summarize()
    factory.py            builds the configured provider
    providers/            gemini.py, anthropic.py, openai.py
  agent/                  LangGraph workflow
    state.py              state passed between nodes
    graph.py              nodes, routing, ask()
    charts.py             chart suggestion check
  analytics/
    kpis.py               dashboard KPI queries
  api/                    HTTP layer
    factory.py            create_app(): wiring, lifespan, routers, static files
    container.py          long-lived services (engines, dataset store, an agent per dataset)
    dependencies.py       services lookup, API key + rate limit
    rate_limit.py         sliding-window limiter
    schemas.py            request/response models
    routes/               health.py, dashboard.py, ask.py, datasets.py
  web/static/
    css/                  tokens (light/dark), base, layout, components
    js/                   one module per concern: api, ask, datasets, upload, dashboard, data,
                          charts, format, icons, recent, theme, toast, main
    js/ink/               ink-bleed theme transition (WebGL renderer, shaders, page capture)
evals/                    dataset.py, scoring.py, run_eval.py, questions.jsonl
tests/                    fakes.py, sample_files.py, conftest.py, unit/, integration/
docs/                     DEPLOYMENT.md (cloud database plan)
docker/                   Postgres read-only role
.vscode/                  shared editor settings, run configs, recommended extensions
```
