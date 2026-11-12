"""
Provider-neutral errors. Adapters translate their SDK's exceptions into these, so the rest of the
app never depends on a vendor's exception classes.

Two families:
    LLMError          this one question failed (refusal, cut-off, invalid JSON).
                      The agent reports it as a failed answer; the HTTP request still succeeds.
    LLMServiceError   the provider is unusable right now (no key, bad key, rate limit, outage).
                      The API returns `status_code` to the client.
"""


class LLMError(Exception):
    """The model call failed or returned something unusable for this question."""


class LLMServiceError(Exception):
    """Base for provider-level failures. Subclasses set the HTTP status to return."""

    status_code = 502


class LLMNotConfigured(LLMServiceError):
    """Missing API key, missing SDK package, unknown provider or model."""

    status_code = 503


class LLMAuthError(LLMServiceError):
    """The provider rejected the API key."""

    status_code = 503


class LLMRateLimited(LLMServiceError):
    """Rate limit or quota reached."""

    status_code = 429


class LLMUnavailable(LLMServiceError):
    """Network error or provider-side failure."""

    status_code = 502
