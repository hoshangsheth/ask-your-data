"""
POST /api/ask - answer a natural-language question about a dataset.

Request:  {"question": "Top 5 products by revenue in 2025", "dataset_id": "demo"}
Response: AskResponse (app/api/schemas.py): answer, SQL, rows, chart, agent trace, token usage.

Errors:
    401/429      from require_access (API key / rate limit)
    404          unknown dataset_id
    422          question too short or too long
    429/502/503  AI provider unusable (rate limit / outage / no or bad key), from LLMServiceError
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.container import Services
from app.api.dependencies import get_services, require_access
from app.api.schemas import AskRequest, AskResponse
from app.core.logging import log_event
from app.datasets.store import DatasetNotFound
from app.llm import LLMServiceError

router = APIRouter(tags=["ask"])


@router.post("/api/ask", response_model=AskResponse, dependencies=[Depends(require_access)])
def ask(body: AskRequest, services: Services = Depends(get_services)) -> dict:
    provider = services.settings.llm_provider
    try:
        agent = services.agent(body.dataset_id)
        result = agent.ask(body.question.strip())
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found; it may have been deleted") from e
    except LLMServiceError as e:
        raise HTTPException(e.status_code, f"AI provider ({provider}): {e}") from e

    # One JSON log line per question: enough to track quality, latency and cost over time.
    log_event(
        "ask",
        provider=provider,
        dataset_id=body.dataset_id,
        question=result["question"],
        status=result["status"],
        attempts=result["attempts"],
        rows=len(result["rows"]),
        latency_ms=result["latency_ms"],
        **result["usage"],
    )
    return {**result, "dataset_id": body.dataset_id, "currency": agent.source.currency}
