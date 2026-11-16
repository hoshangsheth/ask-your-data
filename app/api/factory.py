"""
Application factory: builds a fully wired FastAPI app.

Usage:
    from app.api.factory import create_app
    app = create_app()                              # settings from env/.env, LLM from settings
    app = create_app(Settings(...), llm=FakeLLM())  # tests: custom settings, scripted model

Startup (lifespan): creates tables (demo store, accounts, question log) and seeds the demo store if empty (AUTO_SEED=true; SQLite or
Postgres). Shutdown: closes connection pools.
"""

import hashlib
import mimetypes
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, insert, select, text
from sqlalchemy import exc as sa_exc

from app.api.container import Services
from app.api.routes import ask, auth, dashboard, datasets, health, metrics, questions
from app.api.session import install_session_middleware
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event
from app.datasets.pg_store import PostgresDatasetStore
from app.db.app_tables import LATER_COLUMNS, add_missing_columns, app_metadata, app_secrets
from app.db.models import metadata
from app.db.seed import seed
from app.llm import LLM

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"

# Windows can map .js to text/plain via the registry; browsers refuse ES modules served that way.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# SQLite stores NUMERIC as REAL and SQLAlchemy warns on every query. Expected for the demo DB.
warnings.filterwarnings("ignore", category=sa_exc.SAWarning, message=".*Decimal objects natively.*")


_SEED_LOCK_ID = 727_001  # arbitrary app-wide key for pg_advisory_lock
_SCHEMA_KEY = "schema_fingerprint"  # row in app_secrets: the schema this database was prepared for


def _schema_fingerprint(services: Services) -> str:
    """Changes whenever a table or column is added or altered, or the seeding setting changes."""
    parts = [f"seed={services.settings.auto_seed}"]
    for md in (app_metadata, metadata):
        for t in md.sorted_tables:
            parts.append(t.name + ":" + ",".join(f"{c.name}/{c.type}" for c in t.columns))
    parts += [f"{t}.{c}" for t, c, _ in LATER_COLUMNS]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def _schema_is_current(services: Services, fingerprint: str) -> bool:
    """One quick read instead of the locked create/migrate/seed pass on every cold start."""
    try:
        with services.owner_engine.connect() as conn:
            stored = conn.execute(
                select(app_secrets.c.value).where(app_secrets.c.name == _SCHEMA_KEY)
            ).scalar_one_or_none()
        return stored == fingerprint
    except Exception:  # first start on this database (no tables yet), or any doubt: do the full pass
        return False


def _remember_schema(conn, fingerprint: str) -> None:
    conn.execute(delete(app_secrets).where(app_secrets.c.name == _SCHEMA_KEY))
    conn.execute(insert(app_secrets).values(name=_SCHEMA_KEY, value=fingerprint))


def _prepare_database(services: Services) -> None:
    """Create tables and load the demo data if the database is empty (AUTO_SEED=true).

    Skipped when the database already matches this code (a fingerprint of every table and column,
    stored after a successful pass): serverless instances start often, and the full pass costs
    a dozen round trips plus a lock.

    On Postgres several serverless instances can cold-start at once, so seeding runs in one
    transaction holding an advisory lock: the first instance loads the data, the others wait and
    then find it there. (A transaction-level lock also works through Neon's connection pooler.)
    """
    engine, auto_seed = services.owner_engine, services.settings.auto_seed
    fingerprint = _schema_fingerprint(services)
    if _schema_is_current(services, fingerprint):
        return
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_ID})
            if isinstance(services.store, PostgresDatasetStore):
                services.store.create_tables(conn)
            app_metadata.create_all(conn)
            add_missing_columns(conn)
            counts = seed(conn) if auto_seed else metadata.create_all(conn)
            _remember_schema(conn, fingerprint)
    else:
        app_metadata.create_all(engine)
        with engine.begin() as conn:
            add_missing_columns(conn)
        counts = seed(engine) if auto_seed else metadata.create_all(engine)  # seed: no-op if data exists
        with engine.begin() as conn:
            _remember_schema(conn, fingerprint)
    if counts:
        log_event("seeded", **counts)


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or get_settings()
    services = Services(settings, llm)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        configure_logging()
        _prepare_database(services)
        yield
        services.dispose()

    app = FastAPI(
        title="Ask Your Data",
        version="1.0.0",
        lifespan=lifespan,
        description="Ask business questions in plain English; get SQL, a table, a chart and an answer.",
    )
    app.state.services = services

    # Feature routers.
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.include_router(ask.router)
    app.include_router(datasets.router)
    app.include_router(auth.router)
    app.include_router(questions.router)
    app.include_router(metrics.router)

    # Every /api request gets an identity: a signed-in user or an anonymous guest.
    install_session_middleware(app)

    # The page and its assets: browsers re-check them on every load (so an update is never hidden
    # behind a stale file), but Vercel's edge keeps a copy and answers those checks itself. Without
    # this every file went through this Python function, and after idle time each one waited for a
    # cold start. Vercel empties the edge cache on every deploy, so a year is safe.
    @app.middleware("http")
    async def cache_static(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if response.status_code == 200 and (path == "/" or path.startswith("/static/")):
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Vercel-CDN-Cache-Control"] = "max-age=31536000"
        return response

    # Static dashboard: index at "/", assets under "/static".
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
