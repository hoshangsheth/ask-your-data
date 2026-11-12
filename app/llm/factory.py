"""
Builds the configured provider. This is the only module that maps provider names to classes,
API keys and default models.

Switching provider (in .env, no code change):
    LLM_PROVIDER=gemini      + GEMINI_API_KEY
    LLM_PROVIDER=anthropic   + ANTHROPIC_API_KEY
    LLM_PROVIDER=openai      + OPENAI_API_KEY + LLM_SQL_MODEL (+ LLM_SUMMARY_MODEL)
"""

import importlib
import os

from app.core.config import Settings
from app.llm.errors import LLMNotConfigured
from app.llm.providers import PROVIDERS
from app.llm.text_to_sql import TextToSQL

# (sql_model, summary_model) used when LLM_SQL_MODEL / LLM_SUMMARY_MODEL are empty.
# OpenAI has no default on purpose: set the model names your account can use.
DEFAULT_MODELS: dict[str, tuple[str, str]] = {
    "gemini": ("gemini-3.8-flash", "gemini-3.5-flash-lite"),
    "anthropic": ("claude-opus-5-5", "claude-opus-5-5"),
}


# Where each provider's key can come from: the settings field, then environment variables.
_KEY_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "gemini": ("gemini_api_key", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    "anthropic": ("anthropic_api_key", ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")),
    "openai": ("openai_api_key", ("OPENAI_API_KEY",)),
}


def has_credentials(settings: Settings) -> bool:
    """True if an API key for the selected provider is configured. Does not call the provider."""
    field, env_vars = _KEY_SOURCES.get(settings.llm_provider.strip().lower(), ("", ()))
    return bool((field and getattr(settings, field, "")) or any(os.environ.get(v) for v in env_vars))


def _provider_name(settings: Settings) -> str:
    name = settings.llm_provider.strip().lower()
    if name not in PROVIDERS:
        raise LLMNotConfigured(f"unknown LLM_PROVIDER '{name}'. Choose one of: {', '.join(PROVIDERS)}")
    return name


def resolve_models(settings: Settings) -> tuple[str, str]:
    """(sql_model, summary_model) after applying overrides and provider defaults. May be empty."""
    default_sql, default_summary = DEFAULT_MODELS.get(settings.llm_provider.strip().lower(), ("", ""))
    sql_model = settings.llm_sql_model or default_sql
    summary_model = settings.llm_summary_model or default_summary or sql_model
    return sql_model, summary_model


def build_provider(settings: Settings):
    """Instantiate the adapter for LLM_PROVIDER. SDKs are imported lazily (only the one in use)."""
    name = _provider_name(settings)
    module_path, class_name = PROVIDERS[name]
    provider_cls = getattr(importlib.import_module(module_path), class_name)
    api_key = {
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }.get(name, "")
    return provider_cls(api_key=api_key, timeout_s=settings.llm_timeout_s)


def build_llm(settings: Settings) -> TextToSQL:
    """The object the agent uses: shared prompts + configured provider + models + reasoning."""
    name = _provider_name(settings)
    sql_model, summary_model = resolve_models(settings)
    if not sql_model:
        raise LLMNotConfigured(f"set LLM_SQL_MODEL (and optionally LLM_SUMMARY_MODEL) for provider '{name}'")
    return TextToSQL(
        build_provider(settings),
        sql_model=sql_model,
        summary_model=summary_model,
        sql_reasoning=settings.llm_sql_reasoning,
        summary_reasoning=settings.llm_summary_reasoning,
    )
