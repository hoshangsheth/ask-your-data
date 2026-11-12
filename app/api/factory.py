"""
Application factory: builds a fully wired FastAPI app.

Usage:
    from app.api.factory import create_app
    app = create_app()                              # settings from env/.env, LLM from settings
    app = create_app(Settings(...), llm=FakeLLM())  # tests: custom settings, scripted model

Startup (lifespan): seeds the SQLite demo database if empty (AUTO_SEED=true), otherwise just
ensures tables exist. Shutdown: closes connection pools.
"""

import mimetypes
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import exc as sa_exc

from app.api.container import Services
from app.api.routes import ask, dashboard, health
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event
from app.db.models import metadata
from app.db.seed import seed
from app.llm import LLM

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"

# Windows can map .js to text/plain via the registry; browsers refuse ES modules served that way.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# SQLite stores NUMERIC as REAL and SQLAlchemy warns on every query. Expected for the demo DB.
warnings.filterwarnings("ignore", category=sa_exc.SAWarning, message=".*Decimal objects natively.*")


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or get_settings()
    services = Services(settings, llm)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        configure_logging()
        if settings.auto_seed and services.owner_engine.dialect.name == "sqlite":
            counts = seed(services.owner_engine)  # no-op if data already exists
            if counts:
                log_event("seeded", **counts)
        else:
            metadata.create_all(services.owner_engine)
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

    # Make browsers re-check the page and its assets on every load (cheap 304 if unchanged), so a
    # code update is never hidden behind a stale cached file.
    @app.middleware("http")
    async def revalidate_static(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Static dashboard: index at "/", assets under "/static".
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
