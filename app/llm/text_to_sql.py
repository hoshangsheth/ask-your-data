"""
The two model calls the agent makes, independent of provider:

    generate_sql()   question (+ earlier turns for follow-ups, + previous error on retry) -> SQLDraft
                     The model first decides the kind: a query, a question about the dataset
                     itself (answered directly from the schema, no SQL), or unanswerable.
    summarize()      question + result rows                -> Summary (answer + chart suggestion)

`LLM` is the Protocol the agent depends on. `TextToSQL` implements it on top of any LLMProvider;
tests implement it with a scripted fake (tests/conftest.py).
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.contracts import LLMProvider, Reasoning
from app.llm.indian_units import inr_words, is_money_column
from app.llm.prompts import (
    DIALECT_NAMES,
    HISTORY_TEMPLATE,
    HISTORY_TURN,
    RETRY_TEMPLATE,
    SQL_SCHEMA,
    SQL_SYSTEM,
    SUMMARY_INR_RULES,
    SUMMARY_MAX_ROWS,
    SUMMARY_SCHEMA,
    SUMMARY_SYSTEM,
)


@dataclass
class SQLDraft:
    answerable: bool
    sql: str
    explanation: str
    usage: dict[str, Any] = field(default_factory=dict)  # model + token counts for this call
    standalone_question: str = ""  # the question rewritten to stand alone (follow-ups)
    kind: str = ""  # "query" | "about" | "unanswerable"; empty = derived from `answerable`
    reply: str = ""  # direct answer for kind "about" (questions about the dataset itself)

    @property
    def mode(self) -> str:
        """The effective kind: "query", "about" or "unanswerable"."""
        if self.kind in ("query", "about", "unanswerable"):
            return self.kind
        return "query" if self.answerable else "unanswerable"


@dataclass
class Summary:
    answer: str
    chart: str  # bar | line | pie | none
    x: str  # column for the x axis / labels
    y: str  # numeric column for the values
    usage: dict[str, Any] = field(default_factory=dict)


class LLM(Protocol):
    """What the agent needs from the model layer."""

    def generate_sql(
        self,
        *,
        question: str,
        schema: str,
        dialect: str,
        previous_sql: str | None = None,
        error: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> SQLDraft: ...

    def summarize(
        self,
        *,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[list[Any]],
        truncated: bool,
        currency: str | None = None,
    ) -> Summary: ...


def _annotate_money(columns: list[str], row: list[Any]) -> list[Any]:
    """Replace raw rupee numbers with 'Rs-in-words (raw)' so the model copies units instead of converting."""
    out = []
    for col, value in zip(columns, row, strict=True):
        if is_money_column(col) and isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(f"{inr_words(value)} ({value})")
        else:
            out.append(value)
    return out


class TextToSQL:
    """Binds the shared prompts to one provider and a model per step."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        sql_model: str,
        summary_model: str,
        sql_reasoning: Reasoning = "medium",
        summary_reasoning: Reasoning = "low",
    ):
        self.provider = provider
        self.sql_model = sql_model  # stronger model: SQL correctness matters most
        self.summary_model = summary_model  # cheaper model: summarising is easy
        self.sql_reasoning = sql_reasoning
        self.summary_reasoning = summary_reasoning

    def describe(self) -> dict[str, str]:
        """Provider and models in use (shown by /api/health and the eval report)."""
        return {"provider": self.provider.name, "sql_model": self.sql_model, "summary_model": self.summary_model}

    def generate_sql(
        self,
        *,
        question: str,
        schema: str,
        dialect: str,
        previous_sql: str | None = None,
        error: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> SQLDraft:
        system = SQL_SYSTEM.format(dialect_name=DIALECT_NAMES.get(dialect, dialect), schema=schema)
        user = ""
        if history:  # follow-up: show the earlier turns so "that" / "same for 2024" can be resolved
            turns = "\n".join(HISTORY_TURN.format(**t) for t in history)
            user = HISTORY_TEMPLATE.format(turns=turns)
        user += f"Question: {question}"
        if previous_sql is not None:  # retry: show the model its failed query and the error
            user += RETRY_TEMPLATE.format(previous_sql=previous_sql, error=error)
        r = self.provider.complete_json(
            model=self.sql_model,
            system=system,
            user=user,
            schema=SQL_SCHEMA,
            schema_name="sql_draft",
            reasoning=self.sql_reasoning,
        )
        d = r.data
        kind = d.get("kind") or ("query" if d.get("answerable") else "unanswerable")  # older shape
        if kind == "about" and not str(d.get("answer") or "").strip():
            kind = "query" if str(d.get("sql") or "").strip() else "unanswerable"  # nothing to show
        return SQLDraft(
            answerable=kind != "unanswerable",
            sql="" if kind == "about" else d.get("sql", ""),
            explanation=d.get("explanation", ""),
            usage=r.usage(),
            standalone_question=str(d.get("standalone_question") or "").strip(),
            kind=kind,
            reply=str(d.get("answer") or "").strip() if kind == "about" else "",
        )

    def summarize(
        self,
        *,
        question: str,
        sql: str,
        columns: list[str],
        rows: list[list[Any]],
        truncated: bool,
        currency: str | None = None,
    ) -> Summary:
        shown = rows[:SUMMARY_MAX_ROWS]
        more = truncated or len(rows) > len(shown)
        note = f" (showing first {len(shown)} of more rows)" if more else ""
        inr = currency == "INR"
        # Rupee amounts are pre-formatted in lakh/crore (small models convert units unreliably).
        shown = [_annotate_money(columns, r) for r in shown] if inr else shown
        user = (
            f"Question: {question}\n\nSQL that was run:\n{sql}\n\n"
            f"Result columns: {json.dumps(columns)}\nResult rows{note}:\n"
            + "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in shown)
        )
        r = self.provider.complete_json(
            model=self.summary_model,
            system=SUMMARY_SYSTEM + (SUMMARY_INR_RULES if inr else ""),
            user=user,
            schema=SUMMARY_SCHEMA,
            schema_name="summary",
            reasoning=self.summary_reasoning,
        )
        return Summary(answer=r.data["answer"], chart=r.data["chart"], x=r.data["x"], y=r.data["y"], usage=r.usage())
