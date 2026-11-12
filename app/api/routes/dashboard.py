"""
Dashboard data (no AI involved):
    GET /api/kpis     headline KPIs, monthly trend, revenue by region and category
    GET /api/schema   tables, row counts, columns and their descriptions (the "Data" view)
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.analytics.kpis import compute_kpis
from app.api.container import Services
from app.api.dependencies import get_services
from app.api.schemas import ColumnInfo, SchemaResponse, TableInfo
from app.db.catalog import DATA_DICTIONARY
from app.db.models import metadata

router = APIRouter(tags=["dashboard"])


@router.get("/api/kpis")
def kpis(services: Services = Depends(get_services)) -> dict[str, Any]:
    return compute_kpis(services.readonly_engine)


@router.get("/api/schema", response_model=SchemaResponse)
def schema(services: Services = Depends(get_services)) -> SchemaResponse:
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
    return SchemaResponse(tables=tables)
