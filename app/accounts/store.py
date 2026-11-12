"""
Account storage (users table) and the session-signing secret.

    accounts = AccountStore(owner_engine, admin_emails={"me@example.com"}, secret_override="")
    user = accounts.create("a@b.com", "long password")       # raises AccountError
    user = accounts.authenticate("a@b.com", "long password")  # None if wrong
    accounts.get(user_id); accounts.secret()

The secret is generated once and stored in the database, so every serverless instance signs and
checks cookies with the same key without any manual setup (SESSION_SECRET overrides it).
"""

import re
import secrets
import threading
import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import IntegrityError

from app.accounts.passwords import DUMMY_HASH, hash_password, verify_password
from app.db.app_tables import app_secrets, users

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


class AccountError(ValueError):
    """Sign-up rejected; the message is safe to show. status_code is the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class User:
    id: str
    email: str


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


class AccountStore:
    def __init__(self, engine: Engine, admin_emails: set[str] | None = None, secret_override: str = ""):
        self.engine = engine
        self.admin_emails = {normalize_email(e) for e in (admin_emails or set()) if e.strip()}
        self._secret = secret_override or None
        self._lock = threading.Lock()

    def is_admin(self, email: str) -> bool:
        return normalize_email(email) in self.admin_emails

    # ---- users ---------------------------------------------------------------------------------
    def create(self, email: str, password: str) -> User:
        email = normalize_email(email)
        if not _EMAIL.match(email) or len(email) > 254:
            raise AccountError("enter a valid email address")
        if len(password) < MIN_PASSWORD:
            raise AccountError(f"use a password of at least {MIN_PASSWORD} characters")
        if len(password) > 200:
            raise AccountError("that password is too long")
        user = User(id=uuid.uuid4().hex[:12], email=email)
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(users).values(id=user.id, email=email, password_hash=hash_password(password)))
        except IntegrityError as e:
            raise AccountError("an account with this email already exists; sign in instead", 409) from e
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.email == normalize_email(email))).first()
        if row is None:
            verify_password(password, DUMMY_HASH)  # same work as a real check: don't reveal which emails exist
            return None
        return User(row.id, row.email) if verify_password(password, row.password_hash) else None

    def get(self, user_id: str) -> User | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users.c.id, users.c.email).where(users.c.id == user_id)).first()
        return User(row.id, row.email) if row else None

    # ---- session secret ------------------------------------------------------------------------
    def secret(self) -> str:
        """The cookie-signing key: SESSION_SECRET, else one generated and stored in the database."""
        with self._lock:
            if self._secret is None:
                self._secret = self._load_or_create_secret()
            return self._secret

    def _load_or_create_secret(self) -> str:
        query = select(app_secrets.c.value).where(app_secrets.c.name == "session")
        with self.engine.connect() as conn:
            value = conn.execute(query).scalar()
        if value:
            return value
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(app_secrets).values(name="session", value=secrets.token_urlsafe(48)))
        except IntegrityError:
            pass  # another instance created it first; use theirs
        with self.engine.connect() as conn:
            return conn.execute(query).scalar_one()
