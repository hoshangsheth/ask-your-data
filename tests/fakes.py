"""
Test doubles shared across the suite.

FakeLLM implements the agent's LLM protocol (app/llm/text_to_sql.py) with scripted responses,
so agent and API behaviour can be tested deterministically and for free.
"""

from dataclasses import dataclass, field
from typing import Any

from app.llm import SQLDraft, Summary

# A valid query used by many tests: customer count per region (4 rows).
GOOD_DRAFT = SQLDraft(
    True, "SELECT c.region, COUNT(*) AS customers FROM customers c GROUP BY c.region", "Counts by region."
)


@dataclass
class FakeLLM:
    """Returns `drafts` in order from generate_sql, and `summary` from summarize; records calls."""

    drafts: list[SQLDraft]
    summary: Summary = field(default_factory=lambda: Summary("Fake answer.", "bar", "region", "customers"))
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate_sql(self, **kwargs) -> SQLDraft:
        self.calls.append({"fn": "generate_sql", **kwargs})
        return self.drafts.pop(0)

    def summarize(self, **kwargs) -> Summary:
        self.calls.append({"fn": "summarize", **kwargs})
        return self.summary
