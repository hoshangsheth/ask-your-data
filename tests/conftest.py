"""
Shared pytest fixtures.

The database is seeded once per test session with a small dataset. By default it is a temporary
SQLite file; set TEST_DATABASE_URL (and TEST_READONLY_DATABASE_URL) to run against Postgres,
as CI does.
"""

import os

import pytest

from app.core.config import Settings
from app.db.engine import make_engines
from app.db.seed import seed


@pytest.fixture(scope="session")
def db_url(tmp_path_factory) -> str:
    """URL of a freshly seeded test database."""
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"
    owner, _ = make_engines(url)
    seed(owner, force=True, n_customers=300, n_orders=2500)
    owner.dispose()
    return url


@pytest.fixture(scope="session")
def engines(db_url):
    """(owner_engine, readonly_engine) for the test database."""
    owner, ro = make_engines(db_url, os.environ.get("TEST_READONLY_DATABASE_URL", ""))
    yield owner, ro
    owner.dispose()
    ro.dispose()


@pytest.fixture
def ro_engine(engines):
    """The read-only engine (what the agent and KPIs use)."""
    return engines[1]


@pytest.fixture
def settings(db_url, tmp_path) -> Settings:
    """App settings for the test database: no seeding, no API key, no rate limit, no .env file,
    and uploads in a temporary folder (never the real data/uploads)."""
    return Settings(
        uploads_dir=str(tmp_path / "uploads"),
        database_url=db_url,
        readonly_database_url=os.environ.get("TEST_READONLY_DATABASE_URL", ""),
        auto_seed=False,
        app_api_key="",
        questions_per_minute=0,
        questions_per_day_user=0,
        questions_per_day_guest=0,
        questions_per_day_site=0,
        upload_requests_per_minute=0,
        _env_file=None,
    )
