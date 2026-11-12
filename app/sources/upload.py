"""
A user-uploaded dataset as a DataSource (schema from its stored profile).
"""

from sqlalchemy import Engine

from app.datasets.profile import DatasetMeta, schema_text
from app.sources.base import DataSource


def build_upload_source(meta: DatasetMeta, readonly_engine: Engine) -> DataSource:
    return DataSource(
        id=meta.id,
        name=meta.name,
        kind="upload",
        engine=readonly_engine,
        allowed_tables=frozenset(t.name for t in meta.tables),
        schema_text=schema_text(meta),
        currency=None,  # unknown for arbitrary files: numbers are shown as plain numbers
        suggestions=meta.suggestions,
    )
