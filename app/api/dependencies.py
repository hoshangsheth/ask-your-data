"""
FastAPI dependencies shared by the routes.

    get_services     the Services container for this app instance
    require_access   optional API-key check + per-client rate limit (used on paid endpoints)
"""

from fastapi import Header, HTTPException, Request

from app.api.container import Services


def get_services(request: Request) -> Services:
    """Services created in the app factory and stored on app.state."""
    return request.app.state.services


def require_access(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Reject the request with 401 (bad/missing key) or 429 (too many requests)."""
    services = get_services(request)
    settings = services.settings
    if settings.app_api_key and x_api_key != settings.app_api_key:
        raise HTTPException(401, "missing or invalid X-API-Key")
    client = request.client.host if request.client else "unknown"
    if not services.limiter.allow(client):
        raise HTTPException(429, f"rate limit: {settings.rate_limit_per_minute} questions per minute")
