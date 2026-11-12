"""
GET /api/health - liveness check plus which database and AI models are configured, and whether
an API key is present (`llm_ready`). Does not call the AI provider, so it works without a key
(used by the Docker HEALTHCHECK and by the UI to show setup steps).
"""

from fastapi import APIRouter, Depends

from app.api.container import Services
from app.api.dependencies import get_services
from app.api.schemas import HealthResponse
from app.llm import has_credentials, resolve_models

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health(services: Services = Depends(get_services)) -> HealthResponse:
    settings = services.settings
    sql_model, summary_model = resolve_models(settings)
    return HealthResponse(
        status="ok",
        database=services.readonly_engine.dialect.name,
        llm_provider=settings.llm_provider.strip().lower(),
        sql_model=sql_model,
        summary_model=summary_model,
        llm_ready=has_credentials(settings),
        storage=services.storage_info,
    )
