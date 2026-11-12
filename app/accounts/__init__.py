"""
Accounts and sessions: email + password sign-in, with a signed session cookie.

    passwords.py   scrypt password hashing (standard library, no extra dependency)
    sessions.py    signed, expiring session tokens: a user, or an anonymous guest browser
    store.py       users table + the shared session-signing secret

Everyone gets a session: anonymous visitors are "guests" (they can ask about the demo store);
signed-in users can also upload data, which only they can see.
"""

from app.accounts.sessions import Identity, SessionCodec
from app.accounts.store import AccountError, AccountStore

__all__ = ["AccountError", "AccountStore", "Identity", "SessionCodec"]
