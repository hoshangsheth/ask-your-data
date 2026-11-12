"""
Tables the application itself owns (separate from the demo store and uploaded data):

    users          accounts (email + scrypt password hash)
    app_secrets    generated secrets shared by every instance (e.g. the session-signing key)
    questions      one row per question asked: answer, SQL, timings, tokens, cost, feedback
    usage_events   other measured events (uploads), payload as JSON

They are created at startup (app/api/factory.py) next to the demo tables. Model-generated SQL can't
reach them: the SQL guard only allows the selected dataset's tables.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)

app_metadata = MetaData()

users = Table(
    "users",
    app_metadata,
    Column("id", String(12), primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
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
