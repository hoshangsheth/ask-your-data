"""
Actions on an answered question (only the user or guest who asked it can use them):

    POST /api/questions/{id}/feedback          {rating: 1 | -1 | 0, note}   helpful / not / clear
    GET  /api/questions/{id}/export?format=csv  result table as CSV (or format=xlsx for Excel)
    POST /api/questions/{id}/report            {chart_png}  one-page PDF report

Exports re-run the stored SQL (validated again, read-only, up to EXPORT_MAX_ROWS rows) on the
same dataset, so they hold the full result rather than the rows shown in the chat.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.accounts import Identity
from app.api.container import Services
from app.api.dependencies import check_dataset_access, get_identity, get_services
from app.api.schemas import FeedbackRequest, ReportRequest
from app.core.logging import log_event
from app.datasets.store import DatasetNotFound
from app.db.executor import QueryError, run_readonly
from app.exports import Report, decode_png_data_url, filename_for, to_csv, to_pdf, to_xlsx
from app.sql.guard import SQLValidationError, validate_sql
from app.telemetry import StoredQuestion

router = APIRouter(tags=["questions"])

MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _question(services: Services, qid: str, identity: Identity) -> StoredQuestion:
    q = services.log.get(qid, identity) if len(qid) == 32 else None
    if q is None:
        raise HTTPException(404, "question not found")
    return q


def _rows(services: Services, q: StoredQuestion, identity: Identity) -> tuple[list[str], list[list]]:
    if not q.sql:
        raise HTTPException(409, "this question has no result to export")
    check_dataset_access(services, q.dataset_id, identity)
    limit = services.settings.export_max_rows
    try:
        source = services.source(q.dataset_id)
        sql = validate_sql(q.sql, dialect=source.dialect, allowed_tables=source.allowed_tables, max_rows=limit).sql
        r = run_readonly(
            source.engine, sql, max_rows=limit, timeout_ms=services.settings.query_timeout_ms * 3, schema=source.schema
        )
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found; it may have been deleted") from e
    except (SQLValidationError, QueryError) as e:
        raise HTTPException(409, f"couldn't re-run the query: {e}") from e
    return r.columns, r.rows


def _download(content: bytes, fmt: str, question: str) -> Response:
    return Response(
        content,
        media_type=MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename_for(question, fmt)}"'},
    )


@router.post("/api/questions/{qid}/feedback", status_code=204)
def feedback(
    qid: str,
    body: FeedbackRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> Response:
    if len(qid) != 32 or not services.log.set_feedback(qid, identity, body.rating, body.note):
        raise HTTPException(404, "question not found")
    log_event("feedback", question_id=qid, rating=body.rating)
    return Response(status_code=204)


@router.get("/api/questions/{qid}/export")
def export(
    qid: str,
    format: Literal["csv", "xlsx"] = Query("csv"),
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> Response:
    q = _question(services, qid, identity)
    columns, rows = _rows(services, q, identity)
    content = to_csv(columns, rows) if format == "csv" else to_xlsx(columns, rows, q.question)
    log_event("export", question_id=qid, format=format, rows=len(rows))
    return _download(content, format, q.question)


@router.post("/api/questions/{qid}/report")
def report(
    qid: str,
    body: ReportRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> Response:
    q = _question(services, qid, identity)
    columns, rows = _rows(services, q, identity) if q.sql else ([], [])
    name = "Demo store" if q.dataset_id == "demo" else services.store.get(q.dataset_id).name
    pdf = to_pdf(
        Report(
            question=q.standalone_question or q.question,
            answer=q.answer,
            sql=q.sql,
            columns=columns,
            rows=rows,
            dataset_name=name,
            chart_png=decode_png_data_url(body.chart_png) if body.chart_png else None,
            details={
                "Asked": str(q.created_at)[:16],
                "Model": q.sql_model or "-",
                "Answered in": f"{q.latency_ms / 1000:.1f}s",
            },
        )
    )
    log_event("export", question_id=qid, format="pdf", rows=len(rows))
    return _download(pdf, "pdf", q.question)
