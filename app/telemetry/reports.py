"""
Offline reports committed to the repository under metrics/ and shown on the metrics page:

    metrics/eval.json        latest evaluation run (python -m evals.run_eval)
    metrics/quality.json     test count and code coverage (python -m scripts.quality_report)
    metrics/loadtest.json    API load test against a deployment (python -m scripts.loadtest URL)

A missing or unreadable report is simply left out.
"""

import json
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

METRICS_DIR = PROJECT_ROOT / "metrics"
REPORTS = ("eval", "quality", "loadtest")


def load_reports(folder: Path = METRICS_DIR) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in REPORTS:
        try:
            out[name] = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out[name] = None
    return out
