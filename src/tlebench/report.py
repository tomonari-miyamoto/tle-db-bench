"""Render results.json into a markdown comparison table."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

TARGET_ROWS = 10_000_000
TARGET_SECONDS = 5.0


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def verdict(p95_s: float, target_s: float = TARGET_SECONDS) -> str:
    return "PASS" if p95_s < target_s else "FAIL"


def row_verdict(
    p95_s: float,
    *,
    primary: bool,
    scaled: bool,
    rows: int,
    invalid: bool,
    unsettled: bool,
    target_s: float = TARGET_SECONDS,
) -> str:
    """Verdict cell. INVALID beats everything; scaled runs get no PASS/FAIL."""
    if invalid:
        return "INVALID"
    if not primary:
        return "n/a"
    if scaled:
        return f"n/a (scaled: {rows:,} rows)"
    v = verdict(p95_s, target_s)
    return f"{v} (unsettled)" if unsettled else v


def summarise(results: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per (query, path, concurrency, state) with p50/p95 over all fetches.

    `rows` is the minimum row count over the fetches. `invalid` lists reasons the row cannot be
    trusted (cross-DB count MISMATCH, or a fetch whose count differs from expected);
    `unsettled` is true when the row's database was not settled before timing.
    """
    mismatch = not results.get("row_count_check", {"ok": True})["ok"]
    settle = results.get("meta", {}).get("settle", {})
    groups: dict[tuple, list[tuple[dict, float]]] = defaultdict(list)
    for run in results["runs"]:
        key = (run["query"], run["path"], run["db"], run["concurrency"], run["state"])
        for f in run["fetches"]:
            groups[key].append((f, run["wall_s"]))
    rows = []
    for (query, path, db, conc, state), items in groups.items():
        fetches = [f for f, _ in items]
        ttlr = [f["ttlr_s"] for f in fetches]
        ttfb = [f["ttfb_s"] for f in fetches]
        rps = [f["rows"] / f["ttlr_s"] for f in fetches if f["ttlr_s"] > 0]
        mbs = [f["nbytes"] / 1e6 / f["ttlr_s"] for f in fetches if f["ttlr_s"] > 0]
        invalid = ["row-count check MISMATCH"] if mismatch else []
        if any(
            f.get("expected_rows") is not None and f["rows"] != f["expected_rows"] for f in fetches
        ):
            invalid.append("fetch row count differs from expected")
        rows.append(
            {
                "query": query,
                "path": path,
                "db": db,
                "concurrency": conc,
                "state": state,
                "samples": len(fetches),
                "rows": min(f["rows"] for f in fetches),
                "invalid": invalid,
                "unsettled": not settle.get(db, {"settled": True})["settled"],
                "ttfb_p50": percentile(ttfb, 50),
                "ttlr_p50": percentile(ttlr, 50),
                "ttlr_p95": percentile(ttlr, 95),
                "rows_per_s_p50": percentile(rps, 50) if rps else 0.0,
                "mb_per_s_p50": percentile(mbs, 50) if mbs else 0.0,
            }
        )
    order = {"range": 0, "object": 1, "asof": 2}
    rows.sort(key=lambda r: (order.get(r["query"], 9), r["path"], r["concurrency"], r["state"]))
    return rows


def _fmt_bytes(n: float) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB"


def render_markdown(
    results: dict[str, Any],
    target_s: float = TARGET_SECONDS,
    target_rows: int = TARGET_ROWS,
) -> str:
    meta = results["meta"]
    lines = [
        "# TLE bulk retrieval benchmark: ClickHouse vs TimescaleDB",
        "",
        f"- Created: {meta['created']}  Host: {meta['host']}",
        f"- Table rows: {meta['total_rows']:,}  Objects: {meta['objects']:,}  "
        f"Seed: {meta['seed']}  Timescale variant: {meta['variant']}",
        f"- Primary query target rows: {meta['target_rows']:,}  Reps: {meta['reps']}  "
        f"Warmups: {meta['warmups']}",
        f"- Target: {target_rows:,} rows in the client in under {target_s:g} s "
        f"(verdict = p95 time-to-last-row < {target_s:g} s)",
        "",
    ]
    if meta["target_rows"] < target_rows:
        lines += [
            f"> WARNING: this run fetched {meta['target_rows']:,} rows per query, fewer than "
            f"the {target_rows:,}-row target. No PASS/FAIL verdict is given for scaled rows. "
            "The linear 10M estimate is indicative only: it ignores fixed query overhead, "
            "cache and working-set effects, chunk/partition counts and the network.",
            "",
        ]
    settle = meta.get("settle", {})
    if settle:
        parts = []
        for db, st in settle.items():
            detail = (
                f"{st['active_parts']} active parts"
                if "active_parts" in st
                else f"{st.get('chunks', '?')} chunks"
            )
            parts.append(
                f"{db} {'settled' if st['settled'] else 'NOT settled'} "
                f"({detail}, waited {st['waited_s']} s)"
            )
        lines += ["Pre-run settle: " + "; ".join(parts), ""]
        if not all(st["settled"] for st in settle.values()):
            lines += [
                "> WARNING: background merges or (auto)vacuum were still running when "
                "timing started; results may be skewed.",
                "",
            ]
    check = results["row_count_check"]
    lines.append("Row-count check across databases: " + ("OK" if check["ok"] else "MISMATCH"))
    lines += [f"- {p}" for p in check["problems"]]
    lines += ["", "## On-disk size", "", "| DB | Table | Size | Rows |", "|---|---|---|---|"]
    for db, s in results["table_sizes"].items():
        lines.append(
            f"| {db} | {s['table']} | {_fmt_bytes(s['bytes_on_disk'])} | {s['row_count']:,} |"
        )
    lines += [
        "",
        "## Results",
        "",
        "| Query | DB / path | Conc | State | Rows | TTFB p50 (s) | Last p50 (s) | Last p95 (s) "
        "| Rows/s p50 | MB/s p50 | Est. 10M p95 (s, indicative only) | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summarise(results):
        primary = r["query"] == "range"
        scaled = primary and r["rows"] < target_rows
        est = r["ttlr_p95"] * target_rows / r["rows"] if scaled and r["rows"] else None
        v = row_verdict(
            r["ttlr_p95"],
            primary=primary,
            scaled=scaled,
            rows=r["rows"],
            invalid=bool(r["invalid"]),
            unsettled=r["unsettled"],
            target_s=target_s,
        )
        lines.append(
            f"| {r['query']} | {r['path']} | {r['concurrency']} | {r['state']} | {r['rows']:,} "
            f"| {r['ttfb_p50']:.3f} | {r['ttlr_p50']:.3f} | {r['ttlr_p95']:.3f} "
            f"| {r['rows_per_s_p50']:,.0f} | {r['mb_per_s_p50']:.1f} "
            f"| {f'{est:.2f}' if est is not None else '-'} "
            f"| {v} |"
        )
    lines += [
        "",
        "MB/s counts decoded in-memory Arrow bytes. With concurrency > 1 each worker is one "
        "sample (one distinct window per worker). p95 over few repetitions approaches the max.",
    ]
    return "\n".join(lines) + "\n"


def render_file(
    results_path: Path | str,
    out_path: Path | str,
    target_s: float = TARGET_SECONDS,
    target_rows: int = TARGET_ROWS,
) -> str:
    results = json.loads(Path(results_path).read_text())
    md = render_markdown(results, target_s, target_rows)
    Path(out_path).write_text(md)
    return md
