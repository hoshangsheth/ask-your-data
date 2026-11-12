"""
POST /api/ask - answer a natural-language question about a dataset.

Request:  {"question": "Top 5 products by revenue in 2025", "dataset_id": "demo",
           "conversation_id": "<32 hex>" (optional: continue a conversation)}
Response: AskResponse (app/api/schemas.py): answer, SQL, rows, chart, agent trace, token usage,
          plus question_id (feedback / export), conversation_id, turn and estimated cost.

Follow-ups: when conversation_id is given, the previous answered turns of that conversation (by
the same user or guest, on the same dataset) are passed to the model, so "same for 2024" or
"break that down by city" work. Every question is recorded in the question log for metrics.

Errors:
    401/429      from require_access (API key / rate limit)
    404          unknown dataset_id, or another user's dataset
    422          question too short or too long
    429/502/503  AI provider unusable (rate limit / outage / no or bad key), from LLMServiceError
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.accounts import Identity
from app.api.container import Services
from app.api.dependencies import check_dataset_access, get_identity, get_services, require_access
from app.api.schemas import AskRequest, AskResponse
from app.core.logging import log_event
from app.datasets.store import DatasetNotFound
from app.llm import LLMServiceError

router = APIRouter(tags=["ask"])


@router.post("/api/ask", response_model=AskResponse, dependencies=[Depends(require_access)])
def ask(
    body: AskRequest, services: Services = Depends(get_services), identity: Identity = Depends(get_identity)
) -> dict:
    provider = services.settings.llm_provider
    check_dataset_access(services, body.dataset_id, identity)

    conversation_id = body.conversation_id or uuid.uuid4().hex
    history: list[dict[str, str]] = []
    turn = 1
    if body.conversation_id:
        try:
            history = services.log.history(conversation_id, identity, body.dataset_id)
            turn = services.log.turns(conversation_id, identity) + 1
        except Exception as e:  # the log is a nice-to-have: answer without context rather than fail
            log_event("history_failed", error=type(e).__name__)

    try:
        agent = services.agent(body.dataset_id)
        result = agent.ask(body.question.strip(), history=history)
        models = services.models()
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found; it may have been deleted") from e
    except LLMServiceError as e:
        raise HTTPException(e.status_code, f"AI provider ({provider}): {e}") from e

    question_id, cost = None, None
    try:
        question_id, cost = services.log.record(
            result,
            identity=identity,
            conversation_id=conversation_id,
            turn=turn,
            dataset_id=body.dataset_id,
            dataset_kind="demo" if body.dataset_id == "demo" else "upload",
            models=models,
        )
    except Exception as e:  # never lose an answer because the log write failed
        log_event("question_log_failed", error=type(e).__name__)

    # One JSON log line per question as well (visible in the hosting provider's logs).
    log_event(
        "ask",
        provider=provider,
        dataset_id=body.dataset_id,
        status=result["status"],
        attempts=result["attempts"],
        rows=len(result["rows"]),
        latency_ms=result["latency_ms"],
        turn=turn,
        cost_usd=cost,
        **result["usage"],
    )
    return {
        **result,
        "dataset_id": body.dataset_id,
        "currency": agent.source.currency,
        "question_id": question_id,
        "conversation_id": conversation_id,
        "turn": turn,
        "cost_usd": cost,
    }
