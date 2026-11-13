"""
Tables the application itself owns (separate from the demo store and uploaded data):

    users          accounts (email, scrypt password hash, name, company)
    app_secrets    generated secrets shared by every instance (e.g. the session-signing key)
    questions      one row per question asked: answer, SQL, timings, tokens, cost, feedback
    usage_events   other measured events (uploads), payload as JSON
    usage_counters question quotas: per minute, per day and site-wide counts (app/api/quota.py)

They are created at startup (app/api/factory.py) next to the demo tables; columns added after a
table already existed in a database are added by add_missing_columns() (a tiny migration step). Model-generated SQL can't
reach them: the SQL guard only allows the selected dataset's tables.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Connection,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    inspect,
    text,
)

app_metadata = MetaData()

users = Table(
    "users",
    app_metadata,
    Column("id", String(12), primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Asked at sign-up so feedback can be read with who gave it (added later: see add_missing_columns).
    Column("name", String(100), nullable=False, server_default=""),
    Column("company", String(120), nullable=False, server_default=""),
)

app_secrets = Table(
    "app_secrets",
    app_metadata,
    Column("name", String(64), primary_key=True),
    Column("value", String(255), nullable=False),
)

questions = Table(
    "questions",
    app_metadata,
    Column("id", String(32), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # who asked: a signed-in user, else an anonymous browser (guest cookie)
    Column("user_id", String(12), index=True),
    Column("guest_id", String(32), index=True),
    # conversation (follow-ups use the previous turns of the same conversation)
    Column("conversation_id", String(32), nullable=False, index=True),
    Column("turn", Integer, nullable=False, default=1),
    Column("dataset_id", String(40), nullable=False),
    Column("dataset_kind", String(10), nullable=False),
    Column("question", Text, nullable=False),
    Column("standalone_question", Text, nullable=False, default=""),
    Column("sql", Text, nullable=False, default=""),
    Column("answer", Text, nullable=False, default=""),
    Column("status", String(16), nullable=False),  # ok | unanswerable | failed
    Column("attempts", Integer, nullable=False, default=0),
    Column("rows", Integer, nullable=False, default=0),
    Column("chart", String(8), nullable=False, default=""),
    # timings (ms): total and per agent step (summed over retries)
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("sql_ms", Integer, nullable=False, default=0),
    Column("validate_ms", Integer, nullable=False, default=0),
    Column("execute_ms", Integer, nullable=False, default=0),
    Column("summary_ms", Integer, nullable=False, default=0),
    # model usage and estimated cost
    Column("provider", String(20), nullable=False, default=""),
    Column("sql_model", String(60), nullable=False, default=""),
    Column("summary_model", String(60), nullable=False, default=""),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_usd", Float),  # None when the model's price is unknown
    Column("is_follow_up", Boolean, nullable=False, default=False),
    # user feedback: 1 = helpful, -1 = wrong/unhelpful, None = no rating
    Column("feedback", Integer),
    Column("feedback_note", Text, nullable=False, default=""),
)

usage_events = Table(
    "usage_events",
    app_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("kind", String(20), nullable=False, index=True),  # "upload"
    Column("user_id", String(12)),
    Column("data", JSON, nullable=False),
)


usage_counters = Table(
    "usage_counters",
    app_metadata,
    Column("key", String(120), primary_key=True),  # e.g. "d:u:<user id>:2026-11-13", "s:2026-11-13"
    Column("day", String(10), nullable=False, index=True),  # India date, for cleaning up old rows
    Column("count", Integer, nullable=False, default=0),
)


# Columns added to existing tables after the first release: (table, column, DDL type + default).
LATER_COLUMNS = [
    ("users", "name", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("users", "company", "VARCHAR(120) NOT NULL DEFAULT ''"),
]


def add_missing_columns(conn: Connection) -> list[str]:
    """Add columns introduced after a table was first created (SQLite and Postgres). Idempotent."""
    insp = inspect(conn)
    added = []
    for table, column, ddl in LATER_COLUMNS:
        if not insp.has_table(table):
            continue
        if column not in {c["name"] for c in insp.get_columns(table)}:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            added.append(f"{table}.{column}")
    return added
