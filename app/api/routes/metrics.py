"""
Metrics (the "Metrics" page):

    GET /api/metrics                     live usage metrics + the committed offline reports
                                         (evaluation, tests/coverage, load test). Aggregates only,
                                         no questions or emails, so it is public.
    GET /api/metrics/feedback            rated questions with SQL and notes (admins only)
    GET /api/metrics/eval-candidates     questions rated "not helpful", as eval-set JSONL lines
                                         to review and add to evals/questions.jsonl (admins only)

Admins are the emails in ADMIN_EMAILS.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.accounts import Identity
from app.api.container import Services
from app.api.dependencies import get_identity, get_services
from app.db.app_tables import questions
from app.telemetry.metrics import compute_live_metrics
from app.telemetry.reports import load_reports

router = APIRouter(tags=["metrics"])


def _require_admin(identity: Identity) -> None:
    if not identity.is_admin:
        raise HTTPException(403, "admins only (ADMIN_EMAILS)")


@router.get("/api/metrics")
def metrics(services: Services = Depends(get_services)) -> dict[str, Any]:
    return {"live": compute_live_metrics(services.owner_engine), **load_reports()}


def _rated(services: Services, rating: int | None, limit: int) -> list[Any]:
    q = questions.c
    query = select(
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
    ).where(q.feedback.is_not(None) if rating is None else q.feedback == rating)
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
