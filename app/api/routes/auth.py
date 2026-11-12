"""
Accounts: sign up, sign in, sign out, and who am I.

    POST /api/auth/signup   {email, password, name, company}  -> 201 + session cookie
    POST /api/auth/login    {email, password}  -> 200 + session cookie, 401 if wrong
    POST /api/auth/logout                      -> a fresh guest session
    GET  /api/auth/me                          -> {signed_in, email, name, company, is_admin}

Questions asked as a guest move to the account on sign-in, so the conversation carries on.
Sign-in and sign-up are rate limited per IP (LOGIN_ATTEMPTS_PER_MINUTE).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.accounts import AccountError, Identity, SessionCodec
from app.accounts.store import User
from app.api.container import Services
from app.api.dependencies import client_ip, get_identity, get_services
from app.api.schemas import Credentials, MeResponse, SignupRequest
from app.api.session import set_session_cookie
from app.core.logging import log_event

router = APIRouter(tags=["auth"])


def _limit(request: Request, services: Services) -> None:
    if not services.login_limiter.allow(client_ip(request)):
        raise HTTPException(429, "too many attempts; wait a minute and try again")


def _signed_in(request: Request, response: Response, services: Services, previous: Identity, user: User) -> MeResponse:
    admin = services.accounts.is_admin(user.email)
    identity = Identity(user_id=user.id, email=user.email, name=user.name, company=user.company, is_admin=admin)
    set_session_cookie(response, request, SessionCodec(services.accounts.secret()), identity)
    if previous.guest_id:
        services.log.adopt_guest(previous.guest_id, user.id)
    return MeResponse(signed_in=True, email=user.email, name=user.name, company=user.company, is_admin=admin)


@router.post("/api/auth/signup", response_model=MeResponse, status_code=201)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> MeResponse:
    _limit(request, services)
    try:
        user = await run_in_threadpool(services.accounts.create, body.email, body.password, body.name, body.company)
    except AccountError as e:
        raise HTTPException(e.status_code, str(e)) from e
    log_event("signup", user_id=user.id)
    return await run_in_threadpool(_signed_in, request, response, services, identity, user)


@router.post("/api/auth/login", response_model=MeResponse)
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    identity: Identity = Depends(get_identity),
) -> MeResponse:
    _limit(request, services)
    user = await run_in_threadpool(services.accounts.authenticate, body.email, body.password)
    if user is None:
        raise HTTPException(401, "wrong email or password")
    return await run_in_threadpool(_signed_in, request, response, services, identity, user)


@router.post("/api/auth/logout", response_model=MeResponse)
def logout(request: Request, response: Response, services: Services = Depends(get_services)) -> MeResponse:
    set_session_cookie(response, request, SessionCodec(services.accounts.secret()), Identity.new_guest())
    return MeResponse(signed_in=False)


@router.get("/api/auth/me", response_model=MeResponse)
def me(identity: Identity = Depends(get_identity)) -> MeResponse:
    return MeResponse(
        signed_in=identity.signed_in,
        email=identity.email,
        name=identity.name,
        company=identity.company,
        is_admin=identity.is_admin,
    )
