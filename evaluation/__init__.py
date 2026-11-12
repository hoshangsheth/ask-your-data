"""
End-to-end evaluation suite: runs the real application and records measurable results.

    server.py        start/stop the app (uvicorn) on an isolated, freshly seeded SQLite database
    functional.py    every API endpoint and workflow, incl. edge cases -> results/functional.json
    ui_e2e.py        browser tests with Playwright (Chromium)            -> results/ui_e2e.json
    ai_quality.py    real-model checks: accuracy run, concurrency       -> results/ai_*.json
    load_stress.py   step load up to the breaking point, CPU/memory     -> results/load_*.json
    soak.py          constant load for N minutes, stability + memory     -> results/soak.json
    db_perf.py       query timings (demo KPIs, typical agent SQL)        -> results/db_perf.json

See EVALUATION_REPORT.md for the methodology and the results.
"""
