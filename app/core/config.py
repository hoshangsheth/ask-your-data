"""
Application settings.

Every value can be set as an environment variable or in a `.env` file at the project root
(copy `.env.example` to `.env`). Names are case-insensitive: field `llm_provider` is read
from `LLM_PROVIDER`.

Usage:
    from app.core.config import get_settings
    settings = get_settings()          # cached; one instance per process

In tests, build one directly and skip the .env file:
    Settings(llm_provider="anthropic", _env_file=None)

Paths: `.env` is read from the project root. Relative data paths (sqlite:///./data/shop.db,
data/uploads) are resolved against DATA_ROOT: the project root locally, a temporary folder on
Vercel (the deployed code folder is read-only there).

Cloud (Vercel): set DATABASE_URL to Postgres (Neon) and connect a Blob store
(BLOB_READ_WRITE_TOKEN); uploads then go to Postgres + Blob automatically. See docs/DEPLOYMENT.md.
"""

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# D:\Ask Your Data (this file is app/core/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# True inside Vercel Functions (Vercel sets VERCEL=1).
ON_VERCEL = bool(os.environ.get("VERCEL"))

# Where relative data paths live: writable everywhere we run.
DATA_ROOT = Path(tempfile.gettempdir()) / "ask-your-data" if ON_VERCEL else PROJECT_ROOT

ReasoningLevel = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    """All runtime configuration. Defaults give a working local demo (SQLite + Gemini)."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ---- AI provider: swap without code changes ----------------------------------------------
    llm_provider: str = "gemini"  # gemini | anthropic | openai
    llm_sql_model: str = ""  # empty = provider default (app/llm/factory.py)
    llm_summary_model: str = ""  # empty = provider default
    # Mapped per provider (thinking level / effort). "low" measured ~4x faster than "medium" on
    # Gemini 3.8 Flash with the same correct SQL; raise it if the eval shows accuracy gains.
    llm_sql_reasoning: ReasoningLevel = "low"
    llm_summary_reasoning: ReasoningLevel = "low"
    llm_timeout_s: float = 60.0
    # Only the key for the selected provider is needed.
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ---- Database ----------------------------------------------------------------------------
    # Owner connection: used only to create tables and seed demo data.
    database_url: str = "sqlite:///./data/shop.db"
    # Connection used for model-generated SQL. Point it at a read-only role in production.
    # Empty = derived from database_url (SQLite then opens the file in read-only mode).
    readonly_database_url: str = ""
    max_rows: int = 500  # hard cap on rows returned per query
    max_attempts: int = 3  # SQL generation attempts before giving up
    query_timeout_ms: int = 5000  # per-query execution time limit

    # ---- User uploads ------------------------------------------------------------------------
    uploads_dir: str = "data/uploads"  # local backend only; relative paths are under DATA_ROOT
    max_upload_mb: int = 50
    # Browsers send files in parts of this size (Vercel caps a request body at 4.5 MB).
    upload_part_mb: int = 4
    # Where upload parts and original files go: "blob" (Vercel Blob), "local", or "auto" (Blob
    # when BLOB_READ_WRITE_TOKEN is set). Uploaded tables go to Postgres when DATABASE_URL is
    # Postgres, otherwise to one SQLite file per dataset.
    upload_storage: Literal["auto", "local", "blob"] = "auto"
    blob_read_write_token: str = ""  # set by Vercel when a Blob store is connected

    # ---- API protection ----------------------------------------------------------------------
    app_api_key: str = ""  # if set, POST /api/ask requires header X-API-Key
    rate_limit_per_minute: int = 20  # per client IP on POST /api/ask; 0 disables

    # ---- Startup -----------------------------------------------------------------------------
    auto_seed: bool = True  # seed the SQLite demo database on first start


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (read once, then cached)."""
    return Settings()
