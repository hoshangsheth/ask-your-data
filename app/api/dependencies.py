"""
FastAPI dependencies shared by the routes.

    get_services       the Services container for this app instance
    get_identity       who is calling: a signed-in user or an anonymous guest (set by the session
                       middleware in app/api/session.py)
    require_user       401 unless signed in (uploads, private datasets)
    require_access     optional API-key check + per-IP request limit (uploads, deletes)
    require_api_key    the API-key check alone (questions: limited by app/api/quota.py instead)
    dataset_for(...)   resolve a dataset id the caller may use (404 for other users' datasets)
    client_ip          the caller's IP (Vercel's forwarded header when deployed)
"""

from fastapi import Depends, Header, HTTPException, Request

from app.accounts import Identity
from app.api.container import Services
from app.core.config import ON_VERCEL
from app.datasets.profile import DatasetMeta
from app.datasets.store import DatasetNotFound
from app.sources import DEMO_ID


def get_services(request: Request) -> Services:
    """Services created in the app factory and stored on app.state."""
    return request.app.state.services


def get_identity(request: Request) -> Identity:
    return getattr(request.state, "identity", None) or Identity.new_guest()


def require_user(identity: Identity = Depends(get_identity)) -> Identity:
    if not identity.signed_in:
        raise HTTPException(401, "sign in to use your own data")
    return identity


def client_ip(request: Request) -> str:
    if ON_VERCEL:  # Vercel's edge sets these; a client can't spoof the first hop it adds
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Reject the request with 401 when an API key is configured and missing or wrong."""
    key = get_services(request).settings.app_api_key
    if key and x_api_key != key:
        raise HTTPException(401, "missing or invalid X-API-Key")


def require_access(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Reject the request with 401 (bad/missing key) or 429 (too many requests from this IP)."""
    require_api_key(request, x_api_key)
    services = get_services(request)
    if not services.limiter.allow(client_ip(request)):
        raise HTTPException(429, {"code": "rate_uploads", "message": "too many requests; wait a minute and try again"})


def owned_upload(services: Services, dataset_id: str, identity: Identity) -> DatasetMeta:
    """An uploaded dataset that belongs to the caller; DatasetNotFound otherwise (also for others' data)."""
    meta = services.store.get(dataset_id)
    if not identity.signed_in or meta.owner_id != identity.user_id:
        raise DatasetNotFound(dataset_id)
    return meta


def check_dataset_access(services: Services, dataset_id: str, identity: Identity) -> None:
    """404 unless the dataset is the demo store or the caller's own upload."""
    if dataset_id == DEMO_ID:
        return
    try:
        owned_upload(services, dataset_id, identity)
    except DatasetNotFound as e:
        raise HTTPException(404, "dataset not found; it may have been deleted") from e
