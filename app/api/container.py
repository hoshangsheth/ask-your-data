"""
Services container: the long-lived objects one app instance needs, created once and shared by
all requests (stored on `app.state.services`).

The agent is built lazily on the first question, so the dashboard works even when no LLM API
key is configured. Tests inject a fake LLM through `Services(settings, llm=FakeLLM(...))`.
"""

import threading

from app.agent import SQLAgent
from app.api.rate_limit import RateLimiter
from app.core.config import Settings
from app.db.engine import make_engines
from app.llm import LLM, build_llm


class Services:
    def __init__(self, settings: Settings, llm: LLM | None = None):
        self.settings = settings
        self.owner_engine, self.readonly_engine = make_engines(settings.database_url, settings.readonly_database_url)
        self.limiter = RateLimiter(settings.rate_limit_per_minute)
        self._llm = llm  # injected (tests) or built from settings on first use
        self._agent: SQLAgent | None = None
        self._lock = threading.Lock()

    def agent(self) -> SQLAgent:
        """Return the agent, building it (and the LLM) on first call. Thread-safe."""
        with self._lock:
            if self._agent is None:
                llm = self._llm or build_llm(self.settings)  # may raise LLMServiceError (e.g. no key)
                s = self.settings
                self._agent = SQLAgent(
                    llm,
                    self.readonly_engine,
                    max_rows=s.max_rows,
                    max_attempts=s.max_attempts,
                    timeout_ms=s.query_timeout_ms,
                )
            return self._agent

    def dispose(self) -> None:
        """Close database connection pools (called on shutdown)."""
        self.owner_engine.dispose()
        self.readonly_engine.dispose()
