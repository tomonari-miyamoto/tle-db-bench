# TLE bulk retrieval benchmark: ClickHouse vs TimescaleDB

- Created: 2026-11-13T08:36:46.644873+00:00  Host: Linux-7.0.0-1014-aws-x86_64-with-glibc2.39
- Table rows: 1,000,000  Objects: 30,000  Seed: 42  Timescale variant: compressed
- Primary query target rows: 100,000  Reps: 3  Warmups: 1
- Target: 10,000,000 rows in the client in under 5 s (verdict = p95 time-to-last-row < 5 s)

> WARNING: this run fetched 100,000 rows per query, fewer than the 10,000,000-row target. No PASS/FAIL verdict is given for scaled rows. The linear 10M estimate is indicative only: it ignores fixed query overhead, cache and working-set effects, chunk/partition counts and the network.

Pre-run settle: clickhouse settled (4 active parts, waited 4.0 s); timescaledb settled (4 chunks, waited 4.0 s)

Row-count check across databases: OK

## On-disk size

| DB | Table | Size | Rows |
|---|---|---|---|
| clickhouse | tle | 99.4 MB | 1,000,000 |
| timescaledb | tle_columnstore | 162.5 MB | 1,000,000 |

## Results

| Query | DB / path | Conc | State | Rows | TTFB p50 (s) | Last p50 (s) | Last p95 (s) | Rows/s p50 | MB/s p50 | Est. 10M p95 (s, indicative only) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| range | adbc-postgresql-arrow | 1 | cold | 100,000 | 0.245 | 0.347 | 0.349 | 287,803 | 61.6 | 34.86 | n/a (scaled: 100,000 rows) |
| range | adbc-postgresql-arrow | 1 | warm | 100,000 | 0.164 | 0.239 | 0.248 | 417,738 | 89.4 | 24.77 | n/a (scaled: 100,000 rows) |
| range | adbc-postgresql-arrow | 4 | cold | 100,000 | 0.325 | 0.474 | 0.517 | 210,965 | 45.1 | 51.73 | n/a (scaled: 100,000 rows) |
| range | adbc-postgresql-arrow | 4 | warm | 100,000 | 0.266 | 0.379 | 0.441 | 264,240 | 56.5 | 44.14 | n/a (scaled: 100,000 rows) |
| range | clickhouse-connect-arrow | 1 | cold | 100,000 | 0.042 | 0.144 | 0.145 | 692,948 | 148.3 | 14.48 | n/a (scaled: 100,000 rows) |
| range | clickhouse-connect-arrow | 1 | warm | 100,000 | 0.012 | 0.085 | 0.088 | 1,175,523 | 251.6 | 8.82 | n/a (scaled: 100,000 rows) |
| range | clickhouse-connect-arrow | 4 | cold | 100,000 | 0.045 | 0.234 | 0.242 | 427,253 | 91.4 | 24.22 | n/a (scaled: 100,000 rows) |
| range | clickhouse-connect-arrow | 4 | warm | 100,000 | 0.019 | 0.182 | 0.191 | 549,940 | 117.7 | 19.12 | n/a (scaled: 100,000 rows) |
| range | psycopg3-binary-copy | 1 | cold | 100,000 | 0.385 | 0.536 | 0.540 | 186,522 | 39.9 | 53.97 | n/a (scaled: 100,000 rows) |
| range | psycopg3-binary-copy | 1 | warm | 100,000 | 0.291 | 0.444 | 0.458 | 225,329 | 48.2 | 45.83 | n/a (scaled: 100,000 rows) |
| range | psycopg3-binary-copy | 4 | cold | 100,000 | 1.319 | 1.895 | 1.991 | 52,837 | 11.3 | 199.05 | n/a (scaled: 100,000 rows) |
| range | psycopg3-binary-copy | 4 | warm | 100,000 | 1.211 | 1.830 | 1.929 | 54,661 | 11.7 | 192.89 | n/a (scaled: 100,000 rows) |
| object | adbc-postgresql-arrow | 1 | cold | 32 | 0.771 | 0.771 | 0.771 | 42 | 0.0 | - | n/a |
| object | adbc-postgresql-arrow | 1 | warm | 32 | 0.036 | 0.036 | 0.036 | 891 | 0.2 | - | n/a |
| object | clickhouse-connect-arrow | 1 | cold | 32 | 0.071 | 0.145 | 0.147 | 220 | 0.0 | - | n/a |
| object | clickhouse-connect-arrow | 1 | warm | 32 | 0.027 | 0.052 | 0.053 | 614 | 0.1 | - | n/a |
| object | psycopg3-binary-copy | 1 | cold | 32 | 0.826 | 0.826 | 0.829 | 39 | 0.0 | - | n/a |
| object | psycopg3-binary-copy | 1 | warm | 32 | 0.036 | 0.036 | 0.037 | 879 | 0.2 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | cold | 30,000 | 1.910 | 1.910 | 1.916 | 15,707 | 3.4 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | warm | 30,000 | 1.377 | 1.377 | 1.401 | 21,788 | 4.7 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | cold | 30,000 | 0.366 | 0.439 | 0.440 | 68,367 | 14.6 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | warm | 30,000 | 0.253 | 0.322 | 0.322 | 93,268 | 20.0 | - | n/a |
| asof | psycopg3-binary-copy | 1 | cold | 30,000 | 1.985 | 1.987 | 1.988 | 15,096 | 3.2 | - | n/a |
| asof | psycopg3-binary-copy | 1 | warm | 30,000 | 1.421 | 1.423 | 1.439 | 21,078 | 4.5 | - | n/a |

MB/s counts decoded in-memory Arrow bytes. With concurrency > 1 each worker is one sample (one distinct window per worker). p95 over few repetitions approaches the max.
