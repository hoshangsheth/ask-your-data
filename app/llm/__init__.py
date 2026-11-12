"""
Provider-agnostic LLM layer. The provider is chosen by configuration (LLM_PROVIDER), never in code.

    contracts.py     the one method every provider implements: complete_json()
    errors.py        provider-neutral error types (the API maps them to HTTP codes)
    prompts.py       system prompts and JSON schemas, written once for all providers
    indian_units.py  lakh/crore formatting of money values given to the model
    text_to_sql.py   the two calls the agent makes: generate_sql() and summarize()
    factory.py       builds the configured provider and default models
    providers/       one adapter per vendor SDK (gemini.py, anthropic.py, openai.py)

Usage:
    from app.llm import build_llm
    llm = build_llm(settings)                 # TextToSQL bound to the configured provider
    draft = llm.generate_sql(question=..., schema=..., dialect="sqlite")
"""

from app.llm.contracts import JSONResult, LLMProvider, Reasoning
from app.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMNotConfigured,
    LLMRateLimited,
    LLMServiceError,
    LLMUnavailable,
)
from app.llm.factory import DEFAULT_MODELS, build_llm, build_provider, has_credentials, resolve_models
from app.llm.text_to_sql import LLM, SQLDraft, Summary, TextToSQL

__all__ = [
    "JSONResult",
    "LLMProvider",
    "Reasoning",
    "LLMAuthError",
    "LLMError",
    "LLMNotConfigured",
    "LLMRateLimited",
    "LLMServiceError",
    "LLMUnavailable",
    "DEFAULT_MODELS",
    "build_llm",
    "build_provider",
    "has_credentials",
    "resolve_models",
    "LLM",
    "SQLDraft",
    "Summary",
    "TextToSQL",
]
