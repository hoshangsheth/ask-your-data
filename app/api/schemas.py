"""
Request and response models for the HTTP API. They validate input, document the API at /docs,
and fix the response shapes the frontend (app/web/static/js/) relies on.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.sources import DEMO_ID


# ---- /api/ask -------------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500, examples=["Which region's revenue dropped last quarter?"])
    dataset_id: str = Field(default=DEMO_ID, max_length=40, description='"demo" or an uploaded dataset id')


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
    dataset_id: str
    currency: str | None  # "INR" -> the UI formats money in lakh/crore
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
    storage: dict[str, str] = {}  # {"datasets": "postgres" | "sqlite-files", "files": "vercel-blob" | "local"}


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
    dataset_id: str = DEMO_ID
    tables: dict[str, TableInfo]


# ---- /api/datasets --------------------------------------------------------------------------
class DatasetTable(BaseModel):
    name: str
    rows: int
    columns: int


class DatasetSummary(BaseModel):
    id: str
    name: str
    kind: Literal["demo", "upload"]
    filename: str = ""
    file_format: str = ""
    created_at: str = ""
    size_bytes: int = 0
    tables: list[DatasetTable]
    suggestions: list[str]


class FormatsResponse(BaseModel):
    extensions: list[str]
    max_upload_mb: int
    part_mb: int = 4  # browsers upload files in parts of this size


# ---- /api/uploads (multi-part uploads) --------------------------------------------------------
class UploadStart(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)


class UploadStarted(BaseModel):
    upload_id: str
    part_bytes: int
    parts: int


class UploadComplete(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    parts: int = Field(ge=1, le=1000)
