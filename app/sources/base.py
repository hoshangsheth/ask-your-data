"""
The DataSource value object passed to the agent.
"""

from dataclasses import dataclass, field

from sqlalchemy import Engine

from app.db.engine import dialect_of

DEMO_ID = "demo"  # id of the built-in demo store


@dataclass(frozen=True)
class DataSource:
    id: str
    name: str
    kind: str  # "demo" | "upload"
    engine: Engine  # READ-ONLY engine for this dataset
    allowed_tables: frozenset[str]
    schema_text: str  # schema + definitions sent to the model
    currency: str | None = None  # e.g. "INR": money is pre-formatted in lakh/crore for the summary
    suggestions: list[str] = field(default_factory=list)

    @property
    def dialect(self) -> str:
        return dialect_of(self.engine)
