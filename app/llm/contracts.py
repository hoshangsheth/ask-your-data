"""
The contract every LLM provider adapter implements.

A provider sends a system prompt + user message and returns an object matching a JSON schema.
Nothing outside app/llm/providers/ imports a vendor SDK, so switching provider is a config change.

To add a provider: write a class with a `name` attribute and a `complete_json` method with this
exact signature, then register it in app/llm/providers/__init__.py.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

# Provider-neutral reasoning depth. Each adapter maps it to its own knob
# (Gemini thinking_level, Claude effort, OpenAI reasoning.effort).
Reasoning = Literal["low", "medium", "high"]


@dataclass
class JSONResult:
    """What a provider returns: the parsed JSON plus token usage for cost tracking."""

    data: dict[str, Any]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0  # includes thinking/reasoning tokens where the provider reports them

    def usage(self) -> dict[str, Any]:
        """Usage as a plain dict (stored in the agent trace)."""
        return {"model": self.model, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


class LLMProvider(Protocol):
    """Structural type: any class with these members is a provider."""

    name: str

    def complete_json(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], schema_name: str, reasoning: Reasoning
    ) -> JSONResult:
        """Return a response that conforms to `schema`, or raise an app.llm.errors exception."""
        ...
