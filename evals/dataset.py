"""
Eval dataset access.

Each line of questions.jsonl is one object:
    {"id": "...", "question": "...", "sql": "<PostgreSQL reference>"}      answerable question
    {"id": "...", "question": "...", "unanswerable": true}                  agent must decline

Reference SQL is written for PostgreSQL and transpiled with sqlglot for other databases.
"""

import json
from pathlib import Path

import sqlglot

QUESTIONS_FILE = Path(__file__).with_name("questions.jsonl")


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    """All eval items, in file order."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reference_sql(item: dict, dialect: str) -> str:
    """Reference SQL for `dialect` ("postgres" returns it unchanged)."""
    if dialect == "postgres":
        return item["sql"]
    return sqlglot.transpile(item["sql"], read="postgres", write=dialect)[0]
