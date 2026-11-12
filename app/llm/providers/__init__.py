"""
Provider registry: LLM_PROVIDER value -> (module, class). Modules are imported lazily, so only
the SDK for the selected provider has to be installed.

To add a provider:
    1. create app/llm/providers/<name>.py with a class implementing app.llm.contracts.LLMProvider
    2. register it below
    3. add its default models to DEFAULT_MODELS in app/llm/factory.py (optional)
    4. add its API key field to app/core/config.py and the mapping in factory.build_provider
"""

PROVIDERS: dict[str, tuple[str, str]] = {
    "gemini": ("app.llm.providers.gemini", "GeminiProvider"),
    "anthropic": ("app.llm.providers.anthropic", "AnthropicProvider"),
    "openai": ("app.llm.providers.openai", "OpenAIProvider"),
}
