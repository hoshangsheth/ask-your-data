"""
Read-only query execution.

`run_readonly` is the second of three safety layers for model-generated SQL:
    1. app/sql/guard.py   static checks before anything runs
    2. this module        read-only transaction, time limit, row cap, always rolled back
    3. database role      a Postgres role with SELECT-only grants (docker/init-readonly.sql)

Usage:
    from app.db.executor import run_readonly, QueryError
    result = run_readonly(engine, "SELECT ...", max_rows=500, timeout_ms=5000)
    result.columns, result.rows, result.truncated, result.elapsed_ms
"""

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class QueryError(Exception):
    """The database rejected or aborted a query. The message is safe to show to the model."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]  # JSON-safe values
    truncated: bool  # True if more than max_rows rows existed
    elapsed_ms: int


def jsonable(value: Any) -> Any:
    """Convert database values (Decimal, date, bytes) into JSON-safe Python values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def run_readonly(engine: Engine, sql: str, *, max_rows: int, timeout_ms: int, schema: str | None = None) -> QueryResult:
    """Execute one SELECT inside a read-only transaction with a timeout, then roll back.

    `schema` (Postgres only) limits name lookup to one schema, e.g. an uploaded dataset's
    "ds_3f9a1c2b7d10". It must come from our own code, never from user input.
    """
    if schema is not None and not _SCHEMA.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    started = time.perf_counter()
    is_pg = engine.dialect.name == "postgresql"
    deadline = started + timeout_ms / 1000

    with engine.connect() as conn:
        # Raw DB-API connection: no SQLAlchemy bind-parameter parsing, so '%' and ':' in SQL are safe.
        dbapi = conn.connection
        raw = dbapi.driver_connection
        cur = dbapi.cursor()
        try:
            if is_pg:
                # SET TRANSACTION must be the first statement; a pool pre-ping may have run one.
                dbapi.rollback()
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                if schema:
                    # pg_catalog stays implicitly reachable; the SQL guard blocks system catalogs.
                    cur.execute(f'SET LOCAL search_path TO "{schema}"')
            else:
                # SQLite has no statement timeout: abort from the VM progress callback instead.
                raw.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10_000)

            cur.execute(sql)
            columns = [d[0] for d in cur.description or []]
            fetched = cur.fetchmany(max_rows + 1)  # one extra row tells us whether we truncated

        except Exception as e:  # driver-specific error classes; normalise them for the agent
            text = str(e).strip()
            msg = text.splitlines()[0] if text else type(e).__name__
            if "interrupted" in msg.lower() or "statement timeout" in msg.lower():
                msg = f"query exceeded the {timeout_ms} ms time limit; simplify it or aggregate more"
            raise QueryError(msg[:500]) from e

        finally:
            if not is_pg:
                raw.set_progress_handler(None, 0)
            cur.close()
            conn.rollback()  # never keep anything, even if the query somehow wrote

    rows = [[jsonable(v) for v in r] for r in fetched[:max_rows]]
    elapsed = int((time.perf_counter() - started) * 1000)
    return QueryResult(columns, rows, len(fetched) > max_rows, elapsed)
