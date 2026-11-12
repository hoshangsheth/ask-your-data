"""
Small pure functions: chart selection (app/agent/charts.py) and eval scoring (evals/scoring.py).
"""

from app.agent.charts import pick_chart
from evals.scoring import results_match


def test_pick_chart_accepts_good_suggestion():
    cols, rows = ["month", "revenue"], [["2025-01", 10.0], ["2025-02", 12.0]]
    assert pick_chart("line", "month", "revenue", cols, rows) == {"type": "line", "x": "month", "y": "revenue"}


def test_pick_chart_rejects_bad_suggestions():
    cols, rows = ["month", "revenue"], [["2025-01", 10.0], ["2025-02", 12.0]]
    assert pick_chart("line", "month", "nope", cols, rows) is None  # unknown column
    assert pick_chart("bar", "revenue", "month", cols, rows) is None  # y not numeric
    assert pick_chart("bar", "month", "revenue", cols, rows[:1]) is None  # single row
    assert pick_chart("scatter", "month", "revenue", cols, rows) is None  # unknown type


def test_pick_chart_turns_big_pie_into_bar():
    many = [[str(i), float(i)] for i in range(10)]
    assert pick_chart("pie", "label", "value", ["label", "value"], many)["type"] == "bar"


def test_results_match_rules():
    ref = [["East", 10.0], ["West", 20.0]]
    assert results_match(ref, [["West", 20.0], ["East", 10.0]])  # order-insensitive
    assert results_match(ref, [[10.004, "East", 1], [20.0, "west", 2]])  # extra cols, case, tolerance
    assert results_match([[0.1234]], [[12.34]])  # fraction vs percent
    assert not results_match(ref, [["East", 10.0]])  # row count differs
    assert not results_match(ref, [["East", 11.0], ["West", 20.0]])  # wrong value
