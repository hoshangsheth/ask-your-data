"""
State passed between the agent's graph nodes.

Each node returns a partial dict; LangGraph merges it into the state. `trace` uses an
append reducer (operator.add), so every node adds its own step instead of overwriting the list.
"""

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    sql: str  # latest SQL (validated/normalised after the validate node)
    explanation: str  # model's explanation of the SQL, or why it is unanswerable
    error: str | None  # last validation/database error; None after a successful step
    attempts: int  # SQL generation attempts so far
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    answer: str
    chart: dict | None  # {"type", "x", "y"} or None
    status: str  # ok | unanswerable | failed
    trace: Annotated[list[dict], operator.add]  # one entry per executed step
