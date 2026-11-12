"""
Request and response models for the HTTP API. They validate input, document the API at /docs,
and fix the response shape the frontend (app/web/static/app.js) relies on.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- /api/ask -------------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500, examples=["Which region's revenue dropped last quarter?"])


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "pie"]
    x: str
    y: str


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class AskResponse(BaseModel):
    status: Literal["ok", "unanswerable", "failed"]
    question: str
    answer: str
    sql: str
    explanation: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    chart: ChartSpec | None
    attempts: int
    trace: list[dict[str, Any]]  # one entry per agent step (timing, errors, tokens)
    usage: TokenUsage
    latency_ms: int


# ---- /api/health ----------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: str
    llm_provider: str
    sql_model: str
    summary_model: str
    llm_ready: bool  # an API key for the provider is configured (the UI shows setup steps if not)


# ---- /api/schema ----------------------------------------------------------------------------
class ColumnInfo(BaseModel):
    name: str
    type: str
    description: str = ""


class TableInfo(BaseModel):
    description: str = ""
    row_count: int = 0
    columns: list[ColumnInfo]


class SchemaResponse(BaseModel):
    tables: dict[str, TableInfo]
