"""
Start the real application for testing, isolated from development data.

    with running_server(port=8010) as srv:
        srv.url            # http://127.0.0.1:8010
        srv.process        # psutil.Process of the uvicorn worker (CPU / memory sampling)

The server uses its own SQLite database and upload folder under data/eval/ (wiped at start, then
seeded with the demo store by the app itself), the AI settings from .env, and no rate limits
unless asked for, so load tests measure the app rather than the limiter.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
EVAL_DATA = ROOT / "data" / "eval"
RESULTS = Path(__file__).resolve().parent / "results"


@dataclass
class Server:
    url: str
    process: psutil.Process
    startup_s: float
    log_path: Path


@contextlib.contextmanager
def running_server(port: int = 8010, fresh: bool = True, rate_limit: int = 0, workers: int = 1) -> Iterator[Server]:
    if fresh and EVAL_DATA.exists():
        shutil.rmtree(EVAL_DATA)
    EVAL_DATA.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{(EVAL_DATA / 'shop.db').as_posix()}",
        "UPLOADS_DIR": str(EVAL_DATA / "uploads"),
        "RATE_LIMIT_PER_MINUTE": str(rate_limit),
        "LOGIN_ATTEMPTS_PER_MINUTE": "0" if rate_limit == 0 else "10",
        "ADMIN_EMAILS": "eval-admin@example.test",
        "PYTHONIOENCODING": "utf-8",
    }
    RESULTS.mkdir(exist_ok=True)
    log_path = RESULTS / f"server_{port}.log"
    log = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - closed in finally
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"]
    if workers > 1:
        cmd += ["--workers", str(workers)]
    started = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 120
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited early; see {log_path}")
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{url}/api/health", timeout=2).status_code == 200:
                    break
            if time.time() > deadline:
                raise TimeoutError("server did not start within 120 s")
            time.sleep(0.25)
        startup = time.perf_counter() - started
        yield Server(url=url, process=psutil.Process(proc.pid), startup_s=round(startup, 2), log_path=log_path)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def all_processes(server: Server) -> list[psutil.Process]:
    """The server process plus its children (uvicorn workers)."""
    try:
        return [server.process, *server.process.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []
