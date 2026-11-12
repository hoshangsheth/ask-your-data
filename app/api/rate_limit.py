"""
In-memory sliding-window rate limiter.

Protects the paid endpoint (POST /api/ask) from runaway API bills. State lives in this process
only; for several server instances, replace it with a shared store such as Redis.

Usage:
    limiter = RateLimiter(per_minute=20)
    if not limiter.allow(client_ip): ...   # reject with HTTP 429
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_minute: int, window_s: float = 60.0):
        self.per_minute = per_minute  # 0 or less disables limiting
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)  # client key -> request timestamps
        self._lock = threading.Lock()  # FastAPI runs sync endpoints in a thread pool

    def allow(self, key: str) -> bool:
        """Record a request for `key`; return False if it exceeds the limit."""
        if self.per_minute <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_s:  # drop requests outside the window
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(now)
            return True
