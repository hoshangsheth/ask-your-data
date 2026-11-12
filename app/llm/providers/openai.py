"""
OpenAI adapter using the Responses API (SDK: `pip install openai`).

Config:
    LLM_PROVIDER=openai
    OPENAI_API_KEY=...            # https://platform.openai.com
    LLM_SQL_MODEL=...             # required: no default model is assumed
    LLM_SUMMARY_MODEL=...         # optional: defaults to LLM_SQL_MODEL

Mapping of the provider-neutral contract:
    system prompt   -> instructions
    JSON schema     -> text.format = json_schema (strict)
    reasoning       -> reasoning.effort (low / medium / high)
"""

import json
from typing import Any

from app.llm.contracts import JSONResult, Reasoning
from app.llm.errors import LLMAuthError, LLMError, LLMNotConfigured, LLMRateLimited, LLMUnavailable


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str = "", timeout_s: float = 60.0):
        # Import here so the SDK is only required when this provider is selected.
        try:
            import openai
        except ImportError as e:
            raise LLMNotConfigured("install the OpenAI SDK: pip install openai") from e
        self._sdk = openai
        try:
            # Empty key -> the SDK reads OPENAI_API_KEY from the environment.
            self.client = openai.OpenAI(api_key=api_key or None, timeout=timeout_s)
        except openai.OpenAIError as e:
            raise LLMNotConfigured("set OPENAI_API_KEY") from e

    def complete_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], schema_name: str, reasoning: Reasoning
    ) -> JSONResult:
        resp = self._send(
            model=model, system=system, user=user, schema=schema, schema_name=schema_name, reasoning=reasoning
        )
        self._check_complete(resp)
        try:
            data = json.loads(resp.output_text or "")
        except json.JSONDecodeError as e:
            raise LLMError("the model returned invalid JSON") from e
        u = resp.usage
        return JSONResult(
            data=data, model=model, input_tokens=u.input_tokens if u else 0, output_tokens=u.output_tokens if u else 0
        )

    def _send(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], schema_name: str, reasoning: Reasoning
    ):
        """Call the API and translate SDK errors into provider-neutral ones."""
        sdk = self._sdk
        try:
            return self.client.responses.create(
                model=model,
                instructions=system,
                input=user,
                reasoning={"effort": reasoning},
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
                max_output_tokens=16000,
            )
        except sdk.AuthenticationError as e:
            raise LLMAuthError("OpenAI rejected the API key") from e
        except sdk.NotFoundError as e:
            raise LLMNotConfigured(f"OpenAI model '{model}' not found") from e
        except sdk.RateLimitError as e:
            raise LLMRateLimited("OpenAI rate limit or quota reached") from e
        except (sdk.APIStatusError, sdk.APIConnectionError) as e:
            raise LLMUnavailable(f"OpenAI request failed: {type(e).__name__}") from e

    @staticmethod
    def _check_complete(resp) -> None:
        """Raise LLMError for truncated, filtered or refused responses."""
        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", "")
            raise LLMError(
                "the model declined to answer this question"
                if reason == "content_filter"
                else "the model response was cut off"
            )
        for item in resp.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", "") == "refusal":
                    raise LLMError("the model declined to answer this question")
