# TLE bulk retrieval benchmark: ClickHouse vs TimescaleDB

- Created: 2026-11-13T16:04:22.998245+00:00  Host: Linux-7.0.0-1014-aws-x86_64-with-glibc2.39
- Table rows: 100,000,000  Objects: 30,000  Seed: 42  Timescale variant: compressed
- Primary query target rows: 10,000,000  Reps: 5  Warmups: 1
- Target: 10,000,000 rows in the client in under 5 s (verdict = p95 time-to-last-row < 5 s)

Pre-run settle: clickhouse settled (329 active parts, waited 4.0 s); timescaledb settled (334 chunks, waited 4.1 s)

Row-count check across databases: OK

## On-disk size

| DB | Table | Size | Rows |
|---|---|---|---|
| clickhouse | tle | 9.94 GB | 100,000,000 |
| timescaledb | tle_columnstore | 16.25 GB | 100,000,000 |

## Results

| Query | DB / path | Conc | State | Rows | TTFB p50 (s) | Last p50 (s) | Last p95 (s) | Rows/s p50 | MB/s p50 | Est. 10M p95 (s, indicative only) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| range | adbc-postgresql-arrow | 1 | cold | 10,000,000 | 0.408 | 26.818 | 27.079 | 372,878 | 79.8 | - | FAIL |
| range | adbc-postgresql-arrow | 1 | warm | 10,000,000 | 0.218 | 21.772 | 23.734 | 459,307 | 98.3 | - | FAIL |
| range | adbc-postgresql-arrow | 4 | cold | 10,000,000 | 0.419 | 29.704 | 30.370 | 336,658 | 72.0 | - | FAIL |
| range | adbc-postgresql-arrow | 4 | warm | 10,000,000 | 0.255 | 25.407 | 29.109 | 393,643 | 84.2 | - | FAIL |
| range | clickhouse-connect-arrow | 1 | cold | 10,000,000 | 0.060 | 4.904 | 4.976 | 2,039,064 | 436.4 | - | PASS |
| range | clickhouse-connect-arrow | 1 | warm | 10,000,000 | 0.018 | 4.822 | 4.858 | 2,074,026 | 443.8 | - | PASS |
| range | clickhouse-connect-arrow | 4 | cold | 10,000,000 | 0.083 | 9.548 | 12.208 | 1,047,376 | 224.1 | - | FAIL |
| range | clickhouse-connect-arrow | 4 | warm | 10,000,000 | 0.036 | 9.052 | 11.010 | 1,104,727 | 236.4 | - | FAIL |
| range | psycopg3-binary-copy | 1 | cold | 10,000,000 | 0.556 | 43.707 | 45.137 | 228,798 | 49.0 | - | FAIL |
| range | psycopg3-binary-copy | 1 | warm | 10,000,000 | 0.354 | 44.796 | 46.318 | 223,233 | 47.8 | - | FAIL |
| range | psycopg3-binary-copy | 4 | cold | 10,000,000 | 1.423 | 190.854 | 192.288 | 52,396 | 11.2 | - | FAIL |
| range | psycopg3-binary-copy | 4 | warm | 10,000,000 | 1.416 | 191.751 | 193.999 | 52,151 | 11.2 | - | FAIL |
| object | adbc-postgresql-arrow | 1 | cold | 3,336 | 73.815 | 73.815 | 73.952 | 45 | 0.0 | - | n/a |
| object | adbc-postgresql-arrow | 1 | warm | 3,336 | 2.427 | 2.427 | 2.432 | 1,374 | 0.3 | - | n/a |
| object | clickhouse-connect-arrow | 1 | cold | 3,336 | 6.987 | 12.790 | 13.054 | 261 | 0.1 | - | n/a |
| object | clickhouse-connect-arrow | 1 | warm | 3,336 | 0.713 | 2.576 | 2.586 | 1,295 | 0.3 | - | n/a |
| object | psycopg3-binary-copy | 1 | cold | 3,336 | 73.984 | 73.985 | 74.114 | 45 | 0.0 | - | n/a |
| object | psycopg3-binary-copy | 1 | warm | 3,336 | 2.423 | 2.423 | 2.424 | 1,377 | 0.3 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | cold | 30,000 | 304.445 | 304.445 | 305.475 | 99 | 0.0 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | warm | 30,000 | 278.341 | 278.341 | 281.581 | 108 | 0.0 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | cold | 30,000 | 20.601 | 20.676 | 20.737 | 1,451 | 0.3 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | warm | 30,000 | 12.623 | 12.700 | 12.807 | 2,362 | 0.5 | - | n/a |
| asof | psycopg3-binary-copy | 1 | cold | 30,000 | 297.893 | 297.895 | 300.843 | 101 | 0.0 | - | n/a |
| asof | psycopg3-binary-copy | 1 | warm | 30,000 | 275.272 | 275.275 | 276.064 | 109 | 0.0 | - | n/a |

MB/s counts decoded in-memory Arrow bytes. With concurrency > 1 each worker is one sample (one distinct window per worker). p95 over few repetitions approaches the max.
