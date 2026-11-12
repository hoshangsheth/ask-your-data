"""
Password hashing with scrypt (memory-hard; hashlib, no extra dependency).

    stored = hash_password("correct horse")      # "scrypt$16384$8$1$<salt>$<hash>"
    verify_password("correct horse", stored)     # True

Parameters are stored with each hash, so they can be raised later without breaking old hashes.
"""

import base64
import hashlib
import hmac
import os

_N, _R, _P = 2**14, 8, 1  # ~16 MB memory per hash; ~50 ms on a server CPU
_LEN = 32


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=_LEN, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(_scrypt(password, salt, _N, _R, _P))}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, _unb64(digest))  # constant time


# Used to spend the same time on unknown emails as on wrong passwords (no account enumeration).
DUMMY_HASH = hash_password("not-a-real-password")
