"""
Session tokens kept in an HttpOnly cookie.

A token is "<kind>.<id>.<expires>.<signature>" where kind is "u" (signed-in user) or "g" (guest),
signed with HMAC-SHA256. Nothing secret is inside; the signature only proves we issued it.

    codec = SessionCodec(secret)
    token = codec.issue(Identity(user_id="3f9a1c2b7d10", email="a@b.com"))
    identity = codec.read(token)          # None if missing, tampered with or expired
"""

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field

COOKIE_NAME = "ayd_session"
MAX_AGE_S = 30 * 24 * 3600  # 30 days


@dataclass(frozen=True)
class Identity:
    """Who is making a request. Exactly one of user_id / guest_id is set."""

    user_id: str | None = None
    guest_id: str | None = None
    email: str = ""
    name: str = ""
    company: str = ""
    is_admin: bool = False
    is_new: bool = field(default=False, compare=False)  # a guest created on this request (cookie to set)

    @property
    def signed_in(self) -> bool:
        return self.user_id is not None

    @staticmethod
    def new_guest() -> "Identity":
        return Identity(guest_id=uuid.uuid4().hex, is_new=True)


class SessionCodec:
    def __init__(self, secret: str):
        self._key = secret.encode()

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self._key, payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    def issue(self, identity: Identity, now: float | None = None) -> str:
        kind, ident = ("u", identity.user_id) if identity.user_id else ("g", identity.guest_id)
        payload = f"{kind}.{ident}.{int((now or time.time()) + MAX_AGE_S)}"
        return f"{payload}.{self._sign(payload)}"

    def read(self, token: str | None, now: float | None = None) -> tuple[str, str] | None:
        """Return (kind, id) for a valid token, else None."""
        if not token or token.count(".") != 3:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None
        kind, ident, expires = payload.split(".")
        if kind not in ("u", "g") or not expires.isdigit() or int(expires) < (now or time.time()):
            return None
        return kind, ident
