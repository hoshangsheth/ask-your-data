"""
Datasets: the demo store plus files users upload.

    GET    /api/formats              supported file extensions and the size limit
    GET    /api/datasets             demo store first, then uploads (newest first)
    POST   /api/datasets             upload a small file in one request (multipart field "file")
    GET    /api/datasets/{id}        one dataset
    DELETE /api/datasets/{id}        delete an uploaded dataset (the demo store can't be deleted)

Uploads are private: uploading needs a signed-in user, and each user only sees and can delete
their own datasets (others' ids answer 404). Every upload is measured for the metrics page.

Multi-part upload (what the browser uses; each request stays under Vercel's 4.5 MB body limit):
    POST   /api/uploads                          {filename, size} -> {upload_id, part_bytes, parts}
    PUT    /api/uploads/{upload_id}/parts/{n}    raw bytes of part n (0-based)
    POST   /api/uploads/{upload_id}/complete     {filename, parts} -> new dataset
"""

import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from app.accounts import Identity
from app.api.container import Services
from app.api.dependencies import get_identity, get_services, owned_upload, require_access, require_user
from app.api.schemas import (
    DatasetSummary,
    DatasetTable,
    FormatsResponse,
    UploadComplete,
    UploadStart,
    UploadStarted,
)
from app.core.logging import log_event
from app.datasets.profile import DatasetMeta
from app.datasets.service import UploadError
from app.datasets.staging import MAX_PARTS, MissingPart, check_upload_id
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
        extensions=list(services.datasets.supported_extensions()),
        max_upload_mb=services.settings.max_upload_mb,
        part_mb=services.settings.upload_part_mb,
    )


@router.get("/api/datasets", response_model=list[DatasetSummary])
def list_datasets(
    services: Services = Depends(get_services), identity: Identity = Depends(get_identity)
) -> list[DatasetSummary]:
    own = [m for m in services.store.list() if identity.signed_in and m.owner_id == identity.user_id]
    return [_demo_summary(services)] + [_upload_summary(m) for m in own]


@router.post("/api/datasets", response_model=DatasetSummary, status_code=201, dependencies=[Depends(require_access)])
async def upload_dataset(
    file: UploadFile = File(...), services: Services = Depends(get_services), user: Identity = Depends(require_user)
) -> DatasetSummary:
    limit = services.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)  # read at most one byte past the limit
    started = time.perf_counter()
    try:
        # Parsing is CPU-bound: run it off the event loop.
        meta = await run_in_threadpool(
            services.datasets.ingest, data, file.filename or "data", owner_id=user.user_id or ""
        )
    except UploadError as e:
        raise HTTPException(e.status_code, str(e)) from e
    await run_in_threadpool(_log_upload, services, meta, started)
    return _upload_summary(meta)


def _log_upload(services: Services, meta: DatasetMeta, started: float) -> None:
    """Measure the upload (size, rows, processing time) for the metrics page and the server log."""
    data = {
        "dataset_id": meta.id,
        "format": meta.file_format,
        "size_bytes": meta.size_bytes,
        "tables": len(meta.tables),
        "rows": sum(t.rows for t in meta.tables),
        "processing_ms": int((time.perf_counter() - started) * 1000),
    }
    log_event("upload", **data)
    try:
        services.log.record_upload(meta.owner_id or None, data)
    except Exception as e:  # metrics must never fail an upload
        log_event("upload_log_failed", error=type(e).__name__)


# ---- multi-part uploads ------------------------------------------------------------------------
def _part_bytes(services: Services) -> int:
    return services.settings.upload_part_mb * 1024 * 1024


@router.post("/api/uploads", response_model=UploadStarted, status_code=201, dependencies=[Depends(require_access)])
def start_upload(
    body: UploadStart, services: Services = Depends(get_services), _: Identity = Depends(require_user)
) -> UploadStarted:
    try:
        services.datasets.check_upload(body.filename, body.size)
    except UploadError as e:
        raise HTTPException(e.status_code, str(e)) from e
    part = _part_bytes(services)
    return UploadStarted(upload_id=uuid.uuid4().hex, part_bytes=part, parts=max(1, -(-body.size // part)))


@router.put("/api/uploads/{upload_id}/parts/{index}", status_code=204, dependencies=[Depends(require_access)])
async def upload_part(
    upload_id: str,
    index: int,
    request: Request,
    services: Services = Depends(get_services),
    _: Identity = Depends(require_user),
) -> Response:
    if not 0 <= index < MAX_PARTS:
        raise HTTPException(400, "invalid part number")
    try:
        check_upload_id(upload_id)
    except MissingPart as e:
        raise HTTPException(404, str(e)) from e
    data = await request.body()
    if not data:
        raise HTTPException(400, "empty part")
    if len(data) > _part_bytes(services):
        raise HTTPException(413, "part is larger than the part size")
    await run_in_threadpool(services.staging.put_part, upload_id, index, data)
    return Response(status_code=204)


def _complete(services: Services, upload_id: str, body: UploadComplete, owner_id: str) -> DatasetMeta:
    """Join the parts, keep the original, build the dataset; staged parts are always removed."""
    try:
        data = services.staging.assemble(upload_id, body.parts)
        if len(data) > services.datasets.max_bytes:
            raise UploadError("the file is larger than the upload limit", status_code=413)
        services.datasets.check_upload(body.filename, len(data))
        try:
            url = services.staging.keep_original(upload_id, body.filename, data)
        except Exception as e:  # the dataset is usable without its original file
            log_event("keep_original_failed", upload_id=upload_id, error=type(e).__name__)
            url = ""
        try:
            return services.datasets.ingest(data, body.filename, source_url=url, owner_id=owner_id)
        except Exception:
            services.staging.delete_original(url)  # don't keep files of failed uploads
            raise
    finally:
        try:
            services.staging.discard(upload_id)
        except Exception as e:
            log_event("discard_failed", upload_id=upload_id, error=type(e).__name__)


@router.post(
    "/api/uploads/{upload_id}/complete",
    response_model=DatasetSummary,
    status_code=201,
    dependencies=[Depends(require_access)],
)
async def complete_upload(
    upload_id: str,
    body: UploadComplete,
    services: Services = Depends(get_services),
    user: Identity = Depends(require_user),
) -> DatasetSummary:
    started = time.perf_counter()
    try:
        check_upload_id(upload_id)
        meta = await run_in_threadpool(_complete, services, upload_id, body, user.user_id or "")
    except MissingPart as e:
        raise HTTPException(409, str(e)) from e
    except UploadError as e:
        raise HTTPException(e.status_code, str(e)) from e
    await run_in_threadpool(_log_upload, services, meta, started)
    return _upload_summary(meta)


@router.get("/api/datasets/{dataset_id}", response_model=DatasetSummary)
def get_dataset(
    dataset_id: str, services: Services = Depends(get_services), identity: Identity = Depends(get_identity)
) -> DatasetSummary:
    if dataset_id == DEMO_ID:
        return _demo_summary(services)
    try:
        return _upload_summary(owned_upload(services, dataset_id, identity))
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found") from e


@router.delete("/api/datasets/{dataset_id}", status_code=204, dependencies=[Depends(require_access)])
def delete_dataset(
    dataset_id: str, services: Services = Depends(get_services), identity: Identity = Depends(get_identity)
) -> Response:
    if dataset_id == DEMO_ID:
        raise HTTPException(400, "the demo store can't be deleted")
    try:
        owned_upload(services, dataset_id, identity)
        services.forget(dataset_id)
        meta = services.store.delete(dataset_id)
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found") from e
    try:
        services.staging.delete_original(meta.source_url)
    except Exception as e:  # the dataset is gone; a leftover file is only storage
        log_event("delete_original_failed", dataset_id=dataset_id, error=type(e).__name__)
    return Response(status_code=204)
