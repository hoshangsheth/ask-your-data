"""
Run the test suite with coverage and write metrics/quality.json (shown on the Metrics page).

Usage (from the project root):
    python -m scripts.quality_report

Records: tests passed / failed / total, run time, line coverage of app/ and evals/.
"""

import json
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metrics" / "quality.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        junit, cov = Path(tmp) / "junit.xml", Path(tmp) / "coverage.json"
        started = time.perf_counter()
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--cov=app",
                "--cov=evals",
                f"--cov-report=json:{cov}",
                f"--junitxml={junit}",
            ],
            cwd=ROOT,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        suite = ET.parse(junit).getroot()
        suite = suite.find("testsuite") if suite.tag == "testsuites" else suite
        total = int(suite.get("tests", 0))
        failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
        skipped = int(suite.get("skipped", 0))
        totals = json.loads(cov.read_text(encoding="utf-8"))["totals"]

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "tests_total": total,
        "tests_passed": total - failed - skipped,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "duration_ms": duration_ms,
        "coverage": round(totals["percent_covered"] / 100, 4),
        "statements": totals["num_statements"],
        "statements_covered": totals["covered_lines"],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
