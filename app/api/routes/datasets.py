"""
Datasets: the demo store plus files users upload.

    GET    /api/formats              supported file extensions and the size limit
    GET    /api/datasets             demo store first, then uploads (newest first)
    POST   /api/datasets             upload a file (multipart field "file") -> new dataset
    GET    /api/datasets/{id}        one dataset
    DELETE /api/datasets/{id}        delete an uploaded dataset (the demo store can't be deleted)
"""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from app.api.container import Services
from app.api.dependencies import get_services, require_access
from app.api.schemas import DatasetSummary, DatasetTable, FormatsResponse
from app.core.logging import log_event
from app.datasets.profile import DatasetMeta
from app.datasets.service import UploadError
from app.datasets.store import DatasetNotFound
from app.db.models import metadata
from app.sources import DEMO_ID
from app.sources.demo import DEMO_SUGGESTIONS

router = APIRouter(tags=["datasets"])


def _demo_summary(services: Services) -> DatasetSummary:
    with services.readonly_engine.connect() as conn:
        tables = [
            DatasetTable(
                name=t.name, rows=conn.execute(select(func.count()).select_from(t)).scalar_one(), columns=len(t.columns)
            )
            for t in metadata.sorted_tables
        ]
    return DatasetSummary(id=DEMO_ID, name="Demo store", kind="demo", tables=tables, suggestions=DEMO_SUGGESTIONS)


def _upload_summary(meta: DatasetMeta) -> DatasetSummary:
    return DatasetSummary(
        id=meta.id,
        name=meta.name,
        kind="upload",
        filename=meta.filename,
        file_format=meta.file_format,
        created_at=meta.created_at,
        size_bytes=meta.size_bytes,
        tables=[DatasetTable(name=t.name, rows=t.rows, columns=len(t.columns)) for t in meta.tables],
        suggestions=meta.suggestions,
    )


@router.get("/api/formats", response_model=FormatsResponse)
def formats(services: Services = Depends(get_services)) -> FormatsResponse:
    return FormatsResponse(
        extensions=list(services.datasets.supported_extensions()), max_upload_mb=services.settings.max_upload_mb
    )


@router.get("/api/datasets", response_model=list[DatasetSummary])
def list_datasets(services: Services = Depends(get_services)) -> list[DatasetSummary]:
    return [_demo_summary(services)] + [_upload_summary(m) for m in services.store.list()]


@router.post("/api/datasets", response_model=DatasetSummary, status_code=201, dependencies=[Depends(require_access)])
async def upload_dataset(file: UploadFile = File(...), services: Services = Depends(get_services)) -> DatasetSummary:
    limit = services.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)  # read at most one byte past the limit
    try:
        # Parsing is CPU-bound: run it off the event loop.
        meta = await run_in_threadpool(services.datasets.ingest, data, file.filename or "data")
    except UploadError as e:
        raise HTTPException(e.status_code, str(e)) from e
    log_event(
        "upload",
        dataset_id=meta.id,
        format=meta.file_format,
        size_bytes=meta.size_bytes,
        tables=len(meta.tables),
        rows=sum(t.rows for t in meta.tables),
    )
    return _upload_summary(meta)


@router.get("/api/datasets/{dataset_id}", response_model=DatasetSummary)
def get_dataset(dataset_id: str, services: Services = Depends(get_services)) -> DatasetSummary:
    if dataset_id == DEMO_ID:
        return _demo_summary(services)
    try:
        return _upload_summary(services.store.get(dataset_id))
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found") from e


@router.delete("/api/datasets/{dataset_id}", status_code=204, dependencies=[Depends(require_access)])
def delete_dataset(dataset_id: str, services: Services = Depends(get_services)) -> Response:
    if dataset_id == DEMO_ID:
        raise HTTPException(400, "the demo store can't be deleted")
    services.forget(dataset_id)
    try:
        services.store.delete(dataset_id)
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found") from e
    return Response(status_code=204)
