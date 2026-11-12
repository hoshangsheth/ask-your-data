"""
Google Gemini adapter (SDK: `pip install google-genai`).

Config:
    LLM_PROVIDER=gemini
    GEMINI_API_KEY=...            # https://aistudio.google.com/apikey

Mapping of the provider-neutral contract:
    system prompt   -> GenerateContentConfig.system_instruction
    JSON schema     -> response_mime_type="application/json" + response_json_schema
    reasoning       -> ThinkingConfig.thinking_level (LOW / MEDIUM / HIGH)
    tokens          -> usage_metadata (output = candidates + thoughts, both billed)
"""

import json
import os
from typing import Any

from app.llm.contracts import JSONResult, Reasoning
from app.llm.errors import LLMAuthError, LLMError, LLMNotConfigured, LLMRateLimited, LLMUnavailable

# Finish reasons that mean the model declined or was blocked.
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str = "", timeout_s: float = 60.0):
        # Import here so the SDK is only required when this provider is selected.
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as e:
            raise LLMNotConfigured("install the Gemini SDK: pip install google-genai") from e
        self._types, self._errors = types, errors
        # Check for a key first: constructing the SDK client without one leaves a half-built
        # client whose cleanup logs a spurious traceback.
        if not (api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            raise LLMNotConfigured("set GEMINI_API_KEY (get one at aistudio.google.com/apikey)")
        try:
            # Empty key -> the SDK reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment.
            self.client = genai.Client(
                api_key=api_key or None, http_options=types.HttpOptions(timeout=int(timeout_s * 1000))
            )
        except ValueError as e:
            raise LLMNotConfigured("set GEMINI_API_KEY (get one at aistudio.google.com/apikey)") from e

    def complete_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], schema_name: str, reasoning: Reasoning
    ) -> JSONResult:
        t = self._types
        config = t.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            thinking_config=t.ThinkingConfig(thinking_level=t.ThinkingLevel(reasoning.upper())),
            max_output_tokens=16000,  # includes thinking tokens
        )
        resp = self._send(model, user, config)
        self._check_finish(resp)
        try:
            data = json.loads(resp.text or "")
        except json.JSONDecodeError as e:
            raise LLMError("the model returned invalid JSON") from e

        u = resp.usage_metadata
        output = ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0
        return JSONResult(
            data=data, model=model, input_tokens=(u.prompt_token_count or 0) if u else 0, output_tokens=output
        )

    def _send(self, model: str, user: str, config):
        """Call the API and translate SDK errors into provider-neutral ones."""
        errors = self._errors
        try:
            return self.client.models.generate_content(model=model, contents=user, config=config)
        except errors.ClientError as e:
            # An invalid key comes back as 400 "API key not valid".
            if e.code in (401, 403) or (e.code == 400 and "api key" in str(e).lower()):
                raise LLMAuthError("Gemini rejected the API key") from e
            if e.code == 429:
                raise LLMRateLimited("Gemini rate limit or quota reached") from e
            if e.code == 404:
                raise LLMNotConfigured(
                    f"Gemini model '{model}' not found; check LLM_SQL_MODEL / LLM_SUMMARY_MODEL"
                ) from e
            raise LLMUnavailable(f"Gemini request failed ({e.code})") from e
        except errors.ServerError as e:
            raise LLMUnavailable(f"Gemini server error ({e.code})") from e
        except errors.APIError as e:
            raise LLMUnavailable("Gemini request failed") from e
        except OSError as e:  # network failure
            raise LLMUnavailable("could not reach Gemini") from e

    @staticmethod
    def _check_finish(resp) -> None:
        """Raise LLMError if the prompt was blocked or the answer was cut off or refused."""
        feedback = getattr(resp, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise LLMError("the model declined to answer this question")
        if resp.candidates:
            reason = resp.candidates[0].finish_reason
            reason = getattr(reason, "name", str(reason))
            if reason == "MAX_TOKENS":
                raise LLMError("the model response was cut off")
            if reason in _BLOCKED:
                raise LLMError("the model declined to answer this question")
