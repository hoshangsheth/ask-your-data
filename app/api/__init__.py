"""
HTTP layer (FastAPI). Thin: it validates input, calls services, and shapes output.

    factory.py       create_app(): builds the app, lifespan, routers and static files
    container.py     Services: the long-lived objects (settings, engines, limiter, agent)
    dependencies.py  FastAPI dependencies (services lookup, API-key + rate-limit check)
    rate_limit.py    in-memory sliding-window limiter
    schemas.py       request/response models (also drive the OpenAPI docs at /docs)
    routes/          one module per feature: health, dashboard, ask
"""
