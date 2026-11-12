"""
The built-in demo store as a DataSource (schema from app/db/catalog.py, money in INR).
"""

from sqlalchemy import Engine

from app.db.catalog import describe_schema
from app.db.models import ALLOWED_TABLES
from app.sources.base import DEMO_ID, DataSource

DEMO_SUGGESTIONS = [
    "Which region's revenue dropped last quarter?",
    "Top 5 products by revenue in 2025",
    "Show monthly revenue for 2025",
    "What is the cancellation rate for each payment method?",
    "Which category has the highest return rate?",
    "How many active customers did we have in 2025?",
]


def build_demo_source(readonly_engine: Engine) -> DataSource:
    return DataSource(
        id=DEMO_ID,
        name="Demo store",
        kind="demo",
        engine=readonly_engine,
        allowed_tables=ALLOWED_TABLES,
        schema_text=describe_schema(readonly_engine),
        currency="INR",
        suggestions=DEMO_SUGGESTIONS,
    )
