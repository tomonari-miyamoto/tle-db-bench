import pytest

from tlebench import report
from tlebench.generator import make_manifest
from tlebench.loaders import TableNotEmptyError, plan_load
from tlebench.runner import check_row_counts, range_queries, table_size_problems
from tlebench.sizes import settled


def fetch(rows, ttfb, ttlr, wid=0, expected=None):
    return {
        "rows": rows,
        "nbytes": rows * 200,
        "ttfb_s": ttfb,
        "ttlr_s": ttlr,
        "window_id": wid,
        "expected_rows": expected,
    }


def run(path, db, query, ttlrs, rows=1_000, conc=1, state="warm"):
    return {
        "db": db, "path": path, "query": query, "concurrency": conc, "state": state,
        "rep": 0, "wall_s": max(ttlrs),
        "fetches": [fetch(rows, t / 10, t, expected=rows if query == "range" else None)
                    for t in ttlrs],
    }  # fmt: skip


def sample(target_rows=10_000_000):
    return {
        "meta": {"created": "2026-01-01T00:00:00+00:00", "host": "test", "total_rows": 100_000_000,
                 "objects": 30_000, "seed": 1, "variant": "compressed",
                 "target_rows": target_rows, "reps": 3, "warmups": 1},
        "table_sizes": {"clickhouse": {"table": "tle", "bytes_on_disk": 12_000_000_000,
                                       "row_count": 100_000_000},
                        "timescaledb": {"table": "tle_columnstore", "bytes_on_disk": 30_000_000,
                                        "row_count": 100_000_000}},
        "row_count_check": {"ok": True, "problems": []},
        "runs": [
            run("clickhouse-connect-arrow", "clickhouse", "range", [3.0, 4.0, 4.5], target_rows),
            run("adbc-postgresql-arrow", "timescaledb", "range", [6.0, 7.0, 8.0], target_rows),
            run("adbc-postgresql-arrow", "timescaledb", "asof", [0.5], 30_000),
        ],
    }  # fmt: skip


def test_percentiles():
    assert report.percentile([1, 2, 3, 4, 5], 50) == 3
    assert report.percentile([0, 10], 95) == 9.5


def test_verdict_threshold():
    assert report.verdict(4.99) == "PASS"
    assert report.verdict(5.0) == "FAIL"  # target is "under 5 s"
    assert report.verdict(5.01) == "FAIL"


def test_markdown_has_pass_fail_and_sections():
    md = report.render_markdown(sample())
    lines = {
        ln.split("|")[2].strip(): ln
        for ln in md.splitlines()
        if ln.startswith("| ") and "range" in ln
    }
    assert lines["clickhouse-connect-arrow"].rstrip().endswith("| PASS |")
    assert lines["adbc-postgresql-arrow"].rstrip().endswith("| FAIL |")
    assert "## On-disk size" in md and "12.00 GB" in md
    assert "Last p95 (s)" in md and "OK" in md
    assert "WARNING" not in md
    assert any(ln.endswith("| n/a |") for ln in md.splitlines() if "| asof |" in ln)


def test_scaled_run_warns_and_extrapolates():
    s = sample(target_rows=100_000)
    s["runs"][0] = run("clickhouse-connect-arrow", "clickhouse", "range", [0.04, 0.05], 100_000)
    md = report.render_markdown(s)
    assert "WARNING" in md and "indicative only" in md and "rough guide" not in md
    range_rows = [ln for ln in md.splitlines() if ln.startswith("| range |")]
    assert range_rows
    for ln in range_rows:
        assert "PASS" not in ln and "FAIL" not in ln
        assert ln.rstrip().endswith("| n/a (scaled: 100,000 rows) |")
    ch = next(ln for ln in range_rows if "| clickhouse-connect-arrow |" in ln)
    # p95 of [0.04, 0.05] = 0.0495 s, scaled by 10M / 100k
    assert "| 4.95 |" in ch


def test_summarise_groups_by_concurrency_and_state():
    s = sample()
    s["runs"].append(
        run(
            "clickhouse-connect-arrow",
            "clickhouse",
            "range",
            [5.0],
            10_000_000,
            conc=4,
            state="cold",
        )
    )
    keys = {(r["path"], r["concurrency"], r["state"]) for r in report.summarise(s)}
    assert ("clickhouse-connect-arrow", 4, "cold") in keys
    assert ("clickhouse-connect-arrow", 1, "warm") in keys


def test_row_count_check_detects_mismatch():
    ok = [run("a", "clickhouse", "range", [1.0]), run("b", "timescaledb", "range", [1.0])]
    assert check_row_counts(ok) == []
    bad = [
        run("a", "clickhouse", "range", [1.0]),
        run("b", "timescaledb", "range", [1.0], rows=999),
    ]
    bad[1]["fetches"][0]["expected_rows"] = 1_000
    problems = check_row_counts(bad)
    assert any("differ across paths" in p for p in problems)
    assert any("expected 1000" in p for p in problems)


def test_range_queries_have_distinct_windows_and_exact_counts():
    m = make_manifest(rows=10_000, objects=100, span_days=10)
    qs = range_queries(m, 1_000, 4)
    assert len(qs) == 4 and {q.expected_rows for q in qs} == {1_000}
    assert len({q.params["lo"] for q in qs}) == 4


def test_settle_reported_and_warns_when_unsettled():
    s = sample()
    s["meta"]["settle"] = {
        "clickhouse": {"settled": True, "active_parts": 12, "running_merges": 0, "waited_s": 4.0},
        "timescaledb": {"settled": False, "chunks": 40, "running_vacuums": 1, "waited_s": 600.0},
    }
    md = report.render_markdown(s)
    assert "clickhouse settled (12 active parts" in md
    assert "timescaledb NOT settled (40 chunks" in md
    assert "still running when timing started" in md
    assert "still running" not in report.render_markdown(sample())


def test_settled_needs_stable_idle_polls():
    assert not settled([(0, 5), (0, 5)])
    assert not settled([(0, 5), (1, 5), (0, 5)])
    assert not settled([(0, 6), (0, 5), (0, 5)])
    assert settled([(2, 9), (0, 5), (0, 5), (0, 5)])


def _verdict_for(s, path="clickhouse-connect-arrow"):
    md = report.render_markdown(s)
    ln = next(x for x in md.splitlines() if x.startswith("| range |") and f"| {path} |" in x)
    return ln.split("|")[-2].strip()


def test_verdict_invalid_on_cross_db_mismatch():
    s = sample()
    assert _verdict_for(s) == "PASS"
    s["row_count_check"] = {"ok": False, "problems": ["x"]}
    assert _verdict_for(s) == "INVALID"
    assert _verdict_for(s, "adbc-postgresql-arrow") == "INVALID"


def test_verdict_invalid_when_any_fetch_differs_from_expected():
    s = sample()
    s["runs"][0]["fetches"][1]["rows"] -= 1  # a later fetch, not fetches[0]
    assert _verdict_for(s) == "INVALID"
    assert _verdict_for(s, "adbc-postgresql-arrow") == "FAIL"  # other rows unaffected


def test_rows_uses_minimum_across_fetches():
    s = sample()
    s["runs"][0]["fetches"][2]["rows"] = 5
    row = next(r for r in report.summarise(s) if r["path"] == "clickhouse-connect-arrow")
    assert row["rows"] == 5 and row["invalid"]


def test_verdict_annotated_when_db_unsettled():
    s = sample()
    s["meta"]["settle"] = {
        "clickhouse": {"settled": False, "active_parts": 3, "waited_s": 1.0},
        "timescaledb": {"settled": True, "chunks": 3, "waited_s": 1.0},
    }
    assert _verdict_for(s) == "PASS (unsettled)"
    assert _verdict_for(s, "adbc-postgresql-arrow") == "FAIL"


def test_scaled_stays_na_unless_invalid():
    s = sample(target_rows=100_000)
    assert _verdict_for(s) == "n/a (scaled: 100,000 rows)"
    s["row_count_check"] = {"ok": False, "problems": ["x"]}
    assert _verdict_for(s) == "INVALID"


def test_table_size_problems_flags_duplicates_and_short_tables():
    ok = {"clickhouse": {"table": "tle", "row_count": 100}, "timescaledb": {"row_count": 100}}
    assert table_size_problems(ok, 100) == []
    bad = {"clickhouse": {"table": "tle", "row_count": 200}, "timescaledb": {"row_count": 99}}
    problems = table_size_problems(bad, 100)
    assert len(problems) == 2 and "clickhouse" in problems[0] and "200" in problems[0]


def test_plan_load_decisions():
    assert plan_load("t", False, False, False) == "create"
    assert plan_load("t", False, False, True) == "create"
    assert plan_load("t", True, True, False) == "recreate"
    assert plan_load("t", False, True, False) == "recreate"
    assert plan_load("t", True, False, True) == "append"
    with pytest.raises(TableNotEmptyError, match="--recreate"):
        plan_load("t", True, False, False)
    with pytest.raises(ValueError, match="mutually exclusive"):
        plan_load("t", False, True, True)


def test_load_cli_flags_are_mutually_exclusive():
    from tlebench.cli import _build_parser

    p = _build_parser()
    assert p.parse_args(["load", "--append"]).append is True
    with pytest.raises(SystemExit):
        p.parse_args(["load", "--recreate", "--append"])
