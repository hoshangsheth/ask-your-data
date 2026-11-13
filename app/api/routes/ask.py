"""
POST /api/ask - answer a natural-language question about a dataset.

Request:  {"question": "Top 5 products by revenue in 2025", "dataset_id": "demo",
           "conversation_id": "<32 hex>" (optional: continue a conversation)}
Response: AskResponse (app/api/schemas.py): answer, SQL, rows, chart, agent trace, token usage,
          plus question_id (feedback / export), conversation_id, turn and estimated cost.

Follow-ups: when conversation_id is given, the previous answered turns of that conversation (by
the same user or guest, on the same dataset) are passed to the model, so "same for 2024" or
"break that down by city" work. Every question is recorded in the question log for metrics.

Limits (app/api/quota.py): 10 questions a minute, 35 a day per account, 5 a day per guest and
250 a day for the whole site by default. A question is counted once it reaches the model; if the
provider is unusable it is given back.

Errors (detail = {"code", "message", ...} so the UI can explain each case):
    401          missing or wrong X-API-Key (when APP_API_KEY is set)
    404          unknown dataset_id, or another user's dataset
    422          question too short or too long
    429          rate_minute | daily_user | daily_guest | daily_site (with retry_after seconds)
    429/502/503  ai_busy | ai_down | ai_not_configured: the AI provider is unusable right now
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from app.accounts import Identity
from app.api.container import Services
from app.api.dependencies import check_dataset_access, client_ip, get_identity, get_services, require_api_key
from app.api.quota import QuotaExceeded
from app.api.schemas import AskRequest, AskResponse
from app.core.logging import log_event
from app.datasets.store import DatasetNotFound
from app.llm import LLMRateLimited, LLMServiceError, LLMUnavailable

router = APIRouter(tags=["ask"])


def _ai_error_code(e: LLMServiceError) -> str:
    if isinstance(e, LLMRateLimited):
        return "ai_busy"  # provider rate limit, quota or spending cap
    if isinstance(e, LLMUnavailable):
        return "ai_down"
    return "ai_not_configured"


@router.post("/api/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
def ask(
    body: AskRequest,
    request: Request,
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> dict:
    provider = services.settings.llm_provider
    check_dataset_access(services, body.dataset_id, identity)

    ticket = None
    if not identity.is_admin:  # the owner can test freely
        actor = f"u:{identity.user_id}" if identity.signed_in else f"g:{client_ip(request)}"
        try:
            ticket = services.quota.reserve(actor, identity.signed_in)
        except QuotaExceeded as e:
            log_event("quota_exceeded", code=e.code)
            raise HTTPException(
                429,
                {"code": e.code, "message": str(e), "retry_after": e.retry_after},
                headers={"Retry-After": str(e.retry_after)},
            ) from e

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
        if ticket:
            try:
                services.quota.refund(ticket)  # nothing was answered: don't count it
            except Exception as refund_error:
                log_event("quota_refund_failed", error=type(refund_error).__name__)
        log_event("ai_provider_error", provider=provider, code=_ai_error_code(e), error=type(e).__name__)
        raise HTTPException(
            e.status_code, {"code": _ai_error_code(e), "message": f"AI provider ({provider}): {e}"}
        ) from e

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
        "questions_left_today": ticket.left_today if ticket else None,
    }
