"""
Lakh/crore formatting given to the summary model (app/llm/indian_units.py), and that money
columns reach the prompt pre-formatted.
"""

from app.llm.indian_units import inr_words, is_money_column
from app.llm.text_to_sql import _annotate_money


def test_inr_words():
    assert inr_words(2977215.55) == "₹29.77 lakh"
    assert inr_words(13_500_000) == "₹1.35 crore"
    assert inr_words(-1436485.85) == "-₹14.36 lakh"
    assert inr_words(16319) == "₹16,319"


def test_money_columns_detected():
    assert is_money_column("q4_revenue") and is_money_column("revenue_change") and is_money_column("aov")
    assert not is_money_column("region") and not is_money_column("orders") and not is_money_column("return_rate")


def test_rows_are_annotated_for_the_prompt():
    row = _annotate_money(["region", "last_quarter_revenue", "orders"], ["East", 2977215.55, 120])
    assert row == ["East", "₹29.77 lakh (2977215.55)", 120]
