"""
POST /api/ask - answer a natural-language question about the data.

Request:  {"question": "Top 5 products by revenue in 2025"}
Response: AskResponse (app/api/schemas.py): answer, SQL, rows, chart, agent trace, token usage.

Errors:
    401/429  from require_access (API key / rate limit)
    422      question too short or too long
    429/502/503  AI provider unusable (rate limit / outage / no or bad key), from LLMServiceError
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.container import Services
from app.api.dependencies import get_services, require_access
from app.api.schemas import AskRequest, AskResponse
from app.core.logging import log_event
from app.llm import LLMServiceError

router = APIRouter(tags=["ask"])


@router.post("/api/ask", response_model=AskResponse, dependencies=[Depends(require_access)])
def ask(body: AskRequest, services: Services = Depends(get_services)) -> dict:
    provider = services.settings.llm_provider
    try:
        result = services.agent().ask(body.question.strip())
    except LLMServiceError as e:
        raise HTTPException(e.status_code, f"AI provider ({provider}): {e}") from e

    # One JSON log line per question: enough to track quality, latency and cost over time.
    log_event(
        "ask",
        provider=provider,
        question=result["question"],
        status=result["status"],
        attempts=result["attempts"],
        rows=len(result["rows"]),
        latency_ms=result["latency_ms"],
        **result["usage"],
    )
    return result
