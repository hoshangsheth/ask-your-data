"""
Agent workflow (app/agent/graph.py) with a scripted model against the real database:
happy path, self-correction after validation and database errors, giving up, unanswerable
questions, and model errors.
"""

from app.agent import SQLAgent
from app.llm import LLMError, SQLDraft, Summary
from app.sources import build_demo_source
from tests.fakes import GOOD_DRAFT, FakeLLM


def make_agent(ro_engine, llm):
    return SQLAgent(llm, build_demo_source(ro_engine), max_rows=100, max_attempts=3, timeout_ms=3000)


def test_happy_path(ro_engine):
    llm = FakeLLM([GOOD_DRAFT], Summary("4 regions.", "bar", "region", "customers"))
    out = make_agent(ro_engine, llm).ask("customers per region?")
    assert out["status"] == "ok" and out["attempts"] == 1
    assert out["columns"] == ["region", "customers"] and len(out["rows"]) == 4
    assert out["chart"] == {"type": "bar", "x": "region", "y": "customers"}
    assert "LIMIT 100" in out["sql"]
    assert [t["step"] for t in out["trace"]] == ["generate_sql", "validate", "execute", "summarize"]


def test_retries_after_validation_error(ro_engine):
    llm = FakeLLM([SQLDraft(True, "DELETE FROM orders", "oops"), GOOD_DRAFT])
    out = make_agent(ro_engine, llm).ask("customers per region?")
    assert out["status"] == "ok" and out["attempts"] == 2
    retry_call = [c for c in llm.calls if c["fn"] == "generate_sql"][1]
    assert retry_call["previous_sql"] == "DELETE FROM orders"
    assert "validation" in retry_call["error"]


def test_retries_after_database_error(ro_engine):
    llm = FakeLLM([SQLDraft(True, "SELECT no_such_column FROM orders", "typo"), GOOD_DRAFT])
    out = make_agent(ro_engine, llm).ask("customers per region?")
    assert out["status"] == "ok" and out["attempts"] == 2
    assert [t["step"] for t in out["trace"]][:4] == ["generate_sql", "validate", "execute", "generate_sql"]


def test_gives_up_after_max_attempts(ro_engine):
    bad = SQLDraft(True, "SELECT * FROM users", "wrong table")
    llm = FakeLLM([bad, bad, bad])
    out = make_agent(ro_engine, llm).ask("anything")
    assert out["status"] == "failed" and out["attempts"] == 3
    assert "unknown table" in out["explanation"]  # the error detail, for the "Technical detail" toggle
    assert "rephrasing" in out["answer"] and "Last error" not in out["answer"]  # plain advice for people
    assert not any(c["fn"] == "summarize" for c in llm.calls)


def test_unanswerable_stops_early(ro_engine):
    llm = FakeLLM([SQLDraft(False, "", "Website traffic is not stored in this database.")])
    out = make_agent(ro_engine, llm).ask("bounce rate?")
    assert out["status"] == "unanswerable" and "not stored" in out["answer"]
    assert len(llm.calls) == 1


def test_token_usage_is_summed_from_trace(ro_engine):
    draft = SQLDraft(
        GOOD_DRAFT.answerable,
        GOOD_DRAFT.sql,
        GOOD_DRAFT.explanation,
        usage={"model": "m", "input_tokens": 100, "output_tokens": 40},
    )
    summary = Summary("ok", "none", "", "", usage={"model": "s", "input_tokens": 30, "output_tokens": 10})
    out = make_agent(ro_engine, FakeLLM([draft], summary)).ask("customers per region?")
    assert out["usage"] == {"input_tokens": 130, "output_tokens": 50}


def test_llm_error_is_reported_as_failed_answer(ro_engine):
    class Broken(FakeLLM):
        def generate_sql(self, **kwargs):
            raise LLMError("the model declined to answer this question")

    out = make_agent(ro_engine, Broken([])).ask("x")
    assert out["status"] == "failed" and "declined" in out["explanation"] and "Asking again" in out["answer"]
