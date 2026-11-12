"""
Chart selection: the model suggests a chart; this module accepts it only if it fits the actual data.

Usage:
    pick_chart("bar", "region", "revenue", columns, rows)  ->  {"type": "bar", "x": "region", "y": "revenue"} | None
"""

from typing import Any

CHART_TYPES = {"bar", "line", "pie"}
MAX_PIE_SLICES = 6


def pick_chart(chart: str, x: str, y: str, columns: list[str], rows: list[list[Any]]) -> dict | None:
    """Return a chart spec for the UI, or None if the suggestion does not match the result."""
    # Needs a known type, at least two points, and two different existing columns.
    if chart not in CHART_TYPES or len(rows) < 2 or x not in columns or y not in columns or x == y:
        return None
    # The value axis must be numeric.
    yi = columns.index(y)
    if not all(isinstance(r[yi], (int, float)) or r[yi] is None for r in rows):
        return None
    # Pies with many slices are unreadable; fall back to bars.
    if chart == "pie" and len(rows) > MAX_PIE_SLICES:
        chart = "bar"
    return {"type": chart, "x": x, "y": y}
