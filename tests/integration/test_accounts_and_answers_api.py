"""
Over HTTP: accounts, private datasets, follow-up conversations, feedback, exports and metrics.
"""

import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api.factory import create_app
from app.llm import SQLDraft
from tests import sample_files as files
from tests.fakes import GOOD_DRAFT, TEST_PASSWORD, FakeLLM, sign_up

FOLLOW_UP = SQLDraft(
    True,
    "SELECT c.segment, COUNT(*) AS customers FROM customers c GROUP BY c.segment",
    "By segment.",
    standalone_question="How many customers are there per segment?",
)


def upload(client):
    return client.post("/api/datasets", files={"file": ("sales.csv", files.csv(), "application/octet-stream")})


# ---- accounts ----------------------------------------------------------------------------------
def test_signup_login_logout(settings):
    with TestClient(create_app(settings, FakeLLM([]))) as c:
        assert c.get("/api/auth/me").json() == {"signed_in": False, "email": "", "is_admin": False}
        assert "ayd_session" in c.cookies  # guests get a session too

        email = sign_up(c)
        me = c.get("/api/auth/me").json()
        assert me["signed_in"] and me["email"] == email

        assert c.post("/api/auth/signup", json={"email": email.upper(), "password": TEST_PASSWORD}).status_code == 409
        assert c.post("/api/auth/logout").json()["signed_in"] is False
        assert c.get("/api/auth/me").json()["signed_in"] is False

        assert c.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
        assert (
            c.post("/api/auth/login", json={"email": "nobody@example.test", "password": "whatever1"}).status_code == 401
        )
        assert (
            c.post("/api/auth/login", json={"email": f"  {email.upper()} ", "password": TEST_PASSWORD}).status_code
            == 200
        )
        assert c.get("/api/auth/me").json()["email"] == email


def test_signup_validation_and_rate_limit(settings):
    s = settings.model_copy(update={"login_attempts_per_minute": 3})
    with TestClient(create_app(s, FakeLLM([]))) as c:
        assert c.post("/api/auth/signup", json={"email": "not-an-email", "password": TEST_PASSWORD}).status_code == 400
        assert c.post("/api/auth/signup", json={"email": "a@example.test", "password": "short"}).status_code == 400
        assert c.post("/api/auth/login", json={"email": "a@example.test", "password": "x"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "a@example.test", "password": "x"}).status_code == 429


def test_tampered_cookie_becomes_a_guest(settings):
    with TestClient(create_app(settings, FakeLLM([]))) as c:
        sign_up(c)
        token = c.cookies.get("ayd_session")
        c.cookies.clear()  # replace the valid cookie (setting alone can add a second one)
        c.cookies.set("ayd_session", token[:-3] + "AAA")
        assert c.get("/api/auth/me").json()["signed_in"] is False


# ---- private datasets --------------------------------------------------------------------------
def test_guests_cannot_upload(settings):
    with TestClient(create_app(settings, FakeLLM([]))) as c:
        assert upload(c).status_code == 401
        assert c.post("/api/uploads", json={"filename": "a.csv", "size": 10}).status_code == 401


def test_uploads_are_private(settings):
    app = create_app(settings, FakeLLM([GOOD_DRAFT] * 3))
    with TestClient(app) as alice, TestClient(app) as bob:
        sign_up(alice)
        sign_up(bob)
        ds = upload(alice).json()["id"]
        assert ds in [d["id"] for d in alice.get("/api/datasets").json()]
        assert ds not in [d["id"] for d in bob.get("/api/datasets").json()]
        assert bob.get(f"/api/datasets/{ds}").status_code == 404
        assert bob.get(f"/api/schema?dataset={ds}").status_code == 404
        assert bob.post("/api/ask", json={"question": "count rows", "dataset_id": ds}).status_code == 404
        assert bob.delete(f"/api/datasets/{ds}").status_code == 404
        assert alice.delete(f"/api/datasets/{ds}").status_code == 204


# ---- follow-up conversations -------------------------------------------------------------------
def test_follow_up_gets_history(settings):
    llm = FakeLLM([GOOD_DRAFT, FOLLOW_UP])
    with TestClient(create_app(settings, llm)) as c:
        first = c.post("/api/ask", json={"question": "Customers by region"}).json()
        assert first["turn"] == 1 and first["question_id"] and len(first["conversation_id"]) == 32
        assert "history" not in llm.calls[0]  # a new conversation has no context

        second = c.post(
            "/api/ask", json={"question": "and by segment?", "conversation_id": first["conversation_id"]}
        ).json()
        assert second["turn"] == 2 and second["conversation_id"] == first["conversation_id"]
        assert second["standalone_question"] == "How many customers are there per segment?"
        history = llm.calls[2]["history"]  # calls: generate, summarize, generate (follow-up), ...
        assert history == [{"question": "Customers by region", "sql": first["sql"], "answer": first["answer"]}]
        # The summary answers the standalone question, not "and by segment?".
        assert llm.calls[3]["question"] == "How many customers are there per segment?"


def test_conversations_are_per_user(settings):
    llm = FakeLLM([GOOD_DRAFT, GOOD_DRAFT])
    app = create_app(settings, llm)
    with TestClient(app) as a, TestClient(app) as b:
        conv = a.post("/api/ask", json={"question": "Customers by region"}).json()["conversation_id"]
        out = b.post("/api/ask", json={"question": "and by segment?", "conversation_id": conv}).json()
        assert out["status"] == "ok" and "history" not in llm.calls[2]  # b can't read a's conversation


# ---- feedback and exports ----------------------------------------------------------------------
def test_feedback_and_exports(settings):
    with TestClient(create_app(settings, FakeLLM([GOOD_DRAFT]))) as c, TestClient(c.app) as other:
        qid = c.post("/api/ask", json={"question": "Customers by region"}).json()["question_id"]
        assert c.post(f"/api/questions/{qid}/feedback", json={"rating": 1}).status_code == 204
        assert c.post(f"/api/questions/{qid}/feedback", json={"rating": 5}).status_code == 422
        assert other.post(f"/api/questions/{qid}/feedback", json={"rating": -1}).status_code == 404

        csv = c.get(f"/api/questions/{qid}/export?format=csv")
        assert csv.status_code == 200 and b"region,customers" in csv.content
        assert "attachment" in csv.headers["content-disposition"]
        ws = load_workbook(io.BytesIO(c.get(f"/api/questions/{qid}/export?format=xlsx").content))["Result"]
        assert [cell.value for cell in ws[1]] == ["region", "customers"] and ws.max_row == 5  # header + 4 regions
        pdf = c.post(f"/api/questions/{qid}/report", json={"chart_png": "data:image/png;base64,not-png"})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

        assert other.get(f"/api/questions/{qid}/export").status_code == 404
        assert c.get("/api/questions/not-a-question/export").status_code == 404


def test_guest_questions_move_to_the_account_on_sign_in(settings):
    with TestClient(create_app(settings, FakeLLM([GOOD_DRAFT]))) as c:
        qid = c.post("/api/ask", json={"question": "Customers by region"}).json()["question_id"]
        sign_up(c)
        assert c.get(f"/api/questions/{qid}/export").status_code == 200


# ---- metrics -----------------------------------------------------------------------------------
def test_metrics_and_admin_endpoints(settings):
    admin = "admin-user@example.test"
    s = settings.model_copy(update={"admin_emails": admin})
    llm = FakeLLM([GOOD_DRAFT, SQLDraft(False, "", "No refunds data.")])
    with TestClient(create_app(s, llm)) as c:
        qid = c.post("/api/ask", json={"question": "Customers by region"}).json()["question_id"]
        c.post("/api/ask", json={"question": "What were refunds?"})
        c.post(f"/api/questions/{qid}/feedback", json={"rating": -1, "note": "wrong grouping"})

        body = c.get("/api/metrics").json()
        live = body["live"]
        assert live["questions"] >= 2 and live["outcomes"]["answered"] >= 1 and live["outcomes"]["unanswerable"] >= 1
        assert live["latency_ms"]["p50"] is not None and live["feedback"]["not_helpful"] >= 1
        assert {"eval", "quality", "loadtest"} <= body.keys()

        assert c.get("/api/metrics/feedback").status_code == 403
        sign_up(c, admin)
        items = c.get("/api/metrics/feedback?rating=-1").json()
        assert any(i["id"] == qid and i["feedback_note"] == "wrong grouping" for i in items)
        jsonl = c.get("/api/metrics/eval-candidates").text
        assert "Customers by region" in jsonl and "TODO" in jsonl
