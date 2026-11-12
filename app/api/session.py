"""
Session middleware: attaches `request.state.identity` to every /api request.

    valid user cookie    -> Identity(user_id, email, is_admin)
    valid guest cookie   -> Identity(guest_id)
    none / invalid       -> a new guest; the cookie is set on the response

Cookies are HttpOnly (no JavaScript access), SameSite=Lax (not sent on cross-site POSTs, which
blocks CSRF on the state-changing endpoints) and Secure over HTTPS.

    set_session_cookie(response, request, codec, identity)   used by sign-in / sign-out
"""

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool

from app.accounts import Identity, SessionCodec
from app.accounts.sessions import COOKIE_NAME, MAX_AGE_S


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def set_session_cookie(response: Response, request: Request, codec: SessionCodec, identity: Identity) -> None:
    response.set_cookie(
        COOKIE_NAME,
        codec.issue(identity),
        max_age=MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )


def install_session_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def session(request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        services = request.app.state.services
        # Database lookups run in the thread pool so they never block the event loop.
        codec = SessionCodec(await run_in_threadpool(services.accounts.secret))
        identity = None
        token = codec.read(request.cookies.get(COOKIE_NAME))
        if token and token[0] == "u":
            user = await run_in_threadpool(services.accounts.get, token[1])
            if user:
                identity = Identity(
                    user_id=user.id,
                    email=user.email,
                    name=user.name,
                    company=user.company,
                    is_admin=services.accounts.is_admin(user.email),
                )
        elif token and token[0] == "g":
            identity = Identity(guest_id=token[1])
        if identity is None:
            identity = Identity.new_guest()
        request.state.identity = identity
        response = await call_next(request)
        if identity.is_new and COOKIE_NAME not in response.headers.get("set-cookie", ""):
            set_session_cookie(response, request, codec, identity)
        return response
