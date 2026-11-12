"""
Dashboard data (no AI involved):
    GET /api/kpis                 demo store KPIs, monthly trend, revenue by region and category
    GET /api/schema?dataset=ID    tables, row counts, columns and descriptions (the "Data" view)
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.analytics.kpis import compute_kpis
from app.api.container import Services
from app.api.dependencies import get_services
from app.api.schemas import ColumnInfo, SchemaResponse, TableInfo
from app.datasets.profile import ColumnProfile
from app.datasets.store import DatasetNotFound
from app.db.catalog import DATA_DICTIONARY
from app.db.models import metadata
from app.sources import DEMO_ID

router = APIRouter(tags=["dashboard"])


@router.get("/api/kpis")
def kpis(services: Services = Depends(get_services)) -> dict[str, Any]:
    return compute_kpis(services.readonly_engine)


def _describe_column(c: ColumnProfile) -> str:
    """Short human description of an uploaded column from its profile."""
    parts = [f'"{c.original_name}" in file'] if c.original_name else []
    if c.min is not None:
        parts.append(f"{c.min} to {c.max}")
    if c.complete_values and c.values:
        shown = ", ".join(map(str, c.values[:6])) + ("…" if len(c.values) > 6 else "")
        parts.append(f"values: {shown}")
    elif c.values:
        parts.append(f"e.g. {', '.join(map(str, c.values))}")
    parts.append(f"{c.distinct:,} distinct")
    return "; ".join(parts)


@router.get("/api/schema", response_model=SchemaResponse)
def schema(dataset: str = Query(DEMO_ID, max_length=40), services: Services = Depends(get_services)) -> SchemaResponse:
    if dataset == DEMO_ID:
        tables: dict[str, TableInfo] = {}
        with services.readonly_engine.connect() as conn:
            for t in metadata.sorted_tables:
                docs = DATA_DICTIONARY.get(t.name, {})
                tables[t.name] = TableInfo(
                    description=docs.get("_table", ""),
                    row_count=conn.execute(select(func.count()).select_from(t)).scalar_one(),
                    columns=[
                        ColumnInfo(name=c.name, type=str(c.type), description=docs.get(c.name, "")) for c in t.columns
                    ],
                )
        return SchemaResponse(dataset_id=DEMO_ID, tables=tables)

    try:
        meta = services.store.get(dataset)
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found") from e
    return SchemaResponse(
        dataset_id=meta.id,
        tables={
            t.name: TableInfo(
                description=f"From {meta.filename}"
                + (f" (sheet/table '{t.source_name}')" if t.source_name != t.name else ""),
                row_count=t.rows,
                columns=[ColumnInfo(name=c.name, type=c.type, description=_describe_column(c)) for c in t.columns],
            )
            for t in meta.tables
        },
    )
