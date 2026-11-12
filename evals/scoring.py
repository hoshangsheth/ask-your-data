"""
Execution-accuracy scoring: does the agent's result contain the reference result?

A prediction passes when:
    - it has the same number of rows as the reference, and
    - every reference column matches a distinct predicted column (extra predicted columns are fine),
      comparing values order-insensitively, case-insensitively for text, with numeric tolerance,
      and accepting a ratio given as a fraction or as a percentage (0.1234 vs 12.34).
"""

import math
from typing import Any


def _norm(v: Any) -> Any:
    """Normalise a value for comparison: numbers -> float, text -> trimmed lower-case."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return str(v).strip().lower()


def values_match(a: Any, b: Any) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, float) and isinstance(b, float):
        # x1 = same scale; x100 / x0.01 = fraction vs percentage.
        return any(math.isclose(a, b * k, rel_tol=2e-3, abs_tol=0.011) for k in (1, 100, 0.01))
    return a == b


def _column_match(ref: list[Any], pred: list[Any]) -> bool:
    """Multiset match of two columns (each predicted value used at most once)."""
    if len(ref) != len(pred):
        return False
    remaining = list(pred)
    for a in ref:
        for i, b in enumerate(remaining):
            if values_match(a, b):
                del remaining[i]
                break
        else:
            return False
    return True


def results_match(ref_rows: list[list[Any]], pred_rows: list[list[Any]]) -> bool:
    """True if every reference column is found among the predicted columns."""
    if len(ref_rows) != len(pred_rows):
        return False
    if not ref_rows:
        return True
    # Transpose rows -> columns (every row of one result has the same width).
    ref_cols, pred_cols = list(zip(*ref_rows, strict=True)), list(zip(*pred_rows, strict=True))
    used: set[int] = set()
    for rc in ref_cols:
        for j, pc in enumerate(pred_cols):
            if j not in used and _column_match(list(rc), list(pc)):
                used.add(j)
                break
        else:
            return False
    return True
