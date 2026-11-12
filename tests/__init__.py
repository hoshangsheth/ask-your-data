"""
Test suite. No API keys needed: the model and vendor SDK clients are replaced by fakes/stubs.

    fakes.py         FakeLLM and canned SQL drafts shared by tests
    conftest.py      fixtures: a small seeded database (SQLite, or Postgres via TEST_DATABASE_URL)
    unit/            pure logic: SQL guard, LLM adapters/factory, chart choice, eval scoring
    integration/     real database: executor, KPIs, agent, HTTP API, eval reference SQL

Run:
    pytest -q                      # everything
    pytest tests/unit -q           # fast subset
    TEST_DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/shop pytest -q   # against Postgres
"""
