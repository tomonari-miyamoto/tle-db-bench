# TLE bulk retrieval benchmark: ClickHouse vs TimescaleDB

- Created: 2026-11-13T12:30:26.538052+00:00  Host: Linux-7.0.0-1014-aws-x86_64-with-glibc2.39
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
| range | adbc-postgresql-arrow | 1 | cold | 10,000,000 | 0.393 | 27.606 | 27.872 | 362,238 | 77.5 | - | FAIL |
| range | adbc-postgresql-arrow | 1 | warm | 10,000,000 | 0.224 | 23.199 | 23.554 | 431,048 | 92.2 | - | FAIL |
| range | adbc-postgresql-arrow | 4 | cold | 10,000,000 | 0.499 | 41.761 | 42.234 | 239,456 | 51.2 | - | FAIL |
| range | adbc-postgresql-arrow | 4 | warm | 10,000,000 | 0.386 | 39.429 | 40.098 | 253,619 | 54.3 | - | FAIL |
| range | clickhouse-connect-arrow | 1 | cold | 10,000,000 | 0.061 | 5.753 | 5.872 | 1,738,283 | 372.0 | - | FAIL |
| range | clickhouse-connect-arrow | 1 | warm | 10,000,000 | 0.019 | 5.643 | 5.772 | 1,771,956 | 379.2 | - | FAIL |
| range | clickhouse-connect-arrow | 4 | cold | 10,000,000 | 0.090 | 16.676 | 19.711 | 599,671 | 128.3 | - | FAIL |
| range | clickhouse-connect-arrow | 4 | warm | 10,000,000 | 0.050 | 16.453 | 18.994 | 607,790 | 130.1 | - | FAIL |
| range | psycopg3-binary-copy | 1 | cold | 10,000,000 | 0.548 | 44.731 | 45.945 | 223,561 | 47.8 | - | FAIL |
| range | psycopg3-binary-copy | 1 | warm | 10,000,000 | 0.341 | 43.863 | 45.492 | 227,983 | 48.8 | - | FAIL |
| range | psycopg3-binary-copy | 4 | cold | 10,000,000 | 1.520 | 189.027 | 191.231 | 52,904 | 11.3 | - | FAIL |
| range | psycopg3-binary-copy | 4 | warm | 10,000,000 | 1.034 | 189.421 | 192.927 | 52,793 | 11.3 | - | FAIL |
| object | adbc-postgresql-arrow | 1 | cold | 3,336 | 73.872 | 73.873 | 74.077 | 45 | 0.0 | - | n/a |
| object | adbc-postgresql-arrow | 1 | warm | 3,336 | 2.468 | 2.468 | 2.476 | 1,352 | 0.3 | - | n/a |
| object | clickhouse-connect-arrow | 1 | cold | 3,336 | 4.086 | 11.789 | 13.360 | 283 | 0.1 | - | n/a |
| object | clickhouse-connect-arrow | 1 | warm | 3,336 | 1.305 | 4.479 | 4.667 | 745 | 0.2 | - | n/a |
| object | psycopg3-binary-copy | 1 | cold | 3,336 | 73.901 | 73.901 | 73.926 | 45 | 0.0 | - | n/a |
| object | psycopg3-binary-copy | 1 | warm | 3,336 | 2.472 | 2.472 | 2.525 | 1,349 | 0.3 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | cold | 30,000 | 321.721 | 321.721 | 325.441 | 93 | 0.0 | - | n/a |
| asof | adbc-postgresql-arrow | 1 | warm | 30,000 | 305.817 | 305.817 | 309.014 | 98 | 0.0 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | cold | 30,000 | 28.028 | 28.093 | 28.223 | 1,068 | 0.2 | - | n/a |
| asof | clickhouse-connect-arrow | 1 | warm | 30,000 | 23.879 | 23.948 | 24.088 | 1,253 | 0.3 | - | n/a |
| asof | psycopg3-binary-copy | 1 | cold | 30,000 | 313.721 | 313.724 | 323.800 | 96 | 0.0 | - | n/a |
| asof | psycopg3-binary-copy | 1 | warm | 30,000 | 306.896 | 306.898 | 308.062 | 98 | 0.0 | - | n/a |

MB/s counts decoded in-memory Arrow bytes. With concurrency > 1 each worker is one sample (one distinct window per worker). p95 over few repetitions approaches the max.
