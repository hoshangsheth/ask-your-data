"""
Anthropic Claude adapter (SDK: `pip install anthropic`).

Config:
    LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=...         # https://console.anthropic.com

Mapping of the provider-neutral contract:
    system prompt   -> system block, marked for prompt caching (identical for every question)
    JSON schema     -> output_config.format = json_schema
    reasoning       -> output_config.effort (low / medium / high)
    refusals        -> server-side fallback model, then stop_reason "refusal" -> LLMError
"""

import json
from typing import Any

from app.llm.contracts import JSONResult, Reasoning
from app.llm.errors import LLMAuthError, LLMError, LLMNotConfigured, LLMRateLimited, LLMUnavailable


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str = "", timeout_s: float = 60.0):
        # Import here so the SDK is only required when this provider is selected.
        try:
            import anthropic
        except ImportError as e:
            raise LLMNotConfigured("install the Anthropic SDK: pip install anthropic") from e
        self._sdk = anthropic
        # Empty key -> the SDK resolves ANTHROPIC_API_KEY / an `ant auth login` profile itself.
        self.client = anthropic.Anthropic(api_key=api_key or None, timeout=timeout_s)

    def complete_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], schema_name: str, reasoning: Reasoning
    ) -> JSONResult:
        resp = self._send(model=model, system=system, user=user, schema=schema, reasoning=reasoning)
        if resp.stop_reason == "refusal":
            raise LLMError("the model declined to answer this question")
        if resp.stop_reason == "max_tokens":
            raise LLMError("the model response was cut off")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError("the model returned invalid JSON") from e
        return JSONResult(
            data=data, model=model, input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens
        )

    def _send(self, *, model: str, system: str, user: str, schema: dict[str, Any], reasoning: Reasoning):
        """Call the API and translate SDK errors into provider-neutral ones."""
        sdk = self._sdk
        try:
            return self.client.beta.messages.create(
                model=model,
                max_tokens=16000,
                # If the primary model declines, the API retries the request on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": reasoning, "format": {"type": "json_schema", "schema": schema}},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except TypeError as e:  # raised before sending when no credentials resolve
            if "authentication" in str(e).lower():
                raise LLMNotConfigured("set ANTHROPIC_API_KEY") from e
            raise
        except sdk.AuthenticationError as e:
            raise LLMAuthError("Anthropic rejected the API key") from e
        except sdk.NotFoundError as e:
            raise LLMNotConfigured(f"Claude model '{model}' not found") from e
        except sdk.RateLimitError as e:
            raise LLMRateLimited("Anthropic rate limit reached") from e
        except (sdk.APIStatusError, sdk.APIConnectionError) as e:
            raise LLMUnavailable(f"Anthropic request failed: {type(e).__name__}") from e
