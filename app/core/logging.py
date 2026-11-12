"""
Structured logging: one JSON object per line, easy to grep or ship to a log service.

Usage:
    from app.core.logging import configure_logging, log_event
    configure_logging()                                  # once, at startup
    log_event("ask", status="ok", latency_ms=812)        # -> {"event": "ask", "status": "ok", ...}
"""

import json
import logging
from typing import Any

LOGGER_NAME = "ask_your_data"
_log = logging.getLogger(LOGGER_NAME)


def configure_logging(level: int = logging.INFO) -> None:
    """Send this app's log lines to stderr as bare messages (the message itself is JSON)."""
    logging.basicConfig(level=level, format="%(message)s")


def log_event(event: str, **fields: Any) -> None:
    """Log one event with arbitrary fields as a single JSON line."""
    _log.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))
