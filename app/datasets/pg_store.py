"""
Postgres dataset storage (cloud deployment, e.g. Neon on Vercel).

Layout:
    datasets                 one row per upload: id, created_at, meta (profile as jsonb)
    ds_<id>.<table>          the uploaded tables, one schema per dataset

Questions about a dataset run with `SET LOCAL search_path TO ds_<id>` (see app/db/executor.py),
and the SQL guard rejects schema-qualified names, so a query can only see that dataset's tables.

Usage (same interface as LocalDatasetStore):
    store = PostgresDatasetStore(owner_engine, readonly_engine)
    store.save(meta, tables); store.get(id); store.list(); store.delete(id)
    store.readonly_engine(id), store.schema_for(id)
"""

import json
from typing import Any

from sqlalchemy import Column, Connection, DateTime, Engine, MetaData, String, Table, delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB

from app.datasets.cleaning import CleanTable
from app.datasets.profile import DatasetMeta
from app.datasets.store import DatasetNotFound, check_id

_meta = MetaData()
datasets_table = Table(
    "datasets",
    _meta,
    Column("id", String(12), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("meta", JSONB, nullable=False),
)


def schema_name(dataset_id: str) -> str:
    """'3f9a1c2b7d10' -> 'ds_3f9a1c2b7d10' (ids are validated hex, so this is a safe identifier)."""
    return f"ds_{check_id(dataset_id)}"


def _copy_rows(table: Any, conn: Any, keys: list[str], data_iter: Any) -> None:
    """pandas to_sql `method`: load rows with COPY (much faster than INSERTs over the network)."""
    cols = ", ".join(f'"{k}"' for k in keys)
    with conn.connection.cursor() as cur, cur.copy(f'COPY "{table.schema}"."{table.name}" ({cols}) FROM STDIN') as copy:
        for row in data_iter:
            copy.write_row(row)


class PostgresDatasetStore:
    def __init__(self, owner: Engine, readonly: Engine):
        self.owner = owner
        self.readonly = readonly

    def create_tables(self, bind: Engine | Connection | None = None) -> None:
        """Create the `datasets` table if missing (called at startup, inside its locked transaction)."""
        _meta.create_all(bind if bind is not None else self.owner)

    # ---- write ---------------------------------------------------------------------------------
    def save(self, meta: DatasetMeta, tables: list[CleanTable]) -> None:
        schema = schema_name(meta.id)
        payload = json.loads(json.dumps(meta.to_dict(), default=str))  # numpy/dates -> JSON types
        with self.owner.begin() as conn:  # schema, tables and metadata row commit together or not at all
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            for t in tables:
                t.frame.to_sql(t.name, conn, schema=schema, index=False, method=_copy_rows, chunksize=20_000)
            ro_user = self.readonly.url.username
            if self.readonly is not self.owner and ro_user and ro_user != self.owner.url.username:
                # A separate read-only role (docker-compose) needs read access to the new schema.
                role = ro_user.replace('"', "")
                conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
                conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
            conn.execute(insert(datasets_table).values(id=meta.id, meta=payload))

    def delete(self, dataset_id: str) -> DatasetMeta:
        meta = self.get(dataset_id)
        with self.owner.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name(dataset_id)}" CASCADE'))
            conn.execute(delete(datasets_table).where(datasets_table.c.id == dataset_id))
        return meta

    # ---- read ----------------------------------------------------------------------------------
    def get(self, dataset_id: str) -> DatasetMeta:
        check_id(dataset_id)
        with self.owner.connect() as conn:
            row = conn.execute(select(datasets_table.c.meta).where(datasets_table.c.id == dataset_id)).first()
        if row is None:
            raise DatasetNotFound(dataset_id)
        return DatasetMeta.from_dict(row.meta)

    def list(self) -> list[DatasetMeta]:
        with self.owner.connect() as conn:
            rows = conn.execute(select(datasets_table.c.meta).order_by(datasets_table.c.created_at.desc())).all()
        out = []
        for r in rows:
            try:
                out.append(DatasetMeta.from_dict(r.meta))
            except (ValueError, KeyError, TypeError):
                continue  # skip a corrupt row rather than failing the whole list
        return out

    def readonly_engine(self, dataset_id: str) -> Engine:
        self.get(dataset_id)  # raises DatasetNotFound
        return self.readonly  # one engine for all datasets; the schema is chosen per query

    def schema_for(self, dataset_id: str) -> str | None:
        return schema_name(dataset_id)

    def dispose(self) -> None:
        pass  # engines belong to the services container
