"""
Measurement: every question and upload is recorded so quality, speed and cost can be reported.

    pricing.py   USD per 1M tokens per model -> estimated cost of a question
    log.py       QuestionLog: write questions/uploads, read conversation history, store feedback
    metrics.py   aggregate the log into live metrics (rates, percentiles, cost, satisfaction)
    reports.py   offline reports committed to metrics/ (eval, tests, load test) for the metrics page
"""

from app.telemetry.log import QuestionLog, StoredQuestion
from app.telemetry.pricing import estimate_cost_usd

__all__ = ["QuestionLog", "StoredQuestion", "estimate_cost_usd"]
