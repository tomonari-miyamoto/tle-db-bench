# ClickHouse vs TimescaleDB: TLE bulk retrieval benchmark

Report date: 12 November 2026. This is a snapshot of one run; rerun the benchmark for current numbers.

## Summary

On a 100-million-row table, ClickHouse delivered 10 million rows to a single client in 2.3 s (p95), inside the 5 s target. TimescaleDB's fastest path took 8.4 s (median) in the same run and 5.4–7.1 s in a later rerun, and missed it both times.

- **Bulk time-range fetch (the main query):** ClickHouse was about 4 times faster than TimescaleDB's best client path in the main run, and about 2.5–3 times faster against that path's rerun.
- **Four clients at once:** neither database met 5 s; ClickHouse took 8.2 s median per client and TimescaleDB 14.6 s.
- **Storage and loading:** ClickHouse used 9.9 GB against 16.3 GB, and loaded the data in 3.5 minutes against 10.3 minutes.
- **Single-object history:** TimescaleDB was faster (0.8 s against 3.0 s median).
- **Latest record per object at a point in time:** both were slow (25 s and about 180 s); this query needs a dedicated design on either database.

All numbers come from one laptop with the databases and the client on the same machine. They show the relative behaviour of the two databases, not what the on-premises hardware will deliver. The benchmark is packaged so it can be rerun there; see "How to run the benchmark".

## Workload and target

The benchmark models a store of time-keyed orbital records (TLE-like), hosted on-premises, that feeds a simulation application.

| Item | Assumption |
| --- | --- |
| Table size | Over 100 million records |
| Growth | About 10,000 records per day |
| Dominant query | One time range across all objects, returning about 10 million rows |
| Consumer | A client application that receives the rows for simulation |
| Target | 10 million rows in the client in under 5 s |

The target is measured at the client, after the last row has arrived and been decoded, not at the database.

## What was tested

Both databases held the same 100 million synthetic records and answered the same queries; the data is generated from a fixed seed, so any run can be reproduced exactly.

**Data.** Each record has 11 columns: object ID (`norad_id`), timestamp (`epoch`), the two TLE text lines, and seven orbital elements as floating-point numbers. The dataset covers 30,000 objects over about 10,000 days.

**Table design.**

|  | ClickHouse 25.8 | TimescaleDB 2.22.1 (PostgreSQL 17) |
| --- | --- | --- |
| Table type | MergeTree | Hypertable with columnstore compression |
| Partitioning | Monthly | Monthly chunks |
| Sort order | `epoch`, then `norad_id` | `epoch`, then `norad_id`, no segment-by column |
| After loading | `OPTIMIZE TABLE ... FINAL` | All chunks compressed, then `ANALYZE` |

Both tables are sorted by time first because the dominant query is a time range across all objects.

**Client paths.** The way the client fetches rows matters as much as the database, so three paths were timed:

| Path name in the results | Database | How rows reach the client |
| --- | --- | --- |
| `clickhouse-connect-arrow` | ClickHouse | Official Python client, streaming Apache Arrow batches |
| `adbc-postgresql-arrow` | TimescaleDB | ADBC PostgreSQL driver, Arrow batches over binary COPY |
| `psycopg3-binary-copy` | TimescaleDB | psycopg 3 binary COPY, decoded in Python |

**Queries.**

| Name | What it asks | Rows returned |
| --- | --- | --- |
| `range` (main) | All records in a time window, all objects | 10,000,000 |
| `object` | Full history of one object | 3,336 |
| `asof` | Latest record per object at a given time | 30,000 |

**Measurement.** Each fetch is timed from sending the query to the first batch arriving (time to first batch) and to the last row consumed (time to last row). Each test ran once as warm-up and then five times. The verdict is PASS when the p95 time to last row for 10 million rows is under 5 s. The main query ran with one client and with four clients at once, each fetching its own 10-million-row window.

## Test environment

The run used one laptop for everything: both databases in containers and the benchmark client beside them.

| Item | Value |
| --- | --- |
| Machine | MacBook Air, Apple M5, 10 cores (4 performance, 6 efficiency), 32 GB memory |
| Operating system | macOS 26.7.3 (arm64) |
| Container runtime | OrbStack (Linux VM with 10 CPUs and about 16 GB memory) |
| Limits per database container | 4 CPUs, 8 GB memory, identical for both |
| ClickHouse image | `clickhouse/clickhouse-server:25.8` |
| TimescaleDB image | `timescale/timescaledb:2.22.1-pg17` |
| Network | Loopback only (client and databases on the same machine) |
| Cache state | Warm (each test preceded by one warm-up fetch) |
| Run date | 12 November 2026; about 78 minutes end to end |

## Results

### Main query: 10 million rows in a time range, all objects

ClickHouse with one client is the only combination that met the target.

| Database / client path | Clients | Median (s) | p95 (s) | Rows per second (median) | Under 5 s? |
| --- | --- | --- | --- | --- | --- |
| ClickHouse, Arrow | 1 | 2.15 | 2.30 | 4.6 million | Yes |
| ClickHouse, Arrow | 4 | 8.23 | 9.70 | 1.2 million each | No |
| TimescaleDB, ADBC Arrow | 1 | 8.44 | 15.04 | 1.2 million | No |
| TimescaleDB, ADBC Arrow | 4 | 14.60 | 16.04 | 0.7 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | 25.57 | 25.89 | 0.4 million | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | 94.59 | 116.80 | 0.1 million each | No |

Times are time to last row. Median time to first batch was under 0.2 s on every single-client path, so all three paths stream rather than buffer the whole result. Both databases returned identical row counts.

### Rerun of the TimescaleDB ADBC path

The single-client TimescaleDB ADBC figure above is pessimistic: a rerun of ten fetches took 5.4–7.1 s, about 6 s median.

In the full run, the five fetches took 15.2, 14.4, 8.4, 7.5 and 7.4 s. That test ran after about 19 minutes of TimescaleDB psycopg tests (four-client range, single-object history and latest-per-object); the cause of the two slow fetches is not known. The rerun, started on an idle machine, gave 5.41, 5.43, 5.54, 6.06, 5.80, 6.09, 6.19, 6.33, 7.10 and 6.53 s. Times rose gradually across the ten fetches; the laptop has no fan, so heat throttling is a plausible cause.

Even the fastest rerun fetch (5.4 s) missed the target, by about 0.4 s.

### Loading and storage

|  | ClickHouse | TimescaleDB (columnstore) |
| --- | --- | --- |
| Size on disk, 100 million rows | 9.94 GB | 16.25 GB |
| Insert rate | 979,000 rows/s | 432,000 rows/s |
| Insert time | 102 s | 231 s |
| Post-load step | 99 s (optimize) | 374 s (compression) |
| Total load time | 3.5 min | 10.3 min |

At the expected growth of 10,000 records a day, ingest speed is not a constraint for either database.

### Secondary queries

| Query | Database / client path | Median (s) | p95 (s) |
| --- | --- | --- | --- |
| One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | 0.79 | 1.04 |
| One object's history (3,336 rows) | TimescaleDB, psycopg 3 | 1.36 | 1.64 |
| One object's history (3,336 rows) | ClickHouse, Arrow | 3.02 | 7.40 |
| Latest per object at a time (30,000 rows) | ClickHouse, Arrow | 24.99 | 30.54 |
| Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | 179.37 | 223.41 |
| Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | 226.18 | 236.64 |

Both tables are sorted by time first and have no index on the object ID, so these two queries scan widely on either database. ClickHouse's single-object times also varied a lot between fetches (2.3–8.1 s).

## How to read these results

The ranking for the main query is clear on this machine, but the absolute times should not be carried over to production.

- **Laptop, not target hardware.** The databases ran in a Linux VM on macOS with virtualised disk I/O, capped at 4 CPUs each. Server hardware will change every number.
- **No real network.** Client and databases shared one machine. Ten million rows are about 2 GB once decoded, so on a real network the link may become the limit for both databases.
- **Client and databases competed for the same CPU.** This affects the four-client rows most; they say little about how either database scales on a dedicated server.
- **Warm cache only.** Cold-start fetches were not measured.
- **Synthetic data.** Generated records compress differently from real TLEs. Treat the on-disk sizes as a comparison between the two databases, not as a capacity forecast.
- **Few repetitions.** With five fetches per test, p95 is close to the slowest fetch.
- **The psycopg 3 path is limited by Python.** Its four-client result understates what a multi-process client could do.
- **One table design per database.** Both were tuned for the time-range query. The secondary queries would improve with a different sort order, an index, or a dedicated latest-state table.
- **TimescaleDB is close.** At 5.4 s in its best fetch, it could meet the target on stronger hardware. It should not be ruled out on this run alone.

## How to run the benchmark

The benchmark is a small Python command-line tool, `tlebench`, plus a Docker Compose file that starts both databases. A full 100-million-row run takes about 80 minutes; a 1-million-row smoke run takes a few minutes.

The code is in this repository, hosted privately at https://github.com/tomonari-miyamoto/tle-db-bench; ask the repository owner for access.

### System requirements

| Resource | Full run (100 million rows) | Smoke run (1 million rows) |
| --- | --- | --- |
| CPU | 8 cores or more (4 per database container, plus the client) | 4 cores |
| Memory | 32 GB recommended (8 GB per database container, plus the client) | 16 GB with the default limits; less if MEM_LIMIT and TS_TUNE_MEMORY are lowered in .env (not tested) |
| Free disk | About 80 GB recommended | About 2 GB |
| Time | About 80 minutes | A few minutes |

The full run produced 10.5 GB of generated Parquet files, 9.9 GB in ClickHouse and 16.3 GB in TimescaleDB. The 80 GB figure is an estimate that adds headroom for TimescaleDB's uncompressed data before compression and for ClickHouse's rewrite during optimize; peak disk use was not measured.

The per-container CPU and memory limits are set in `.env` (`CPU_LIMIT`, `MEM_LIMIT`) and apply identically to both databases. On a container runtime that uses a VM (Docker Desktop, OrbStack), give the VM at least 16 GB of memory and 8 CPUs for the default limits.

### Prerequisites

| Software | Version | Purpose |
| --- | --- | --- |
| Docker with Docker Compose | Any recent version | Runs ClickHouse and TimescaleDB |
| Python | 3.11 or later | Runs the benchmark client |
| uv | Any recent version | Installs the Python dependencies |
| git | Any | Fetches the code |

- **Operating system:** tested on macOS (Apple silicon) only. Linux should work with Docker Engine and is the better choice for meaningful numbers; it has not been tried.
- **Internet access** is needed once, to pull the two container images and download the Python packages.
- **Ports:** the databases listen on `127.0.0.1:8123` (ClickHouse) and `127.0.0.1:5433` (TimescaleDB). Both must be free, or changed in `.env`.
- **No database installation is needed** on the host; both run in containers.

### Steps

1. Clone the repository (access required) and enter the folder.

   ```bash
   git clone https://github.com/tomonari-miyamoto/tle-db-bench.git
   cd tle-db-bench
   ```

2. Create the configuration file and set two benchmark-only passwords in it (`CH_PASSWORD`, `PG_PASSWORD`). Do not reuse real passwords.

   ```bash
   cp .env.example .env
   ```

3. Install the Python dependencies.

   ```bash
   uv sync
   ```

4. Start both databases and wait until they are healthy.

   ```bash
   docker compose up -d --wait
   ```

5. Run the smoke test first to confirm everything works.

   ```bash
   uv run tlebench generate --rows 1000000 --out data/smoke
   uv run tlebench load --data data/smoke --recreate
   uv run tlebench run --data data/smoke --out results/smoke.json --reps 3
   uv run tlebench report --results results/smoke.json --out results/smoke.md
   ```

6. Run the full benchmark.

   ```bash
   uv run tlebench generate --rows 100000000 --out data/full
   uv run tlebench load --data data/full --recreate
   uv run tlebench run --data data/full --out results/full.json
   uv run tlebench report --results results/full.json --out results/full.md
   ```

7. Read the report in `results/full.md`. The raw timings are in `results/full.json`.
8. When finished, stop the databases. Add `-v` to also delete the database volumes.

   ```bash
   docker compose down
   ```

### What each step does

| Command | What it does | Time in the full run |
| --- | --- | --- |
| `generate` | Writes the synthetic dataset as Parquet files; the same options always give the same data | About 2 min |
| `load --recreate` | Drops and recreates the tables, loads both databases, then optimizes (ClickHouse) and compresses (TimescaleDB) | About 14 min |
| `run` | Checks row counts, waits for background work to finish, then times every query on every path | About 62 min |
| `report` | Turns the raw results into a Markdown table with PASS/FAIL verdicts | Seconds |

### Things to know

- `load --recreate` drops the benchmark tables on whatever database hosts `.env` points at. Point it only at disposable benchmark databases.
- `load` refuses to load into a table that already has rows unless `--recreate` or `--append` is given, so data is not duplicated by accident.
- `run` stops early if a table's row count does not match the dataset.
- A scaled-down run shows "n/a" instead of PASS/FAIL, because the verdict only applies to 10-million-row fetches.
- `run --paths adbc-postgresql-arrow --concurrency 1 --skip-secondary` reruns a single path when these options are added to the run command in step 6 (use a different output file to keep the earlier results); `--reps` sets the number of fetches.
- `run --cold` restarts the database containers before each fetch. This clears database caches but not the operating system's file cache.
- To test against database servers on other machines, set `CH_HOST` and `PG_HOST` in `.env`. The supplied Compose file publishes both database ports on 127.0.0.1 only, so on the database servers the port bindings must first be opened to the client (or a tunnel used). That is the way to include a real network in the measurement.
- The [README](../README.md) lists all options.

## Recommended next steps

The decision should rest on a rerun on the on-premises hardware, with the client on a separate machine.

1. Rerun the full benchmark on the target servers, with the client on another host over the real network.
2. Find out which queries the simulation application actually needs. If it needs per-object history or latest-state lookups, design and benchmark for those as well.
3. Decide how many clients will fetch at once, and rerun the multi-client test on hardware where the client does not share CPUs with the database.
4. Load a sample of real TLE data to check storage size and compression.
5. Measure cold-cache fetches if the first query after a restart matters.

## Open questions

- What client language and data format will the simulation application use? The fetch path changed TimescaleDB's result by a factor of three to four.
- Is 5 s required for one client or for several at once?
- Should the benchmark repository move from a personal account to an organisation account?
