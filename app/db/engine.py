"""
Database engines.

Two engines are created from configuration:
    owner     creates tables and loads demo data
    readonly  runs model-generated SQL (SQLite: file opened read-only; Postgres: a read-only role)

Usage:
    from app.db.engine import make_engines, dialect_of
    owner, readonly = make_engines(settings.database_url, settings.readonly_database_url)
    dialect_of(readonly)   # "sqlite" or "postgres" (sqlglot dialect names)
"""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from app.core.config import PROJECT_ROOT


def dialect_of(engine: Engine) -> str:
    """Return the sqlglot dialect name for an engine."""
    return "postgres" if engine.dialect.name == "postgresql" else engine.dialect.name


def make_engines(database_url: str, readonly_database_url: str = "") -> tuple[Engine, Engine]:
    """Return (owner_engine, readonly_engine) for the configured database."""
    url = make_url(database_url)

    if url.get_backend_name() == "sqlite":
        # Relative paths are relative to the project root (not the current folder), so starting
        # the app from a subfolder never creates a second, empty database somewhere else.
        path = Path(url.database or "")
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        owner = create_engine(f"sqlite:///{path.as_posix()}")
        # mode=ro makes SQLite itself refuse every write on this connection.
        ro_url = readonly_database_url or f"sqlite:///file:{path.as_posix()}?mode=ro&uri=true"
        return owner, create_engine(ro_url)

    # Postgres (or another server database): use the dedicated read-only role when configured.
    owner = create_engine(database_url, pool_pre_ping=True)
    readonly = create_engine(readonly_database_url, pool_pre_ping=True) if readonly_database_url else owner
    return owner, readonly
