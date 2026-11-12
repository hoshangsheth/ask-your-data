"""
Async load generator used by the load, stress and soak tests.

    stats = await run_for(base, endpoints, concurrency=20, seconds=15, sampler=...)

Each virtual user loops over `endpoints` (round-robin) for `seconds`. Returns request counts,
errors, throughput and latency percentiles; an optional sampler records server CPU and memory
(psutil) every 0.5 s while the load runs.
"""

import asyncio
import statistics
import time
from dataclasses import dataclass, field

import httpx
import psutil

from app.telemetry.metrics import percentile


@dataclass
class Sampler:
    processes: list[psutil.Process]
    cpu: list[float] = field(default_factory=list)  # % of one core, summed over processes
    rss_mb: list[float] = field(default_factory=list)
    machine_cpu: list[float] = field(default_factory=list)  # % of the whole machine (client + server)

    def prime(self) -> None:
        for p in self.processes:
            p.cpu_percent(None)
        psutil.cpu_percent(None)

    def sample(self) -> None:
        cpu = rss = 0.0
        for p in self.processes:
            try:
                cpu += p.cpu_percent(None)
                rss += p.memory_info().rss / 1_048_576
            except psutil.NoSuchProcess:
                continue
        self.cpu.append(cpu)
        self.rss_mb.append(rss)
        self.machine_cpu.append(psutil.cpu_percent(None))

    def summary(self) -> dict:
        if not self.cpu:
            return {}
        return {
            "server_cpu_pct_avg": round(statistics.mean(self.cpu), 1),
            "server_cpu_pct_max": round(max(self.cpu), 1),
            "server_rss_mb_avg": round(statistics.mean(self.rss_mb), 1),
            "server_rss_mb_max": round(max(self.rss_mb), 1),
            "machine_cpu_pct_avg": round(statistics.mean(self.machine_cpu), 1),
        }


def summarize(results: list[tuple[str, float, int]], seconds: float) -> dict:
    ms = [r[1] for r in results]
    errors = sum(not (200 <= r[2] < 300) for r in results)
    return {
        "requests": len(results),
        "errors": errors,
        "error_rate": round(errors / len(results), 4) if results else 0,
        "rps": round(len(results) / seconds, 1) if seconds else 0,
        "avg_ms": round(statistics.mean(ms), 1) if ms else None,
        "p50_ms": round(percentile(ms, 50), 1) if ms else None,
        "p95_ms": round(percentile(ms, 95), 1) if ms else None,
        "p99_ms": round(percentile(ms, 99), 1) if ms else None,
        "max_ms": round(max(ms), 1) if ms else None,
    }


async def run_for(
    base: str,
    endpoints: list[str],
    concurrency: int,
    seconds: float,
    sampler: Sampler | None = None,
    timeout: float = 30,
    per_minute: bool = False,
) -> dict:
    results: list[tuple[str, float, int]] = []
    stop = time.perf_counter() + seconds
    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency + 5)

    async with httpx.AsyncClient(
        base_url=base, timeout=timeout, limits=limits, headers={"User-Agent": "ayd-eval"}
    ) as client:

        async def user(n: int) -> None:
            i = n
            while time.perf_counter() < stop:
                path = endpoints[i % len(endpoints)]
                i += 1
                t = time.perf_counter()
                try:
                    status = (await client.get(path)).status_code
                except httpx.HTTPError:
                    status = 0  # timeout / connection error
                results.append((path, (time.perf_counter() - t) * 1000, status, time.perf_counter()))

        async def sample() -> None:
            if not sampler:
                return
            sampler.prime()
            while time.perf_counter() < stop:
                await asyncio.sleep(0.5)
                sampler.sample()

        started = time.perf_counter()
        await asyncio.gather(sample(), *(user(n) for n in range(concurrency)))
        elapsed = time.perf_counter() - started

    flat = [(p, ms, s) for p, ms, s, _ in results]
    out = {"concurrency": concurrency, "seconds": round(elapsed, 1), **summarize(flat, elapsed)}
    out["by_endpoint"] = {e: summarize([r for r in flat if r[0] == e], elapsed) for e in endpoints}
    if sampler:
        out["resources"] = sampler.summary()
    if per_minute:
        buckets: dict[int, list] = {}
        for p, ms, s, t in results:
            buckets.setdefault(int((t - started) // 60), []).append((p, ms, s))
        out["per_minute"] = [{"minute": k + 1, **summarize(v, 60)} for k, v in sorted(buckets.items())]
    return out
