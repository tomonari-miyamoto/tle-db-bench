"""Benchmark orchestration: warm/cold runs, concurrency, secondary queries, count checks."""

from __future__ import annotations

import platform
import shlex
import subprocess
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .fetchers import FETCH_PATHS, BaseFetcher, FetchResult, make_factory
from .generator import Manifest, make_catalog
from .queries import Query
from .schema import CH_TABLE, pg_table_for
from .sizes import clickhouse_settle, clickhouse_size, timescale_settle, timescale_size
from .windows import default_target_rows, size_window

# db -> docker compose service name (fixed allow-list; used for cold restarts only)
SERVICES = {"clickhouse": "clickhouse", "timescaledb": "timescaledb"}
PATH_DB = {
    "clickhouse-connect-arrow": "clickhouse",
    "psycopg3-binary-copy": "timescaledb",
    "adbc-postgresql-arrow": "timescaledb",
}


@dataclass
class RunOptions:
    target_rows: int | None = None  # default: 10% of the table
    reps: int = 5
    warmups: int = 1
    concurrency: tuple[int, ...] = (1, 4)
    paths: tuple[str, ...] = FETCH_PATHS
    cold: bool = False
    variant: str = "compressed"
    secondary: bool = True
    asof_position: float = 0.9
    settle_timeout_s: float = 600.0


def range_queries(m: Manifest, target_rows: int, concurrency: int) -> list[Query]:
    """One distinct window per worker, evenly spread, each returning exactly target_rows."""
    out = []
    for j in range(concurrency):
        w = size_window(m, target_rows, (j + 1) / (concurrency + 1))
        out.append(Query("range", {"lo": w.lo_us, "hi": w.hi_us}, w.rows, j))
    return out


def secondary_queries(m: Manifest, asof_position: float) -> list[Query]:
    cat = make_catalog(m.seed, m.objects)
    nid = int(cat["norad"][len(cat["norad"]) // 2])
    ts = m.epoch_us(min(m.rows - 1, round(asof_position * m.rows)))
    return [Query("object", {"nid": nid}, None, 0), Query("asof", {"ts": ts}, None, 0)]


def run_concurrent(
    factory: Callable[[], BaseFetcher], queries: list[Query]
) -> tuple[float, list[FetchResult]]:
    """Connect len(queries) clients, release them together, return (wall_s, results)."""
    fetchers = [factory() for _ in queries]
    try:
        for f in fetchers:
            f.connect()
        barrier = threading.Barrier(len(fetchers) + 1)

        def work(f: BaseFetcher, q: Query) -> FetchResult:
            barrier.wait()
            return f.fetch(q)

        with ThreadPoolExecutor(len(fetchers)) as pool:
            futures = [pool.submit(work, f, q) for f, q in zip(fetchers, queries, strict=True)]
            barrier.wait()
            t0 = time.perf_counter()
            results = [fu.result() for fu in futures]
            wall = time.perf_counter() - t0
        return wall, results
    finally:
        for f in fetchers:
            f.close()


def restart_service(
    db: str,
    factory: Callable[[], BaseFetcher],
    timeout_s: float = 180.0,
    cold_restart_cmd: str | None = None,
) -> None:
    """Restart the database and wait until a client can connect (cold-ish run).

    With `cold_restart_cmd`, run that program instead of the local docker compose restart. It is
    a program plus optional fixed arguments (split with shlex rules); the allow-listed service
    name is appended as the last argument. Nothing goes through a shell.
    """
    if cold_restart_cmd:
        argv = [*shlex.split(cold_restart_cmd), SERVICES[db]]
        subprocess.run(argv, check=True)
    else:
        subprocess.run(["docker", "compose", "restart", SERVICES[db]], check=True)
    deadline = time.monotonic() + timeout_s
    while True:
        f = factory()
        try:
            f.connect()
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
        finally:
            f.close()


def check_row_counts(runs: list[dict[str, Any]]) -> list[str]:
    """Mismatch descriptions: all fetches of one (query, window) must agree, and match expected."""
    seen: dict[tuple[str, int], dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    problems: list[str] = []
    for run in runs:
        for f in run["fetches"]:
            key = (run["query"], f["window_id"])
            seen[key][f["rows"]].add(run["path"])
            exp = f.get("expected_rows")
            if exp is not None and f["rows"] != exp:
                problems.append(
                    f"{run['path']} {run['query']} window {f['window_id']}: "
                    f"got {f['rows']} rows, expected {exp}"
                )
    for (query, wid), counts in seen.items():
        if len(counts) > 1:
            detail = "; ".join(f"{n} rows from {sorted(p)}" for n, p in sorted(counts.items()))
            problems.append(f"{query} window {wid}: row counts differ across paths: {detail}")
    return sorted(set(problems))


class TableSizeError(RuntimeError):
    """A table's row count differs from the manifest (duplicate load, partial load)."""


def table_size_problems(sizes: dict[str, dict[str, Any]], expected_rows: int) -> list[str]:
    """Pure check of table row counts against the manifest, one message per bad table."""
    return [
        f"{db}: table {s.get('table', '?')} holds {s['row_count']:,} rows, dataset has "
        f"{expected_rows:,}"
        for db, s in sizes.items()
        if s["row_count"] != expected_rows
    ]


def run_benchmark(settings: Settings, m: Manifest, opts: RunOptions) -> dict[str, Any]:
    pg_table = pg_table_for(opts.variant)
    k = opts.target_rows or default_target_rows(m)
    runs: list[dict[str, Any]] = []

    def record(
        path: str,
        state: str,
        rep: int,
        wall: float,
        results: list[FetchResult],
        queries: list[Query],
        conc: int,
    ) -> None:
        fetches = []
        for r, q in zip(results, queries, strict=True):
            d = r.to_dict()
            d["expected_rows"] = q.expected_rows
            fetches.append(d)
        runs.append(
            {
                "db": PATH_DB[path],
                "path": path,
                "query": queries[0].kind,
                "concurrency": conc,
                "state": state,
                "rep": rep,
                "wall_s": wall,
                "fetches": fetches,
            }
        )

    plan: list[tuple[list[Query], int]] = [(range_queries(m, k, c), c) for c in opts.concurrency]
    if opts.secondary:
        plan += [([q], 1) for q in secondary_queries(m, opts.asof_position)]

    # Fail fast on duplicate or mis-sized tables, before settling or any timing.
    pre = {
        "clickhouse": clickhouse_size(settings, CH_TABLE),
        "timescaledb": timescale_size(settings, pg_table),
    }
    bad = table_size_problems(pre, m.rows)
    if bad:
        raise TableSizeError(
            "; ".join(bad) + ". Reload with `tlebench load --recreate` before benchmarking."
        )

    # Settle before any timed read: ClickHouse merges drained and part count stable, no
    # (auto)vacuum/analyze running on the hypertable. Recorded so unsettled runs are visible.
    dbs = {PATH_DB[p] for p in opts.paths}
    settle: dict[str, dict[str, Any]] = {}
    if "clickhouse" in dbs:
        settle["clickhouse"] = clickhouse_settle(settings, CH_TABLE, opts.settle_timeout_s)
    if "timescaledb" in dbs:
        settle["timescaledb"] = timescale_settle(settings, pg_table, opts.settle_timeout_s)
    for db, st in settle.items():
        print(f"settle {db}: {st}", flush=True)

    for path in opts.paths:
        factory = make_factory(path, settings, pg_table)
        db = PATH_DB[path]
        for queries, conc in plan:
            states = ["warm"] + (["cold"] if opts.cold else [])
            for state in states:
                if state == "warm":
                    for _ in range(opts.warmups):
                        run_concurrent(factory, queries)
                for rep in range(opts.reps):
                    if state == "cold":
                        restart_service(db, factory, cold_restart_cmd=settings.cold_restart_cmd)
                    wall, results = run_concurrent(factory, queries)
                    record(path, state, rep, wall, results, queries, conc)
                    print(
                        f"{path} {queries[0].kind} c={conc} {state} rep={rep}: {wall:.2f}s",
                        flush=True,
                    )

    sizes = {
        "clickhouse": clickhouse_size(settings, CH_TABLE),
        "timescaledb": timescale_size(settings, pg_table),
    }
    problems = check_row_counts(runs)
    return {
        "meta": {
            "created": datetime.now(UTC).isoformat(),
            "host": platform.platform(),
            "total_rows": m.rows,
            "target_rows": k,
            "seed": m.seed,
            "objects": m.objects,
            "reps": opts.reps,
            "warmups": opts.warmups,
            "variant": opts.variant,
            "cold": opts.cold,
            "concurrency": list(opts.concurrency),
            "settings": settings.public(),
            "settle": settle,
        },
        "table_sizes": sizes,
        "row_count_check": {"ok": not problems, "problems": problems},
        "runs": runs,
    }
