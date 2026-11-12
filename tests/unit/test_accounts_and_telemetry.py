"""
Accounts (password hashing, session tokens), cost estimation, metric aggregation and exports.
"""

import io
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from openpyxl import load_workbook

from app.accounts import Identity, SessionCodec
from app.accounts.passwords import hash_password, verify_password
from app.exports import Report, decode_png_data_url, filename_for, to_csv, to_pdf, to_xlsx
from app.telemetry.metrics import _question_metrics, percentile
from app.telemetry.pricing import estimate_cost_usd, price_table


# ---- passwords ---------------------------------------------------------------------------------
def test_password_hash_round_trip():
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$") and "correct" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)
    assert hash_password("same") != hash_password("same")  # salted
    assert not verify_password("x", "garbage") and not verify_password("x", "bcrypt$1$2$3$4$5")


# ---- session tokens ----------------------------------------------------------------------------
def test_session_tokens_are_signed_and_expire():
    codec = SessionCodec("secret-1")
    user_token = codec.issue(Identity(user_id="abcdefabcdef"))
    assert codec.read(user_token) == ("u", "abcdefabcdef")
    guest = Identity.new_guest()
    assert codec.read(codec.issue(guest)) == ("g", guest.guest_id)

    kind, ident, exp, sig = user_token.split(".")
    assert codec.read(f"u.otheruser123.{exp}.{sig}") is None  # tampered id
    assert SessionCodec("secret-2").read(user_token) is None  # different key
    assert codec.read(user_token, now=time.time() + 31 * 24 * 3600) is None  # expired
    for bad in (None, "", "a.b", "x.y.z.w"):
        assert codec.read(bad) is None


# ---- pricing -----------------------------------------------------------------------------------
def test_cost_is_summed_over_model_calls():
    prices = price_table()
    trace = [
        {"step": "generate_sql", "model": "gemini-3.8-flash", "input_tokens": 1_000_000, "output_tokens": 0},
        {"step": "validate"},
        {"step": "summarize", "model": "gemini-3.5-flash-lite", "input_tokens": 0, "output_tokens": 1_000_000},
    ]
    assert estimate_cost_usd(trace, prices) == 0.75 + 2.50
    assert estimate_cost_usd([{"model": "unknown-model", "input_tokens": 5}], prices) is None
    assert estimate_cost_usd([], prices) == 0


def test_price_overrides():
    assert price_table('{"my-model": [1, 2]}')["my-model"] == (1.0, 2.0)
    assert price_table("not json") == price_table()


# ---- metrics -----------------------------------------------------------------------------------
def test_percentile_nearest_rank():
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    data = list(range(1, 101))
    assert percentile(data, 50) == 50 and percentile(data, 95) == 95 and percentile(data, 100) == 100


def _row(**kw):
    base = dict(
        created_at=datetime.now(UTC),
        user_id=None,
        guest_id="g1",
        conversation_id="c1",
        dataset_kind="demo",
        status="ok",
        attempts=1,
        latency_ms=3000,
        sql_ms=2000,
        validate_ms=5,
        execute_ms=20,
        summary_ms=900,
        input_tokens=1000,
        output_tokens=100,
        cost_usd=0.002,
        feedback=None,
        is_follow_up=False,
        sql_model="gemini-3.8-flash",
    )
    return SimpleNamespace(**{**base, **kw})


def test_question_metrics_rates_and_latency():
    now = datetime.now(UTC)
    rows = [
        _row(feedback=1),
        _row(attempts=2, latency_ms=6000, feedback=-1, is_follow_up=True, conversation_id="c1"),
        _row(status="unanswerable", latency_ms=1500, cost_usd=0.001, conversation_id="c2"),
        _row(
            status="failed",
            attempts=3,
            latency_ms=12000,
            cost_usd=None,
            user_id="u1",
            created_at=now - timedelta(days=40),
        ),
    ]
    m = _question_metrics(rows, now)
    assert m["questions"] == 4 and m["conversations"] == 2 and m["signed_in_users"] == 1
    o = m["outcomes"]
    assert (o["answer_rate"], o["decline_rate"], o["failure_rate"]) == (0.5, 0.25, 0.25)
    assert o["first_try_rate"] == 0.25 and o["self_corrected"] == 1
    assert m["latency_ms"]["p50"] == 3000 and m["latency_ms"]["p95"] == 12000
    assert m["feedback"]["satisfaction"] == 0.5 and m["feedback"]["rated"] == 2
    assert m["follow_ups"]["share"] == 0.25
    assert m["cost_usd"]["total"] == 0.005  # unknown cost (None) excluded
    assert sum(d["questions"] for d in m["daily"]) == 3  # the 40-day-old question is outside the window
    assert sum(m["latency_ms"]["histogram"]["counts"]) == 4


# ---- exports -----------------------------------------------------------------------------------
COLS, ROWS = ["region", "revenue"], [["South", 1234.5], ["North", None]]


def test_csv_has_bom_and_header():
    out = to_csv(COLS, ROWS)
    assert out.startswith(b"\xef\xbb\xbf") and b"region,revenue" in out and b"South,1234.5" in out


def test_xlsx_round_trip():
    wb = load_workbook(io.BytesIO(to_xlsx(COLS, ROWS, "Revenue by region")))
    ws = wb["Result"]
    assert [c.value for c in ws[1]] == COLS and ws["B2"].value == 1234.5
    assert wb["About"]["B1"].value == "Revenue by region"


def test_pdf_report_handles_rupee_and_missing_chart():
    pdf = to_pdf(Report("Revenue?", "South leads at ₹29.77 lakh − up 5%", "SELECT 1", COLS, ROWS * 30, "Demo store"))
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_png_data_url_validation():
    assert decode_png_data_url("data:image/png;base64,iVBORw0KGgo=") == b"\x89PNG\r\n\x1a\n"
    assert decode_png_data_url("data:image/png;base64,bm90IGEgcG5n") is None  # not a PNG
    assert decode_png_data_url("data:text/html;base64,PGI+") is None
    assert filename_for("Top 5 products / 2025?", "csv") == "Top_5_products_2025.csv"
