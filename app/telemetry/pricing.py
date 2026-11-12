"""
Model prices, used to estimate what each question costs.

USD per 1 million tokens (input, output), from the providers' pricing pages, November 2026.
Gemini 3.8 Flash's price doubles on 1 January 2027 ($1.50 / $7.50); update the table then.
Unknown models give no estimate (None) rather than a wrong one. Override or add models with
LLM_PRICES, e.g. LLM_PRICES='{"my-model": [0.5, 2.0]}'.
"""

import contextlib
import json

PRICES_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}


def price_table(overrides_json: str = "") -> dict[str, tuple[float, float]]:
    table = dict(PRICES_USD_PER_1M)
    if overrides_json:
        # A malformed override must not break answering questions: ignore it.
        with contextlib.suppress(ValueError, TypeError, KeyError, IndexError, AttributeError):
            table.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(overrides_json).items()})
    return table


def estimate_cost_usd(trace: list[dict], prices: dict[str, tuple[float, float]]) -> float | None:
    """Sum the cost of every model call in an agent trace; None if any model's price is unknown."""
    total = 0.0
    for step in trace:
        model = step.get("model")
        if not model:
            continue
        if model not in prices:
            return None
        p_in, p_out = prices[model]
        total += (step.get("input_tokens", 0) * p_in + step.get("output_tokens", 0) * p_out) / 1_000_000
    return round(total, 8)
