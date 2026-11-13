"""
HTTP API (app/api) end to end with FastAPI's TestClient: health, dashboard, asking questions,
input validation, API key, rate limiting, and mapping of AI-provider failures to HTTP codes.
"""

from fastapi.testclient import TestClient

from app.api.factory import create_app
from app.db.app_tables import usage_counters
from app.llm import LLMNotConfigured, LLMRateLimited
from tests.fakes import GOOD_DRAFT, FakeLLM, sign_up

QUESTION = {"question": "How many customers per region?"}


def client_for(settings, llm):
    return TestClient(create_app(settings, llm))


def test_health_schema_kpis_index(settings):
    with client_for(settings, FakeLLM([])) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        assert "orders" in c.get("/api/schema").json()["tables"]
        k = c.get("/api/kpis").json()
        assert k["revenue"] > 0 and len(k["monthly"]) == 24
        assert c.get("/").status_code == 200


def test_ask(settings):
    with client_for(settings, FakeLLM([GOOD_DRAFT])) as c:
        r = c.post("/api/ask", json=QUESTION)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and len(body["rows"]) == 4
        assert body["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_ask_validates_input(settings):
    with client_for(settings, FakeLLM([])) as c:
        assert c.post("/api/ask", json={"question": "x"}).status_code == 422
        assert c.post("/api/ask", json={"question": "a" * 501}).status_code == 422


def test_api_key_required_when_configured(settings):
    s = settings.model_copy(update={"app_api_key": "secret"})
    with client_for(s, FakeLLM([GOOD_DRAFT])) as c:
        assert c.post("/api/ask", json=QUESTION).status_code == 401
        assert c.post("/api/ask", json=QUESTION, headers={"X-API-Key": "secret"}).status_code == 200


def _fresh_counters(client):
    """The test database is shared: start each quota test from zero."""
    with client.app.state.services.owner_engine.begin() as conn:
        conn.execute(usage_counters.delete())


def test_questions_per_minute(settings):
    s = settings.model_copy(update={"questions_per_minute": 2})
    with client_for(s, FakeLLM([GOOD_DRAFT] * 3)) as c:
        _fresh_counters(c)
        codes = [c.post("/api/ask", json=QUESTION).status_code for _ in range(2)]
        r = c.post("/api/ask", json=QUESTION)
        assert codes == [200, 200] and r.status_code == 429
        assert r.json()["detail"]["code"] == "rate_minute" and int(r.headers["Retry-After"]) <= 60


def test_daily_limits_for_guests_accounts_and_the_site(settings):
    s = settings.model_copy(
        update={"questions_per_day_guest": 1, "questions_per_day_user": 2, "questions_per_day_site": 4}
    )
    app = create_app(s, FakeLLM([GOOD_DRAFT] * 6))
    with TestClient(app) as guest, TestClient(app) as user, TestClient(app) as other:
        _fresh_counters(guest)
        first = guest.post("/api/ask", json=QUESTION).json()
        assert first["questions_left_today"] == 0
        blocked = guest.post("/api/ask", json=QUESTION)
        assert blocked.status_code == 429 and blocked.json()["detail"]["code"] == "daily_guest"

        sign_up(user)
        assert user.post("/api/ask", json=QUESTION).json()["questions_left_today"] == 1
        assert user.post("/api/ask", json=QUESTION).status_code == 200
        assert user.post("/api/ask", json=QUESTION).json()["detail"]["code"] == "daily_user"

        sign_up(other)  # 3 answered so far; the site allows 4 a day for everyone together
        assert other.post("/api/ask", json=QUESTION).status_code == 200
        r = other.post("/api/ask", json=QUESTION)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "daily_site"


def test_admins_are_not_limited(settings):
    admin = "quota-admin@example.test"
    s = settings.model_copy(update={"admin_emails": admin, "questions_per_day_user": 1, "questions_per_minute": 1})
    with client_for(s, FakeLLM([GOOD_DRAFT] * 3)) as c:
        _fresh_counters(c)
        sign_up(c, admin)
        assert [c.post("/api/ask", json=QUESTION).status_code for _ in range(3)] == [200, 200, 200]


def test_provider_failure_is_not_counted(settings):
    calls = {"n": 0}

    class FlakyLLM(FakeLLM):
        def generate_sql(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMRateLimited("quota exceeded")
            return super().generate_sql(**kwargs)

    s = settings.model_copy(update={"questions_per_day_guest": 1})
    with client_for(s, FlakyLLM([GOOD_DRAFT])) as c:
        _fresh_counters(c)
        r = c.post("/api/ask", json=QUESTION)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "ai_busy"
        assert c.post("/api/ask", json=QUESTION).status_code == 200  # the failed one was given back


def test_provider_not_configured_returns_503(settings):
    class NoKey(FakeLLM):
        def generate_sql(self, **kwargs):
            raise LLMNotConfigured("set ANTHROPIC_API_KEY")

    with client_for(settings, NoKey([])) as c:
        r = c.post("/api/ask", json=QUESTION)
        detail = r.json()["detail"]
        assert (
            r.status_code == 503 and detail["code"] == "ai_not_configured" and "ANTHROPIC_API_KEY" in detail["message"]
        )


def test_provider_rate_limit_returns_429(settings):
    class Limited(FakeLLM):
        def generate_sql(self, **kwargs):
            raise LLMRateLimited("quota reached")

    with client_for(settings, Limited([])) as c:
        r = c.post("/api/ask", json=QUESTION)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "ai_busy"


def test_missing_gemini_key_without_injected_llm(settings, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    s = settings.model_copy(update={"llm_provider": "gemini", "gemini_api_key": ""})
    with client_for(s, None) as c:
        r = c.post("/api/ask", json=QUESTION)
        assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]["message"]
        h = c.get("/api/health").json()
        assert h["llm_provider"] == "gemini" and h["sql_model"] == "gemini-3.8-flash"
        assert h["llm_ready"] is False


def test_health_reports_key_present(settings):
    s = settings.model_copy(update={"llm_provider": "gemini", "gemini_api_key": "k"})
    with client_for(s, FakeLLM([])) as c:
        assert c.get("/api/health").json()["llm_ready"] is True


def test_schema_has_descriptions_and_row_counts(settings):
    with client_for(settings, FakeLLM([])) as c:
        orders = c.get("/api/schema").json()["tables"]["orders"]
        assert orders["row_count"] > 0 and orders["description"]
        assert any(col["name"] == "status" and col["description"] for col in orders["columns"])


def test_static_modules_served_as_javascript(settings):
    with client_for(settings, FakeLLM([])) as c:
        r = c.get("/static/js/main.js")
        assert r.status_code == 200 and "javascript" in r.headers["content-type"]
