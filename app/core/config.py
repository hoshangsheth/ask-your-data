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

Paths: `.env` and relative SQLite paths (sqlite:///./data/shop.db) are resolved against the
project root, not the current folder, so the app behaves the same wherever it is started from.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# D:\Ask Your Data (this file is app/core/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

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

    # ---- API protection ----------------------------------------------------------------------
    app_api_key: str = ""  # if set, POST /api/ask requires header X-API-Key
    rate_limit_per_minute: int = 20  # per client IP on POST /api/ask; 0 disables

    # ---- Startup -----------------------------------------------------------------------------
    auto_seed: bool = True  # seed the SQLite demo database on first start


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (read once, then cached)."""
    return Settings()
