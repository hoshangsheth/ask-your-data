"""
Eval dataset access.

Each line of questions.jsonl is one object:
    {"id": "...", "question": "...", "sql": "<PostgreSQL reference>"}      answerable question
    {"id": "...", "question": "...", "unanswerable": true}                  agent must decline
    {"id": "...", "turns": ["earlier question", ...], "question": "follow-up", "sql": "..."}
                                                    follow-up: earlier turns are asked first
    {"id": "...", "question": "...", "about": true, "mentions": ["word", ...]}
                                                    about the data: answered without SQL, and
                                                    the answer must mention every listed word

Reference SQL is written for PostgreSQL and transpiled with sqlglot for other databases.
"""

import json
from pathlib import Path

import sqlglot

QUESTIONS_FILE = Path(__file__).with_name("questions.jsonl")


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    """All eval items, in file order."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def category(item: dict) -> str:
    """'about_data', 'unanswerable', 'follow_up' or 'single_turn' (reported separately)."""
    if item.get("about"):
        return "about_data"
    if item.get("unanswerable"):
        return "unanswerable"
    return "follow_up" if item.get("turns") else "single_turn"


def reference_sql(item: dict, dialect: str) -> str:
    """Reference SQL for `dialect` ("postgres" returns it unchanged)."""
    if dialect == "postgres":
        return item["sql"]
    return sqlglot.transpile(item["sql"], read="postgres", write=dialect)[0]
