"""
SQLAgent: the text-to-SQL workflow as a LangGraph state machine.

    START -> generate_sql -> validate -> execute -> summarize -> END
                 ^  |           |          |
                 |  +-> END (question not answerable from this data)
                 +------ retry -+----------+   (error fed back to the model, up to max_attempts)
                                |          |
                                +-> fail <-+   (attempts exhausted) -> END

Usage:
    agent = SQLAgent(llm, readonly_engine, max_rows=500, max_attempts=3, timeout_ms=5000)
    result = agent.ask("Top 5 products by revenue in 2025")
    # result: status, answer, sql, explanation, columns, rows, chart, attempts, trace, usage, latency_ms
"""

import time
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy import Engine

from app.agent.charts import pick_chart
from app.agent.state import AgentState
from app.db.catalog import describe_schema
from app.db.engine import dialect_of
from app.db.executor import QueryError, run_readonly
from app.db.models import ALLOWED_TABLES
from app.llm import LLM, LLMError
from app.sql.guard import SQLValidationError, validate_sql


def _step(name: str, started: float, **info: Any) -> list[dict]:
    """One trace entry (a list, because `trace` is merged with an append reducer)."""
    return [{"step": name, "ms": int((time.perf_counter() - started) * 1000), **info}]


def _tokens(usage: dict | None) -> dict:
    """Token fields to attach to a trace entry, if the LLM reported usage."""
    if not usage:
        return {}
    return {
        "model": usage.get("model"),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


class SQLAgent:
    def __init__(self, llm: LLM, engine: Engine, *, max_rows: int = 500, max_attempts: int = 3, timeout_ms: int = 5000):
        self.llm = llm
        self.engine = engine  # must be the READ-ONLY engine
        self.dialect = dialect_of(engine)
        self.max_rows = max_rows
        self.max_attempts = max_attempts
        self.timeout_ms = timeout_ms
        self.schema_text = describe_schema(engine)  # built once; identical prompt prefix per question
        self.graph = self._build()

    # ---- Nodes: each does one thing and returns a partial state update ----------------------
    def _generate(self, state: AgentState) -> AgentState:
        """Ask the model for SQL (on retry, include the failed SQL and its error)."""
        t = time.perf_counter()
        retry = state.get("error") is not None
        draft = self.llm.generate_sql(
            question=state["question"],
            schema=self.schema_text,
            dialect=self.dialect,
            previous_sql=state.get("sql") if retry else None,
            error=state.get("error"),
        )
        attempts = state.get("attempts", 0) + 1
        tokens = _tokens(draft.usage)
        if not draft.answerable:
            return {
                "attempts": attempts,
                "status": "unanswerable",
                "answer": draft.explanation,
                "explanation": draft.explanation,
                "sql": "",
                "trace": _step("generate_sql", t, attempt=attempts, answerable=False, **tokens),
            }
        return {
            "attempts": attempts,
            "sql": draft.sql,
            "explanation": draft.explanation,
            "error": None,
            "trace": _step("generate_sql", t, attempt=attempts, retry=retry, **tokens),
        }

    def _validate(self, state: AgentState) -> AgentState:
        """Static safety checks; on success, replace the SQL with its normalised form."""
        t = time.perf_counter()
        try:
            v = validate_sql(state["sql"], dialect=self.dialect, allowed_tables=ALLOWED_TABLES, max_rows=self.max_rows)
        except SQLValidationError as e:
            return {"error": f"validation: {e}", "trace": _step("validate", t, ok=False, error=str(e))}
        return {"sql": v.sql, "trace": _step("validate", t, ok=True, tables=v.tables, limit_applied=v.limit_applied)}

    def _execute(self, state: AgentState) -> AgentState:
        """Run the SQL read-only with a timeout."""
        t = time.perf_counter()
        try:
            r = run_readonly(self.engine, state["sql"], max_rows=self.max_rows, timeout_ms=self.timeout_ms)
        except QueryError as e:
            return {"error": f"database: {e}", "trace": _step("execute", t, ok=False, error=str(e))}
        return {
            "columns": r.columns,
            "rows": r.rows,
            "truncated": r.truncated,
            "trace": _step("execute", t, ok=True, rows=len(r.rows), truncated=r.truncated),
        }

    def _summarize(self, state: AgentState) -> AgentState:
        """Ask the model for a plain-English answer and a chart suggestion."""
        t = time.perf_counter()
        s = self.llm.summarize(
            question=state["question"],
            sql=state["sql"],
            columns=state["columns"],
            rows=state["rows"],
            truncated=state.get("truncated", False),
        )
        chart = pick_chart(s.chart, s.x, s.y, state["columns"], state["rows"])
        return {
            "answer": s.answer,
            "chart": chart,
            "status": "ok",
            "trace": _step("summarize", t, chart=chart["type"] if chart else "none", **_tokens(s.usage)),
        }

    def _fail(self, state: AgentState) -> AgentState:
        """Terminal node when all attempts failed."""
        return {
            "status": "failed",
            "answer": f"I couldn't build a working query after {state.get('attempts', 0)} attempts. "
            f"Last error: {state.get('error')}",
        }

    # ---- Routing ----------------------------------------------------------------------------
    def _after_generate(self, state: AgentState) -> str:
        return END if state.get("status") == "unanswerable" else "validate"

    def _retry_or(self, next_node: str):
        """Router factory: go on if the step succeeded, else retry or give up."""

        def route(state: AgentState) -> str:
            if state.get("error") is None:
                return next_node
            return "generate_sql" if state.get("attempts", 0) < self.max_attempts else "fail"

        return route

    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("generate_sql", self._generate)
        g.add_node("validate", self._validate)
        g.add_node("execute", self._execute)
        g.add_node("summarize", self._summarize)
        g.add_node("fail", self._fail)
        g.add_edge(START, "generate_sql")
        g.add_conditional_edges("generate_sql", self._after_generate, ["validate", END])
        g.add_conditional_edges("validate", self._retry_or("execute"), ["execute", "generate_sql", "fail"])
        g.add_conditional_edges("execute", self._retry_or("summarize"), ["summarize", "generate_sql", "fail"])
        g.add_edge("summarize", END)
        g.add_edge("fail", END)
        return g.compile()

    # ---- Public API -------------------------------------------------------------------------
    def ask(self, question: str) -> dict[str, Any]:
        """Answer one question. Raises app.llm.LLMServiceError if the provider is unusable."""
        t = time.perf_counter()
        try:
            final = self.graph.invoke({"question": question, "attempts": 0, "error": None, "trace": []})
        except LLMError as e:  # this question failed at the model; report it as an answer
            final = {"status": "failed", "answer": f"Model error: {e}", "trace": []}

        trace = final.get("trace", [])
        return {
            "status": final.get("status", "failed"),
            "question": question,
            "answer": final.get("answer", ""),
            "sql": final.get("sql", ""),
            "explanation": final.get("explanation", ""),
            "columns": final.get("columns", []),
            "rows": final.get("rows", []),
            "truncated": final.get("truncated", False),
            "chart": final.get("chart"),
            "attempts": final.get("attempts", 0),
            "trace": trace,
            "usage": {
                "input_tokens": sum(s.get("input_tokens", 0) for s in trace),
                "output_tokens": sum(s.get("output_tokens", 0) for s in trace),
            },
            "latency_ms": int((time.perf_counter() - t) * 1000),
        }
