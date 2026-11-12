"""
HTTP routes, one module per feature. Each module exposes `router`, mounted in app/api/factory.py.

    health.py      GET  /api/health
    dashboard.py   GET  /api/kpis, GET /api/schema
    ask.py         POST /api/ask
    datasets.py    GET/POST /api/datasets, GET/DELETE /api/datasets/{id}, GET /api/formats
"""
