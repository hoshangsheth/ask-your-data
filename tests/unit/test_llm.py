"""
LLM layer (app/llm): each provider adapter's request shape, response parsing and error mapping,
the factory's provider switching, and the shared prompt layer. SDK clients are replaced with
stubs, so no network or API keys are used.
"""

import json
from types import SimpleNamespace as NS

import pytest

from app.core.config import Settings
from app.llm import (
    JSONResult,
    LLMAuthError,
    LLMError,
    LLMNotConfigured,
    LLMRateLimited,
    TextToSQL,
    build_llm,
)
from app.llm.prompts import SQL_SCHEMA

PAYLOAD = {"answerable": True, "sql": "SELECT 1 FROM orders", "explanation": "x"}
CALL = dict(model="m", system="sys", user="q", schema=SQL_SCHEMA, schema_name="sql_draft", reasoning="medium")


class Recorder:
    """Stub for an SDK method: records kwargs and returns (or raises) a fixed value."""

    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.kwargs = result, exc, None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.result


# ---- Gemini ---------------------------------------------------------------------------------
@pytest.fixture
def gemini():
    from app.llm.providers.gemini import GeminiProvider

    return GeminiProvider(api_key="test-key")


def gemini_response(text=json.dumps(PAYLOAD), finish="STOP"):
    from google.genai import types

    return NS(
        text=text,
        prompt_feedback=None,
        candidates=[NS(finish_reason=types.FinishReason(finish))],
        usage_metadata=NS(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=30),
    )


def test_gemini_request_and_parse(gemini):
    rec = Recorder(gemini_response())
    gemini.client = NS(models=NS(generate_content=rec))
    r = gemini.complete_json(**CALL)
    assert r.data == PAYLOAD and r.input_tokens == 100 and r.output_tokens == 50  # output + thinking
    cfg = rec.kwargs["config"]
    assert rec.kwargs["model"] == "m" and cfg.system_instruction == "sys"
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == SQL_SCHEMA
    assert cfg.thinking_config.thinking_level.value == "MEDIUM"


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY"])
def test_gemini_bad_finish(gemini, finish):
    gemini.client = NS(models=NS(generate_content=Recorder(gemini_response(finish=finish))))
    with pytest.raises(LLMError):
        gemini.complete_json(**CALL)


@pytest.mark.parametrize(
    "code, message, exc",
    [
        (400, "API key not valid. Please pass a valid API key.", LLMAuthError),
        (403, "permission denied", LLMAuthError),
        (429, "quota exceeded", LLMRateLimited),
        (404, "model not found", LLMNotConfigured),
    ],
)
def test_gemini_error_mapping(gemini, code, message, exc):
    from google.genai import errors

    err = errors.ClientError(code, {"error": {"code": code, "message": message, "status": "X"}})
    gemini.client = NS(models=NS(generate_content=Recorder(exc=err)))
    with pytest.raises(exc):
        gemini.complete_json(**CALL)


def test_gemini_invalid_json(gemini):
    gemini.client = NS(models=NS(generate_content=Recorder(gemini_response(text="not json"))))
    with pytest.raises(LLMError, match="invalid JSON"):
        gemini.complete_json(**CALL)


# ---- Anthropic ------------------------------------------------------------------------------
def test_anthropic_request_and_parse():
    from app.llm.providers.anthropic import AnthropicProvider

    p = AnthropicProvider(api_key="test-key")
    rec = Recorder(
        NS(
            stop_reason="end_turn",
            content=[NS(type="text", text=json.dumps(PAYLOAD))],
            usage=NS(input_tokens=10, output_tokens=5),
        )
    )
    p.client = NS(beta=NS(messages=NS(create=rec)))
    r = p.complete_json(**CALL)
    assert r.data == PAYLOAD and (r.input_tokens, r.output_tokens) == (10, 5)
    assert rec.kwargs["output_config"]["effort"] == "medium"
    assert rec.kwargs["output_config"]["format"]["schema"] == SQL_SCHEMA


def test_anthropic_refusal():
    from app.llm.providers.anthropic import AnthropicProvider

    p = AnthropicProvider(api_key="test-key")
    p.client = NS(beta=NS(messages=NS(create=Recorder(NS(stop_reason="refusal", content=[], usage=None)))))
    with pytest.raises(LLMError, match="declined"):
        p.complete_json(**CALL)


# ---- OpenAI ---------------------------------------------------------------------------------
def test_openai_request_and_parse():
    from app.llm.providers.openai import OpenAIProvider

    p = OpenAIProvider(api_key="test-key")
    rec = Recorder(
        NS(status="completed", output=[], output_text=json.dumps(PAYLOAD), usage=NS(input_tokens=7, output_tokens=3))
    )
    p.client = NS(responses=NS(create=rec))
    r = p.complete_json(**CALL)
    assert r.data == PAYLOAD and (r.input_tokens, r.output_tokens) == (7, 3)
    assert rec.kwargs["reasoning"] == {"effort": "medium"} and rec.kwargs["instructions"] == "sys"
    fmt = rec.kwargs["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] == SQL_SCHEMA


def test_openai_incomplete():
    from app.llm.providers.openai import OpenAIProvider

    p = OpenAIProvider(api_key="test-key")
    resp = NS(
        status="incomplete", incomplete_details=NS(reason="max_output_tokens"), output=[], output_text="", usage=None
    )
    p.client = NS(responses=NS(create=Recorder(resp)))
    with pytest.raises(LLMError, match="cut off"):
        p.complete_json(**CALL)


# ---- Factory: switching provider by configuration ---------------------------------------------
def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_default_is_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    llm = build_llm(settings())
    assert llm.describe() == {
        "provider": "gemini",
        "sql_model": "gemini-3.8-flash",
        "summary_model": "gemini-3.5-flash-lite",
    }


def test_switch_provider_by_config():
    llm = build_llm(settings(llm_provider="anthropic", anthropic_api_key="k"))
    assert llm.describe()["provider"] == "anthropic"
    llm = build_llm(settings(llm_provider="openai", openai_api_key="k", llm_sql_model="some-model"))
    assert llm.describe() == {"provider": "openai", "sql_model": "some-model", "summary_model": "some-model"}


def test_model_override():
    llm = build_llm(
        settings(gemini_api_key="k", llm_sql_model="gemini-3.6-flash", llm_summary_model="gemini-3.1-flash-lite")
    )
    assert (llm.sql_model, llm.summary_model) == ("gemini-3.6-flash", "gemini-3.1-flash-lite")


@pytest.mark.parametrize(
    "kw, match",
    [
        ({"llm_provider": "mistral"}, "unknown LLM_PROVIDER"),
        ({"llm_provider": "openai", "openai_api_key": "k"}, "LLM_SQL_MODEL"),
    ],
)
def test_factory_errors(kw, match):
    with pytest.raises(LLMNotConfigured, match=match):
        build_llm(settings(**kw))


def test_missing_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMNotConfigured, match="GEMINI_API_KEY"):
        build_llm(settings())


# ---- Prompt layer (shared by all providers) -------------------------------------------------
class FakeProvider:
    name = "fake"

    def __init__(self, data):
        self.data, self.calls = data, []

    def complete_json(self, **kw):
        self.calls.append(kw)
        return JSONResult(self.data, kw["model"], 11, 22)


def test_text_to_sql_uses_right_model_and_reasoning():
    p = FakeProvider(PAYLOAD)
    t = TextToSQL(p, sql_model="big", summary_model="small", sql_reasoning="high", summary_reasoning="low")
    d = t.generate_sql(question="q?", schema="TABLE x", dialect="postgres", previous_sql="SELECT bad", error="boom")
    assert d.sql == PAYLOAD["sql"] and d.usage["output_tokens"] == 22
    call = p.calls[0]
    assert call["model"] == "big" and call["reasoning"] == "high"
    assert "PostgreSQL" in call["system"] and "TABLE x" in call["system"]
    assert "SELECT bad" in call["user"] and "boom" in call["user"]

    p.data = {"answer": "a", "chart": "none", "x": "", "y": ""}
    s = t.summarize(question="q?", sql="SELECT 1", columns=["n"], rows=[[1]] * 80, truncated=False)
    assert s.answer == "a" and p.calls[1]["model"] == "small" and p.calls[1]["reasoning"] == "low"
    assert "first 50" in p.calls[1]["user"]
