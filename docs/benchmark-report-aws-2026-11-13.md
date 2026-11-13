# ClickHouse vs TimescaleDB on AWS: sizing the on-premises TLE server

Report date: 14 November 2026; the runs took place on 13 and 14 November (JST). This run complements the laptop report of 12 November
(`benchmark-report-2026-11-12.md`): same benchmark, same 100-million-row dataset, but the databases
on a dedicated server of known size and the client on a second machine over a real network. Its
purpose is to find the smallest server that meets the target and to turn that into an on-premises
purchase specification.

## Summary

ClickHouse met the target from the second rung up; TimescaleDB met it on none. The recommended
on-premises database server is the third rung's shape: 8 physical cores with high per-core speed,
64 GB of memory, NVMe SSD and 10 GbE to the client. That is the conservative choice; the second rung
(4 cores, 32 GB) also passed, but by 0.02 s on cold fetches.

| Rung | DB host | ClickHouse, 1 client, p95 warm / cold | ClickHouse, 4 clients, p95 warm / cold | TimescaleDB best, 1 client, p95 warm |
| --- | --- | --- | --- | --- |
| S | 4 vCPU (2 cores), 16 GB | 5.77 s / 5.87 s, fail | 19.0 s / 19.7 s, fail | 23.6 s, fail |
| M | 8 vCPU (4 cores), 32 GB | 4.86 s / 4.98 s, pass | 11.0 s / 12.2 s, fail | 23.7 s, fail |
| L | 16 vCPU (8 cores), 64 GB | 4.12 s / 4.51 s, pass | 7.6 s / 9.9 s, fail | 21.3 s, fail |

- **One client is bounded by per-core speed, not core count.** From S to L the ClickHouse host
  went from 2 to 8 cores and the single-client fetch only from 5.8 s to 4.1 s. Rung S's two cores
  were saturated; on M and L no core on either host was, and the fetch sped up only as much as each
  thread got a core of its own. One HTTP stream, one server thread formatting it and one client
  thread receiving it moved 380 (S), 440 (M) and 530 (L) MB/s on these 2.9 GHz cores. The laptop's
  faster cores did the same fetch in 2.15 s. Turning on wire compression changed nothing.
- **Several clients at once scale with cores.** Four concurrent fetches went from 19 s to 7.6 s
  per client across the ladder and were still outside the target on rung L.
- **TimescaleDB's faster path (ADBC) stayed at 21 to 27 s on every rung** for one client, and the
  psycopg path at 43 to 46 s: a PostgreSQL query runs in one backend and decompressing 10 million
  rows from the columnstore keeps it busy that long. This supersedes the laptop report's view that
  TimescaleDB was close to the target; on server cores over a real network it is not.
- **Disk and network were never the limit.** Cold fetches (database restarted and the file cache
  dropped before every fetch) were within 10 percent of warm ones for ClickHouse with one client;
  TimescaleDB's ADBC path and the four-client cases paid 20 to 30 percent. The wire had more than
  twice the headroom one client needs.
- **Storage is as on the laptop**, 9.9 GB against 16.3 GB on disk. A full reload took 6 to 7
  minutes (ClickHouse) against 14 to 16 (TimescaleDB), slower than the laptop on both because the
  loader runs on the client's cores.

## Workload and target

Unchanged from the first report.

| Item | Assumption |
| --- | --- |
| Table size | Over 100 million records |
| Growth | About 10,000 records per day |
| Dominant query | One time range across all objects, returning about 10 million rows |
| Consumer | A client application on another machine that receives the rows for simulation |
| Target | 10 million rows in the client in under 5 s |

The target is measured at the client, after the last row has arrived and been decoded. Ten million
rows decode to 2.14 GB in memory, so the target also implies a wire that can carry at least
3.4 Gbit/s to one client. A 1 GbE link alone would take about 17 s.

## Method: a ladder of server sizes

Instead of one machine, the benchmark ran on a ladder of EC2 instance sizes for the database host,
with everything else held constant. Each rung doubles CPU, memory and network of the previous one.
The client host is the same size on every rung so its decoding cost is the same term in every
measurement. The smallest rung that passes is the sizing result; the rung above it is the safe
option.

| Rung | DB host | vCPU (physical cores) | Memory | Guaranteed network | Container limits per database |
| --- | --- | --- | --- | --- | --- |
| S | m6in.xlarge | 4 (2) | 16 GB | 6.25 Gbit/s | 4 CPUs, 12 GB |
| M | m6in.2xlarge | 8 (4) | 32 GB | 12.5 Gbit/s | 8 CPUs, 24 GB |
| L | m6in.4xlarge | 16 (8) | 64 GB | 25 Gbit/s | 16 CPUs, 48 GB |
| Client (every rung) | m6in.2xlarge | 8 (4) | 32 GB | 12.5 Gbit/s | n/a |

One EC2 vCPU is one hardware thread; two vCPUs share one physical core. The container limits are
caps, not reservations: `run` queries one database at a time, so each database effectively has the
whole host while it is being measured. Changing rung is an in-place resize of the DB host (stop,
change type, start). The data volume survives but the tables are dropped and reloaded on every rung
so the new limits apply from a fresh table.

The `m6in` family was chosen because smaller general-purpose instances (`m7i.xlarge` and the like)
have burst-credit networking whose baseline is below the 3.4 Gbit/s the target needs; `m6in` has a
guaranteed baseline at every size. Both hosts sit in one cluster placement group, which lifts the
per-flow TCP cap from 5 to 10 Gbit/s.

## What was tested

Identical to the first report: the same synthetic 100-million-row dataset (30,000 objects, fixed
seed 42, 11 columns), the same table designs (ClickHouse MergeTree and a TimescaleDB hypertable with
columnstore compression, both sorted by time then object, monthly partitions), the same three
client paths and the same three queries.

| Path name in the results | Database | How rows reach the client |
| --- | --- | --- |
| `clickhouse-connect-arrow` | ClickHouse | Official Python client, streaming Apache Arrow batches |
| `adbc-postgresql-arrow` | TimescaleDB | ADBC PostgreSQL driver, Arrow batches over binary COPY |
| `psycopg3-binary-copy` | TimescaleDB | psycopg 3 binary COPY, decoded in Python |

| Query | What it asks | Rows returned |
| --- | --- | --- |
| `range` (main) | All records in a time window, all objects | 10,000,000 |
| `object` | Full history of one object | 3,336 |
| `asof` | Latest record per object at a given time | 30,000 |

Two things are new in the measurement.

- **Real network.** The client fetches over the VPC network between two hosts, so wire transfer and
  TCP behaviour are inside the timing. The wire ceiling was measured with `iperf3` before each run.
- **Truly cold fetches.** Every test ran in two states. "Warm" is as before (one warm-up fetch, then
  five timed fetches). "Cold" restarts the database container and drops the operating system's file
  cache on the DB host before every timed fetch, over SSM, so the fetch reads from disk. The laptop
  run could not drop the file cache.

Each test is one warm-up plus five timed fetches; the verdict is PASS when the p95 time to last row
for 10 million rows is under 5 s. The main query ran with one client and with four concurrent
clients, each fetching its own 10-million-row window.

## Test environment

| Item | Value |
| --- | --- |
| Region and zone | ap-northeast-1 (Tokyo), one availability zone, one cluster placement group |
| CPU (both hosts) | Intel Xeon Platinum 8375C, 2.9 GHz (Ice Lake), 2 threads per core |
| DB host storage | gp3 EBS, 200 GB, 6,000 IOPS, 400 MB/s provisioned, mounted at `/data` (Docker data root) |
| Client host storage | gp3 EBS, 100 GB, holds the Parquet dataset |
| Operating system | Ubuntu 24.04, kernel 7.0.0-1014-aws |
| Container runtime | Docker 29.9.3, Compose v5.7.1 |
| ClickHouse image | `clickhouse/clickhouse-server:25.8` |
| TimescaleDB image | `timescale/timescaledb:2.22.1-pg17` |
| Client | Python 3.12.3, clickhouse-connect 1.12.0, psycopg 3.3.8, adbc-driver-postgresql 1.13.0, pyarrow 26.0.1 |
| Wire, client to DB host (`iperf3`, 10 s) | 9.53 Gbit/s on one TCP stream (every rung); 29.5 (S), 38.1 (M) and 28.6 (L) Gbit/s on four streams |
| Dates | 13 and 14 November 2026, the three rungs back to back on the same hosts |

One fetch is one TCP connection, so the wire ceiling that matters is 9.53 Gbit/s, which sets a floor
of about 1.8 s for 2.14 GB. Four concurrent clients together can use more.

## Results

### Rung S: m6in.xlarge, 4 vCPU, 16 GB

No path met the target. ClickHouse missed it by less than a second on one client; both TimescaleDB
paths were far from it.

| Database / client path | Clients | State | Median (s) | p95 (s) | Rows per second (median) | Under 5 s? |
| --- | --- | --- | --- | --- | --- | --- |
| ClickHouse, Arrow | 1 | warm | 5.64 | 5.77 | 1.8 million | No |
| ClickHouse, Arrow | 1 | cold | 5.75 | 5.87 | 1.7 million | No |
| ClickHouse, Arrow | 4 | warm | 16.45 | 18.99 | 0.6 million each | No |
| ClickHouse, Arrow | 4 | cold | 16.68 | 19.71 | 0.6 million each | No |
| TimescaleDB, ADBC Arrow | 1 | warm | 23.20 | 23.55 | 0.4 million | No |
| TimescaleDB, ADBC Arrow | 1 | cold | 27.61 | 27.87 | 0.4 million | No |
| TimescaleDB, ADBC Arrow | 4 | warm | 39.43 | 40.10 | 0.3 million each | No |
| TimescaleDB, ADBC Arrow | 4 | cold | 41.76 | 42.23 | 0.2 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | warm | 43.86 | 45.49 | 0.2 million | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | cold | 44.73 | 45.95 | 0.2 million | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | warm | 189.42 | 192.93 | 0.05 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | cold | 189.03 | 191.23 | 0.05 million each | No |

Times are time to last row. Median time to first batch was 0.02 s (ClickHouse) to 0.35 s (psycopg)
on the warm single-client paths, so every path streams the main query. Cold fetches cost only 2 to 20 percent more than
warm on the main query: the query reads 10 million rows from disk either way, and the gp3 volume
kept up.

Where the time went, from CloudWatch CPU utilisation during the run: while the ClickHouse range
tests ran, the DB host was at 95 to 100 percent of its four vCPUs and the client host below 10
percent of its eight. ClickHouse on rung S was limited by the DB host's CPU, not by the network
(the wire would allow 1.8 s) or by the client. The four-client ClickHouse result, at
2.9 times the single-client time on the median, says the same thing: the host had little spare CPU
to give a second client. During the TimescaleDB single-client tests the DB host sat at about 17 percent, one busy
vCPU out of four: a PostgreSQL query runs in one backend process, and decompressing columnstore
chunks for 10 million rows kept that one process busy for 23 to 44 s. More CPUs do not help
that path unless the query is parallelised; four clients did use four backends (ADBC went from 23 to
39 s per client rather than 92 s).

Comparison with the laptop: the same ClickHouse path took 2.15 s (median) on the MacBook Air with a
4-CPU container limit inside a 10-CPU VM on an Apple M5. Rung S also has "4 CPUs", but they are 4
hardware threads on 2 physical Ice Lake cores at 2.9 GHz. The 2.6-fold difference in medians is
about what the core count and per-core speed predict. Physical cores, not threads, are what an
on-premises specification should count.

### Rung M: m6in.2xlarge, 8 vCPU, 32 GB

ClickHouse with one client met the target, with almost no margin on cold fetches. Nothing else did.

| Database / client path | Clients | State | Median (s) | p95 (s) | Rows per second (median) | Under 5 s? |
| --- | --- | --- | --- | --- | --- | --- |
| ClickHouse, Arrow | 1 | warm | 4.82 | 4.86 | 2.1 million | Yes |
| ClickHouse, Arrow | 1 | cold | 4.90 | 4.98 | 2.0 million | Yes, by 0.02 s |
| ClickHouse, Arrow | 4 | warm | 9.05 | 11.01 | 1.1 million each | No |
| ClickHouse, Arrow | 4 | cold | 9.55 | 12.21 | 1.0 million each | No |
| TimescaleDB, ADBC Arrow | 1 | warm | 21.77 | 23.73 | 0.5 million | No |
| TimescaleDB, ADBC Arrow | 1 | cold | 26.82 | 27.08 | 0.4 million | No |
| TimescaleDB, ADBC Arrow | 4 | warm | 25.41 | 29.11 | 0.4 million each | No |
| TimescaleDB, ADBC Arrow | 4 | cold | 29.70 | 30.37 | 0.3 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | warm | 44.80 | 46.32 | 0.2 million | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | cold | 43.71 | 45.14 | 0.2 million | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | warm | 191.75 | 194.00 | 0.05 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | cold | 190.85 | 192.29 | 0.05 million each | No |

Doubling the host changed the two ClickHouse cases differently. Four clients went from 16.5 s to
9.1 s each (the aggregate rate rose from 0.5 to 0.9 GB/s): the extra cores were used. One client
went only from 5.64 s to 4.82 s, a 15 percent gain for twice the cores.

A separate check after the run explains the difference. Five more single-client ClickHouse fetches
(5.0 to 5.1 s, slightly slower than in the run) were timed while `top` sampled both hosts. The DB
host was at about 30 percent of its 8 vCPUs, its busiest ClickHouse thread at 58 percent of one
vCPU; the client process was at 40 percent of one vCPU, its busiest thread at 27 percent. No core on
either side was saturated and the wire has room for 2.5 times the rate. One fetch is one HTTP
connection, and the rate of that pipeline (server-side formatting of the Arrow stream, TCP, client
receive and decode) on these 2.9 GHz cores is about 430 MB/s. Adding cores does not raise it;
faster cores would (the laptop's Apple M5 ran the same path at about 1 GB/s over loopback), and so
would fewer bytes on the wire (the harness supports ClickHouse's transport compression, off in
every run here, and the ClickHouse `Native` format instead of Arrow was not tried).

Single-client TimescaleDB numbers did not move between S and M, as expected for one single-threaded
backend. Its four-client ADBC case improved from 39 to 25 s per client because each backend now had
a core of its own.

### Rung L: m6in.4xlarge, 16 vCPU, 64 GB

ClickHouse with one client passed with a margin of 0.5 s on cold fetches and 0.9 s on warm ones.
Four clients still missed.

| Database / client path | Clients | State | Median (s) | p95 (s) | Rows per second (median) | Under 5 s? |
| --- | --- | --- | --- | --- | --- | --- |
| ClickHouse, Arrow | 1 | warm | 4.07 | 4.12 | 2.5 million | Yes |
| ClickHouse, Arrow | 1 | cold | 4.23 | 4.51 | 2.4 million | Yes |
| ClickHouse, Arrow | 4 | warm | 5.75 | 7.59 | 1.7 million each | No |
| ClickHouse, Arrow | 4 | cold | 7.31 | 9.86 | 1.4 million each | No |
| TimescaleDB, ADBC Arrow | 1 | warm | 21.19 | 21.27 | 0.5 million | No |
| TimescaleDB, ADBC Arrow | 1 | cold | 26.17 | 26.69 | 0.4 million | No |
| TimescaleDB, ADBC Arrow | 4 | warm | 23.54 | 25.79 | 0.4 million each | No |
| TimescaleDB, ADBC Arrow | 4 | cold | 26.76 | 28.27 | 0.4 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | warm | 43.97 | 44.87 | 0.2 million | No |
| TimescaleDB, psycopg 3 binary COPY | 1 | cold | 43.38 | 43.90 | 0.2 million | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | warm | 191.82 | 195.53 | 0.05 million each | No |
| TimescaleDB, psycopg 3 binary COPY | 4 | cold | 190.06 | 191.95 | 0.05 million each | No |

The single-client ClickHouse fetch gained another 15 percent over rung M. Rung L has 8 physical
cores for its 16 vCPUs, so the two to three busy ClickHouse threads no longer share a core with a
sibling thread; this is a per-core-speed gain, not a core-count gain. The same post-run check as
on rung M showed the DB host at 15 percent of 16 vCPUs and the client process at 50 to 60 percent
of one vCPU during a fetch (4.0 to 4.1 s). A second check with ClickHouse wire compression turned
on (`CH_COMPRESS=true`, LZ4 on the HTTP stream) gave 4.02 to 4.08 s, the same as without: the
bytes on the wire are not what limits this path.

Four concurrent ClickHouse clients improved most, from 11.0 s to 7.6 s p95 warm, and the aggregate
rate reached 1.5 GB/s. Each doubling of the host cut the four-client p95 by less than the one before
(19.0, 11.0, 7.6 s), so one more doubling would land near 5 s at best. Four clients inside 5 s is
not something this ladder reached.

TimescaleDB's four-client ADBC case kept improving (25.8 s p95), its single-client cases did not.
The `asof` query on TimescaleDB halved (280 s to 132 s warm), probably because the larger memory
setting changed the query plan (the plan was not captured); it remains far from usable.

### Loading and storage

Sizes are the same as on the laptop (same data, same table designs); load speed depends on the rung.

| Rung | | ClickHouse | TimescaleDB (columnstore) |
| --- | --- | --- | --- |
| any | Size on disk, 100 million rows | 9.94 GB | 16.25 GB |
| S | Insert rate | 436,000 rows/s | 191,000 rows/s |
| S | Insert, then post-load step | 229 s, then 165 s (optimize) | 525 s, then 384 s (compression) |
| S | Total load time | 6.9 min | 15.5 min |
| M | Insert rate | 499,000 rows/s | 195,000 rows/s |
| M | Insert, then post-load step | 201 s, then 157 s (optimize) | 513 s, then 336 s (compression) |
| M | Total load time | 6.2 min | 14.5 min |
| L | Insert rate | 517,000 rows/s | 199,000 rows/s |
| L | Insert, then post-load step | 193 s, then 148 s (optimize) | 503 s, then 304 s (compression) |
| L | Total load time | 6.0 min | 13.8 min |

Loading barely scales with the host because the client generates the batches from Parquet files and
sends them over one connection; the laptop's faster cores loaded ClickHouse twice as fast.

At 10,000 new records a day, ingest speed is irrelevant to the choice of server.

### Secondary queries

| Rung | Query | Database / client path | State | Median (s) | p95 (s) |
| --- | --- | --- | --- | --- | --- |
| S | One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | warm | 2.47 | 2.48 |
| S | One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | cold | 73.87 | 74.08 |
| S | One object's history (3,336 rows) | TimescaleDB, psycopg 3 | warm | 2.47 | 2.53 |
| S | One object's history (3,336 rows) | TimescaleDB, psycopg 3 | cold | 73.90 | 73.93 |
| S | One object's history (3,336 rows) | ClickHouse, Arrow | warm | 4.48 | 4.67 |
| S | One object's history (3,336 rows) | ClickHouse, Arrow | cold | 11.79 | 13.36 |
| S | Latest per object at a time (30,000 rows) | ClickHouse, Arrow | warm | 23.95 | 24.09 |
| S | Latest per object at a time (30,000 rows) | ClickHouse, Arrow | cold | 28.09 | 28.22 |
| S | Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | warm | 305.82 | 309.01 |
| S | Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | cold | 321.72 | 325.44 |
| S | Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | warm | 306.90 | 308.06 |
| S | Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | cold | 313.72 | 323.80 |
| M | One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | warm | 2.43 | 2.43 |
| M | One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | cold | 73.82 | 73.95 |
| M | One object's history (3,336 rows) | TimescaleDB, psycopg 3 | warm | 2.42 | 2.42 |
| M | One object's history (3,336 rows) | TimescaleDB, psycopg 3 | cold | 73.98 | 74.11 |
| M | One object's history (3,336 rows) | ClickHouse, Arrow | warm | 2.58 | 2.59 |
| M | One object's history (3,336 rows) | ClickHouse, Arrow | cold | 12.79 | 13.05 |
| M | Latest per object at a time (30,000 rows) | ClickHouse, Arrow | warm | 12.70 | 12.81 |
| M | Latest per object at a time (30,000 rows) | ClickHouse, Arrow | cold | 20.68 | 20.74 |
| M | Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | warm | 278.34 | 281.58 |
| M | Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | cold | 304.45 | 305.48 |
| M | Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | warm | 275.28 | 276.06 |
| M | Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | cold | 297.89 | 300.84 |
| L | One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | warm | 2.36 | 2.37 |
| L | One object's history (3,336 rows) | TimescaleDB, ADBC Arrow | cold | 73.41 | 73.55 |
| L | One object's history (3,336 rows) | TimescaleDB, psycopg 3 | warm | 2.37 | 2.38 |
| L | One object's history (3,336 rows) | TimescaleDB, psycopg 3 | cold | 74.02 | 74.09 |
| L | One object's history (3,336 rows) | ClickHouse, Arrow | warm | 1.55 | 1.63 |
| L | One object's history (3,336 rows) | ClickHouse, Arrow | cold | 12.72 | 13.17 |
| L | Latest per object at a time (30,000 rows) | ClickHouse, Arrow | warm | 6.59 | 6.64 |
| L | Latest per object at a time (30,000 rows) | ClickHouse, Arrow | cold | 20.51 | 20.81 |
| L | Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | warm | 132.47 | 133.13 |
| L | Latest per object at a time (30,000 rows) | TimescaleDB, ADBC Arrow | cold | 192.88 | 197.04 |
| L | Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | warm | 132.43 | 132.66 |
| L | Latest per object at a time (30,000 rows) | TimescaleDB, psycopg 3 | cold | 193.18 | 196.02 |

Here the cold state matters: TimescaleDB's single-object query reads one object out of every
monthly chunk, which is fast from the page cache (2.5 s) and takes 74 s from disk. Both tables are
sorted by time first with no index on the object ID, so these queries are wide scans on either
database, as in the first report. They need their own index or table design if the application
needs them; the server size does not fix them.

## Recommended on-premises specification

The smallest rung that passed is M, but its cold-fetch margin (0.02 s) is inside the run-to-run
noise: five extra fetches on the same host right after the run took 5.0 to 5.1 s. Rung L passed
with a margin of 0.5 s cold and 0.9 s warm. A conservative, low-budget specification is therefore
rung L translated to a physical server, with one adjustment: prefer per-core speed over core
count, because that is what the single-client path responds to.

| Component | Specification | Why |
| --- | --- | --- |
| Database | ClickHouse | The only database that met the target on any rung; TimescaleDB's best single-client time was 21 s |
| CPU | 8 physical cores (16 threads), current-generation x86 server part, highest per-core clock available in the budget (3.5 GHz or more sustained) | Rung L is 8 Ice Lake cores at 2.9 GHz and passed with 0.5 s to spare; the single-client fetch scales with per-core speed and a 2.9 GHz part is slow by today's standard. More cores only help concurrent clients |
| Memory | 64 GB | Matches rung L. ClickHouse showed about 1.4 GB resident in `top` during fetches; the rest is file cache, which the cold results show is not needed for the main query but takes the single-object query from 74 s to 2 s |
| Storage | NVMe SSD, 1 TB, with a second drive or RAID 1 if the data must survive a disk failure | The gp3 volume (6,000 IOPS, 400 MB/s) was never the limit: single-client ClickHouse cold fetches read the whole window from disk within 10 percent of warm. Any data-centre NVMe drive exceeds those figures several times. The working set is 10 GB (ClickHouse) and grows about 0.4 GB a year at 10,000 rows a day; 1 TB leaves room for reloads, which double the footprint temporarily, and for a TimescaleDB instance if it is kept |
| Network | 10 GbE on the server and on the client host, on the same switch | One fetch is one TCP flow carrying 2.1 GB; 5 s needs 3.4 Gbit/s sustained and the measured path used 4.2 Gbit/s on rung L. 1 GbE cannot meet the target (17 s for the transfer alone) |
| Client host | Any current 4-core machine with 16 GB of memory and 10 GbE | The client process used 50 to 60 percent of one core and holds the 2.1 GB result in memory. Its per-core speed matters as much as the server's |

**Safe option.** If more than one application instance will fetch at the same time, or if the
target must hold with headroom for growth, specify 16 physical cores, 128 GB and a 25 GbE port on
the server (four clients each receiving 2.1 GB in 5 s need 13.7 Gbit/s at the server, more than
10 GbE carries). Even that is expected to land near 5 s for four clients rather than comfortably
under it: each doubling of the host cut the four-client p95 by less than the one before (19.0,
11.0, 7.6 s). This is extrapolated, not measured.

**What would change the picture.** A faster-clocked CPU could make rung M's shape (4 cores, 32 GB)
sufficient: the laptop did the same fetch in 2.15 s with a 4-CPU limit on an Apple M5. If budget is tight, a
4-core server with the fastest available cores is a reasonable bet for a single client, but it
should be verified by rerunning this benchmark on the delivered hardware before go-live. The
harness is unchanged and the laptop report describes the procedure.

## How to read these results

- **Cloud instance, not the final server.** The rungs are a way to measure how the benchmark
  scales with cores, memory and network. An on-premises server with the same physical core count
  and a faster clock should do at least as well; one with fewer cores or a slower disk may not.
- **Threads versus cores.** All vCPU counts here are hardware threads. Rung S is a 2-core machine.
- **CPU utilisation figures** in the text come from CloudWatch's 5-minute `CPUUtilization` metric
  and from `top` samples taken over SSM during the post-run checks. They are not in the results
  files.
- **Cold means cold.** Cold fetches restarted the database and dropped the operating system's file
  cache before every fetch. In production the first fetch after a restart looks like the cold
  numbers; every later one like the warm numbers.
- **Few repetitions.** Five fetches per test, so p95 is close to the slowest fetch.
- **The psycopg 3 path is limited by Python**, as before; its four-client numbers say nothing about
  the server.
- **Secondary queries are design problems, not sizing problems.** ClickHouse's `asof` did improve
  with memory and cores (24 s to 6.6 s warm), but a latest-state table would make it milliseconds.
- **Rung M's pass is marginal.** Its cold p95 of 4.98 s is within noise of the target; do not size
  from it without a faster CPU than the one measured here.
- **Synthetic data.** Treat on-disk sizes as a comparison between databases, not a capacity forecast.
- **Log noise.** The run log contains "Unexpected Http Driver Exception" lines from the ClickHouse
  client. They come from the connect-wait probe that polls the server after each cold restart until
  it answers, and every such line is followed by a normal timed fetch. They are not failures.
- **Not verified in this run:** that the database ports are unreachable from the internet. The
  security groups only admit the client host's security group and were reviewed, but the negative
  check from outside the VPC was not executed.

## How to run the benchmark on AWS

The repository now contains `deploy/aws/` (Terraform) with a README that gives the per-rung
procedure: `terraform apply -var-file=rungs/<rung>.tfvars` creates or resizes the two hosts; code
and `.env` files reach the hosts through an S3 bucket; commands run over SSM (no SSH); results are
uploaded to the same bucket. The harness itself gained two settings for this: `BIND_ADDR` (publish
the database ports on an interface other than loopback) and `COLD_RESTART_CMD` (an external command
that restarts a database and drops caches on the remote host, used by `run --cold`). The laptop
procedure in the first report is unchanged.

Timing per rung: generate 5 min (once), load 20 to 22 min, run with cold restarts 2 h 20 min (L)
to 3 h 20 min (S); the long tail is TimescaleDB's `asof` query at 2 to 5 min per fetch.

Cost: at Tokyo on-demand list prices (USD 0.36, 0.72 and 1.43 per hour for the three DB sizes,
0.72 for the client) the three rungs took about 11 hours of client time and 4, 3.6 and 3 hours of DB
time, roughly USD 16 of compute plus about USD 1 a day of EBS. Cost Explorer had not yet reported
the account when this was written; `deploy/aws/scripts/cost.sh` gives the actual figure a day
later.

## Open questions

- Which queries does the simulation application actually need? The secondary queries would change
  the table design, and possibly the database choice.
- Is the target for one client, or for several at once? Four concurrent clients took 1.8 to 3.3
  times as long per client as one, depending on the rung, and did not reach 5 s on any.
- Will the application fetch through Arrow? The TimescaleDB ADBC path is about twice as fast as
  psycopg, and the ClickHouse Arrow path is the only one near the target at all.
