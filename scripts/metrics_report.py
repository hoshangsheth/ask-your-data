"""
Print the live usage metrics straight from the database (no UI, no admin sign-in needed).

The numbers are the same as on the admin-only Metrics page: answer rate, latency percentiles,
cost, satisfaction, follow-ups, questions about the data, uploads, accounts.

Usage (from the project root):
    python -m scripts.metrics_report                        # DATABASE_URL from .env (local)
    python -m scripts.metrics_report --out metrics/live.json

For the deployed app, point it at the production database for one run, e.g. after
`vercel env pull .env.production.local` (keep that file out of git):
    python -m scripts.metrics_report --env-file .env.production.local
"""

import argparse
import json

from app.core.config import Settings
from app.db.engine import make_engines
from app.telemetry.metrics import compute_live_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Live usage metrics from the question log.")
    parser.add_argument("--env-file", default=None, help="read DATABASE_URL from this file instead of .env")
    parser.add_argument("--out", default="", help="also write the JSON to this path")
    args = parser.parse_args()

    settings = Settings(_env_file=args.env_file) if args.env_file else Settings()
    owner, _ = make_engines(settings.database_url)
    try:
        report = compute_live_metrics(owner)
    finally:
        owner.dispose()
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
