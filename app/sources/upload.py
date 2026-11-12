"""
A user-uploaded dataset as a DataSource (schema from its stored profile).

    build_upload_source(meta, readonly_engine, schema=None)
        schema: the Postgres schema holding the dataset's tables (cloud storage); None for SQLite.
"""

from sqlalchemy import Engine

from app.datasets.profile import DatasetMeta, schema_text
from app.db.engine import dialect_of
from app.sources.base import DataSource


def build_upload_source(meta: DatasetMeta, readonly_engine: Engine, schema: str | None = None) -> DataSource:
    return DataSource(
        id=meta.id,
        name=meta.name,
        kind="upload",
        engine=readonly_engine,
        allowed_tables=frozenset(t.name for t in meta.tables),
        schema_text=schema_text(meta, dialect_of(readonly_engine)),
        currency=None,  # unknown for arbitrary files: numbers are shown as plain numbers
        suggestions=meta.suggestions,
        schema=schema,
    )
