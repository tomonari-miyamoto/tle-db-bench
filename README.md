# tlebench

Benchmark harness comparing ClickHouse and TimescaleDB for bulk time-range retrieval of
TLE-like records (>= 100M rows, ~10k rows/day growth). Dominant query: one time range across
all objects returning ~10M rows to a client. Target: 10M rows in the client in under 5 s.

Fetch paths compared: ClickHouse via `clickhouse-connect` Arrow streaming; TimescaleDB via
`psycopg` 3 binary COPY (decoded in Python, batched to Arrow) and via the ADBC PostgreSQL
driver (Arrow). Secondary queries: single-object history and latest-per-object as of T.

## Setup

```bash
cp .env.example .env          # edit passwords and CPU_LIMIT / MEM_LIMIT
uv sync
docker compose up -d --wait   # ClickHouse + TimescaleDB, identical limits, healthchecked
```

Credentials are read from `.env` / the environment only. Image tags are pinned in
`docker-compose.yml`; confirm they exist in your registry before the first pull.

## 1M-row smoke run

```bash
uv run tlebench generate --rows 1000000 --out data/smoke
uv run tlebench load --data data/smoke --recreate
uv run tlebench run --data data/smoke --out results/smoke.json --reps 3
uv run tlebench report --results results/smoke.json --out results/smoke.md
```

## 100M-row full run

```bash
uv run tlebench generate --rows 100000000 --out data/full      # 100 Parquet files, ~10000 days
uv run tlebench load --data data/full --recreate               # prints ingest rows/s per DB
uv run tlebench run --data data/full --out results/full.json   # 10M-row windows, reps 5, c=1,4
uv run tlebench report --results results/full.json --out results/full.md
```

Useful options:

- `generate`: `--seed`, `--objects` (default 30000), `--span-days` (default rows / 10000),
  `--start`, `--chunk-rows`. Output is deterministic for a given option set.
- `load`: `--db clickhouse|timescaledb|both`, `--variant compressed|uncompressed` (TimescaleDB
  columnstore vs plain rowstore, separate tables so both can coexist), `--no-optimize`,
  `--chunk-interval`, `--recreate` / `--append`. `load` refuses (exit 2) to load into a table
  that already holds rows, since a second load silently duplicates the dataset; pass
  `--recreate` to drop and reload, or `--append` to add rows deliberately (mutually exclusive).
  Load stats are written to `results/load_*.json` and folded into the run.
  Post-load state is made comparable by default: ClickHouse runs `OPTIMIZE TABLE ... FINAL`
  (opt out with `--no-optimize`), TimescaleDB chunks are compressed and `ANALYZE`d
  (columnstore) or `VACUUM (ANALYZE, FREEZE)`d (rowstore).
- `run`: `--target-rows` (default 10% of the table), `--reps`, `--warmups`,
  `--concurrency 1,4`, `--paths`, `--variant`, `--skip-secondary`, `--cold`,
  `--settle-timeout`. Before timing, `run` waits until ClickHouse has no running merges and a
  stable active part count, and no (auto)vacuum/analyze runs on the hypertable; the part/chunk
  count and a settled flag are recorded in `meta.settle` and shown in the report.
  Before settling or timing, `run` checks each table's row count against the dataset manifest
  and aborts with exit code 3 on a mismatch (duplicate or partial load); reload with
  `load --recreate`. Exit code 2 if row counts differ between databases or from the expected
  window size.

Window sizing is exact and needs no data scan: epochs sit on an integer grid
(`start + floor(i * span / rows)`), so a window of k rows is computed arithmetically.
With concurrency N each worker gets its own distinct window.

## Cold runs (optional)

`--cold` restarts the database container (`docker compose restart <service>`) before each cold
repetition and waits until it accepts connections. This clears database caches only; it does
NOT drop the OS page cache. On a Linux host, drop it explicitly (`sync; echo 3 >
/proc/sys/vm/drop_caches`, root) between reps if you need truly cold numbers.

## Timings

Each fetch is timed from query issue to (a) the first batch in the client and (b) the last row
consumed. MB/s uses decoded in-memory Arrow bytes. Rows are consumed as columnar batches and
discarded. ClickHouse (Arrow stream) and psycopg (65,536-row batches) hold a bounded number of
rows in the client. ADBC is bounded only if the driver streams: it does so via COPY when the
query has no bound parameters, so the ADBC path embeds window bounds and `norad_id` as SQL
literals built from validated ints (the other paths use bound parameters). With parameters the
driver buffers the whole result, which shows up as time-to-first-batch about equal to
time-to-last-row; check that TTFB is clearly below Last in the report. Concurrent workers are threads, one connection each;
the psycopg path is GIL-bound so its concurrency numbers understate a multi-process client.

## Schema notes

- ClickHouse: MergeTree, `PARTITION BY toYYYYMM(epoch)`, `ORDER BY (epoch, norad_id)`,
  per-column codecs (DoubleDelta+ZSTD on epoch, ZSTD(3) on TLE lines, ZSTD(1) elsewhere).
- TimescaleDB: hypertable on `epoch` (1 month chunks), columnstore with `orderby = epoch,
  norad_id` and no `segmentby` (rationale in `src/tlebench/schema.py`). No secondary index, to
  mirror ClickHouse's single sort key; single-object history therefore scans.

## Caveats

- Measure on the target on-prem hardware. Numbers from a laptop are not predictive.
- Put client and server on a realistic network. A loopback test hides the wire, which is
  usually the bottleneck for 10M rows (~2 GB decoded).
- Docker Desktop / OrbStack on macOS runs a Linux VM with virtualised file I/O and is not
  representative of bare-metal storage or networking.
- `CPU_LIMIT` / `MEM_LIMIT` are applied identically to both containers; tune each engine
  (cache sizes, parallelism) separately if the production config differs.
- `CH_COMPRESS` toggles clickhouse-connect wire compression (default off); set it to match the
  production network assumptions.

## Development

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Unit tests need no Docker.

The report marks a row `INVALID` instead of PASS/FAIL when the cross-database row-count check
is MISMATCH or any fetch returned a count different from expected, and appends `(unsettled)` to
a verdict when that row's database was not settled before timing. Rows shows the minimum count
across fetches.
