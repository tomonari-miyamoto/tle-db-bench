"""`tlebench generate|load|run|report`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings, load_dotenv
from .fetchers import FETCH_PATHS
from .generator import Manifest, generate_dataset, make_manifest
from .report import TARGET_ROWS, TARGET_SECONDS, render_file
from .schema import VARIANTS


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tlebench", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="write synthetic TLE Parquet chunks")
    g.add_argument("--rows", type=int, required=True, help="total rows (scale parameter)")
    g.add_argument("--out", default="data/tle")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--objects", type=int, default=30_000)
    g.add_argument("--start", default="2000-01-01", help="ISO date of the first epoch (UTC)")
    g.add_argument(
        "--span-days",
        type=float,
        default=None,
        help="time span in days (default: rows / 10000, the production growth rate)",
    )
    g.add_argument("--chunk-rows", type=int, default=1_000_000, help="rows per Parquet file")

    ld = sub.add_parser("load", help="bulk-load Parquet chunks and report ingest rows/s")
    ld.add_argument("--data", default="data/tle")
    ld.add_argument("--db", choices=["clickhouse", "timescaledb", "both"], default="both")
    ld.add_argument(
        "--variant",
        choices=VARIANTS,
        default="compressed",
        help="TimescaleDB table variant (columnstore or plain rowstore)",
    )
    mode = ld.add_mutually_exclusive_group()
    mode.add_argument("--recreate", action="store_true", help="drop the target table(s) first")
    mode.add_argument(
        "--append",
        action="store_true",
        help="load into a non-empty table (default: refuse, to avoid duplicated rows)",
    )
    ld.add_argument("--batch-rows", type=int, default=1_000_000)
    ld.add_argument("--chunk-interval", default="1 month", help="hypertable chunk interval")
    ld.add_argument(
        "--optimize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="ClickHouse OPTIMIZE ... FINAL after load (default: on, so both DBs "
        "start the benchmark merged/compressed)",
    )
    ld.add_argument("--results-dir", default="results")

    r = sub.add_parser("run", help="run the benchmark and write results JSON")
    r.add_argument("--data", default="data/tle")
    r.add_argument("--out", default="results/results.json")
    r.add_argument(
        "--target-rows",
        type=int,
        default=None,
        help="rows per primary query (default: 10%% of the table)",
    )
    r.add_argument("--reps", type=int, default=5)
    r.add_argument("--warmups", type=int, default=1)
    r.add_argument("--concurrency", default="1,4", help="comma-separated levels")
    r.add_argument("--paths", default=",".join(FETCH_PATHS), help="comma-separated fetch paths")
    r.add_argument("--variant", choices=VARIANTS, default="compressed")
    r.add_argument(
        "--cold",
        action="store_true",
        help="also run cold reps by restarting containers via docker compose",
    )
    r.add_argument("--skip-secondary", action="store_true")
    r.add_argument(
        "--settle-timeout",
        type=float,
        default=600.0,
        help="max seconds to wait for ClickHouse merges / Postgres (auto)vacuum "
        "to finish before timing starts",
    )

    rp = sub.add_parser("report", help="render results JSON as a markdown table")
    rp.add_argument("--results", default="results/results.json")
    rp.add_argument("--out", default="results/report.md")
    rp.add_argument("--target-seconds", type=float, default=TARGET_SECONDS)
    rp.add_argument("--target-rows", type=int, default=TARGET_ROWS)
    return p


def _cmd_generate(a: argparse.Namespace) -> int:
    m = make_manifest(a.rows, a.seed, a.objects, a.start, a.span_days, a.chunk_rows)
    generate_dataset(
        m, a.out, progress=lambda i, n: print(f"chunk {i}/{n}", file=sys.stderr, flush=True)
    )
    print(f"wrote {m.rows:,} rows in {m.n_chunks} chunk(s) to {a.out}")
    return 0


def _cmd_load(a: argparse.Namespace) -> int:
    from .loaders import TableNotEmptyError, load_clickhouse, load_timescale

    settings = Settings.from_env()
    m = Manifest.load(a.data)
    out = Path(a.results_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = []
    try:
        if a.db in ("clickhouse", "both"):
            stats.append(
                load_clickhouse(settings, m, a.data, a.recreate, a.batch_rows, a.optimize, a.append)
            )
        if a.db in ("timescaledb", "both"):
            stats.append(
                load_timescale(
                    settings,
                    m,
                    a.data,
                    a.variant,
                    a.recreate,
                    a.batch_rows,
                    a.chunk_interval,
                    a.append,
                )
            )
    except TableNotEmptyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for s in stats:
        print(json.dumps(s))
        name = f"load_{s['db']}_{s.get('variant', 'default')}.json"
        (out / name).write_text(json.dumps(s, indent=2) + "\n")
    return 0


def _cmd_run(a: argparse.Namespace) -> int:
    from .runner import RunOptions, TableSizeError, run_benchmark

    paths = tuple(x.strip() for x in a.paths.split(",") if x.strip())
    unknown = set(paths) - set(FETCH_PATHS)
    if unknown:
        raise SystemExit(f"unknown fetch paths: {sorted(unknown)}")
    opts = RunOptions(
        target_rows=a.target_rows,
        reps=a.reps,
        warmups=a.warmups,
        concurrency=tuple(int(x) for x in a.concurrency.split(",")),
        paths=paths,
        cold=a.cold,
        variant=a.variant,
        secondary=not a.skip_secondary,
        settle_timeout_s=a.settle_timeout,
    )
    try:
        results = run_benchmark(Settings.from_env(), Manifest.load(a.data), opts)
    except TableSizeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    loads = {p.stem: json.loads(p.read_text()) for p in sorted(out.parent.glob("load_*.json"))}
    results["meta"]["load"] = loads
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {out}")
    if not results["row_count_check"]["ok"]:
        for problem in results["row_count_check"]["problems"]:
            print(f"ROW COUNT MISMATCH: {problem}", file=sys.stderr)
        return 2
    return 0


def _cmd_report(a: argparse.Namespace) -> int:
    print(render_file(a.results, a.out, a.target_seconds, a.target_rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_parser().parse_args(argv)
    handler = {
        "generate": _cmd_generate,
        "load": _cmd_load,
        "run": _cmd_run,
        "report": _cmd_report,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
