"""
Indian money formatting for prompts.

Small models often get lakh/crore conversions wrong (e.g. writing "₹29.77 crore" for 29,77,215).
So money values are formatted in code and the model is told to copy them, never convert them.

Usage:
    inr_words(2977215.55)          -> "₹29.77 lakh"
    is_money_column("q4_revenue")  -> True
"""

import re

_MONEY_COLUMN = re.compile(r"revenue|sales|gmv|value|profit|amount|cost|price|aov|spend", re.IGNORECASE)


def is_money_column(name: str) -> bool:
    """Heuristic: does this result column hold rupee amounts? (matches the UI's rule)"""
    return bool(_MONEY_COLUMN.search(name))


def inr_words(value: float) -> str:
    """Rupees in Indian units: crore (1e7), lakh (1e5), else digits with Indian grouping."""
    sign = "-" if value < 0 else ""
    a = abs(value)
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f} crore"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:.2f} lakh"
    # Below 1 lakh, Indian and international digit grouping are the same (e.g. 99,999).
    return f"{sign}₹{round(a):,}"
