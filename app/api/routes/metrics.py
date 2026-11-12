"""
Metrics for the app's owner (the admin-only "Metrics" page). Not shown to users.

    GET /api/metrics                     live usage metrics + the committed offline reports
                                         (evaluation, tests/coverage, load test)
    GET /api/metrics/feedback            rated questions with SQL, notes and who rated them
    GET /api/metrics/feedback.xlsx       the same as an Excel workbook (name, company, email per rating)
    GET /api/metrics/eval-candidates     questions rated "not helpful", as eval-set JSONL lines
                                         to review and add to evals/questions.jsonl

All of these need a signed-in admin: an email listed in ADMIN_EMAILS. Without the UI, the same live
numbers come from `python -m scripts.metrics_report` against the database.
"""

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.accounts import Identity
from app.api.container import Services
from app.api.dependencies import get_identity, get_services
from app.db.app_tables import questions, users
from app.telemetry.feedback import feedback_rows, feedback_xlsx
from app.telemetry.metrics import compute_live_metrics
from app.telemetry.reports import load_reports

router = APIRouter(tags=["metrics"])


def _require_admin(identity: Identity) -> None:
    if not identity.is_admin:
        raise HTTPException(403, "admins only (ADMIN_EMAILS)")


@router.get("/api/metrics")
def metrics(services: Services = Depends(get_services), identity: Identity = Depends(get_identity)) -> dict[str, Any]:
    _require_admin(identity)
    return {"live": compute_live_metrics(services.owner_engine), **load_reports()}


def _rated(services: Services, rating: int | None, limit: int) -> list[Any]:
    q, u = questions.c, users.c
    query = (
        select(
            q.id,
            q.created_at,
            q.dataset_kind,
            q.question,
            q.standalone_question,
            q.sql,
            q.answer,
            q.status,
            q.feedback,
            q.feedback_note,
            q.sql_model,
            u.name,
            u.company,
            u.email,
        )
        .select_from(questions.outerjoin(users, q.user_id == u.id))  # guests have no user row
        .where(q.feedback.is_not(None) if rating is None else q.feedback == rating)
    )
    with services.owner_engine.connect() as conn:
        return conn.execute(query.order_by(q.created_at.desc()).limit(limit)).all()


@router.get("/api/metrics/feedback")
def feedback_list(
    rating: int | None = Query(None, ge=-1, le=1),
    limit: int = Query(100, ge=1, le=1000),
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> list[dict[str, Any]]:
    _require_admin(identity)
    return [{**r._asdict(), "created_at": str(r.created_at)} for r in _rated(services, rating, limit)]


@router.get("/api/metrics/feedback.xlsx")
def feedback_excel(services: Services = Depends(get_services), identity: Identity = Depends(get_identity)) -> Response:
    """Every rated answer with who gave it (name, company, email), as an Excel workbook."""
    _require_admin(identity)
    data = feedback_xlsx(feedback_rows(services.owner_engine))
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="ask-your-data-feedback-{stamp}.xlsx"'},
    )


@router.get("/api/metrics/eval-candidates")
def eval_candidates(services: Services = Depends(get_services), identity: Identity = Depends(get_identity)) -> Response:
    _require_admin(identity)
    lines = [
        json.dumps(
            {
                "id": f"feedback_{r.id[:8]}",
                "question": r.standalone_question or r.question,
                "sql": "-- TODO: write the correct reference SQL",
                "model_sql": r.sql,
                "note": r.feedback_note,
            },
            ensure_ascii=False,
        )
        for r in _rated(services, -1, 1000)
        if r.dataset_kind == "demo"  # the eval set runs on the demo store
    ]
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="application/x-ndjson")
