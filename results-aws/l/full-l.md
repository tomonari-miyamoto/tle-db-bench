# TLE bulk retrieval benchmark: ClickHouse vs TimescaleDB

- Created: 2026-11-13T18:56:07.863892+00:00  Host: Linux-7.0.0-1014-aws-x86_64-with-glibc2.39
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
| range | adbc-postgresql-arrow | 1 | cold | 10,000,000 | 0.392 | 26.171 | 26.689 | 382,096 | 81.8 | - | FAIL |
| range | adbc-postgresql-arrow | 1 | warm | 10,000,000 | 0.210 | 21.188 | 21.270 | 471,957 | 101.0 | - | FAIL |
| range | adbc-postgresql-arrow | 4 | cold | 10,000,000 | 0.385 | 26.762 | 28.265 | 373,663 | 80.0 | - | FAIL |
| range | adbc-postgresql-arrow | 4 | warm | 10,000,000 | 0.231 | 23.542 | 25.787 | 424,787 | 90.9 | - | FAIL |
| range | clickhouse-connect-arrow | 1 | cold | 10,000,000 | 0.065 | 4.225 | 4.510 | 2,366,644 | 506.5 | - | PASS |
| range | clickhouse-connect-arrow | 1 | warm | 10,000,000 | 0.017 | 4.067 | 4.119 | 2,458,590 | 526.1 | - | PASS |
| range | clickhouse-connect-arrow | 4 | cold | 10,000,000 | 0.074 | 7.308 | 9.864 | 1,418,852 | 303.6 | - | FAIL |
| range | clickhouse-connect-arrow | 4 | warm | 10,000,000 | 0.032 | 5.754 | 7.589 | 1,737,789 | 371.9 | - | FAIL |
| range | psycopg3-binary-copy | 1 | cold | 10,000,000 | 0.542 | 43.376 | 43.902 | 230,541 | 49.3 | - | FAIL |
| range | psycopg3-binary-copy | 1 | warm | 10,000,000 | 0.342 | 43.970 | 44.872 | 227,425 | 48.7 | - | FAIL |
| range | psycopg3-binary-copy | 4 | cold | 10,000,000 | 1.491 | 190.057 | 191.954 | 52,616 | 11.3 | - | FAIL |
| range | psycopg3-binary-copy | 4 | warm | 10,000,000 | 1.453 | 191.823 | 195.533 | 52,132 | 11.2 | - | FAIL |
| object | adbc-postgresql-arrow | 1 | cold | 3,336 | 73.414 | 73.414 | 73.547 | 45 | 0.0 | - | n/a |
| object | adbc-postgresql-arrow | 1 | warm | 3,336 | 2.361 | 2.361 | 2.370 | 1,413 | 0.3 | - | n/a |
| object | clickhouse-connect-arrow | 1 | cold | 3,336 | 7.980 | 12.723 | 13.170 | 262 | 0.1 | - | n/a |
| object | clickhouse-connect-arrow | 1 | warm | 3,336 | 0.498 | 1.545 | 1.629 | 2,160 | 0.5 | - | n/a |
| object | psycopg3-binary-copy | 1 | cold | 3,336 | 74.024 | 74.024 | 74.086 | 45 | 0.0 | - | n/a |
| object | psycopg3-binary-copy | 1 | warm | 3,336 | 2.366 | 2.366 | 2.382 | 1,410 | 0.3 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | cold | 30,000 | 192.880 | 192.880 | 197.037 | 156 | 0.0 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | warm | 30,000 | 132.466 | 132.466 | 133.132 | 226 | 0.0 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | cold | 30,000 | 20.444 | 20.510 | 20.813 | 1,463 | 0.3 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | warm | 30,000 | 6.523 | 6.589 | 6.635 | 4,553 | 1.0 | - | n/a |
| asof | psycopg3-binary-copy | 1 | cold | 30,000 | 193.183 | 193.185 | 196.015 | 155 | 0.0 | - | n/a |
| asof | psycopg3-binary-copy | 1 | warm | 30,000 | 132.433 | 132.435 | 132.662 | 227 | 0.0 | - | n/a |

MB/s counts decoded in-memory Arrow bytes. With concurrency > 1 each worker is one sample (one distinct window per worker). p95 over few repetitions approaches the max.
