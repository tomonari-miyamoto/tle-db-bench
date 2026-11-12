"""Column definitions and per-database DDL.

Table names are interpolated into SQL only after validation against a fixed allow-list.
"""

from __future__ import annotations

import pyarrow as pa

# (name, arrow type, ClickHouse type, ClickHouse codec, PostgreSQL type)
_COLUMNS: list[tuple[str, pa.DataType, str, str, str]] = [
    ("norad_id", pa.uint32(), "UInt32", "ZSTD(1)", "integer"),
    # Sorted ascending by the primary key, constant stride -> DoubleDelta collapses it.
    (
        "epoch",
        pa.timestamp("us", tz="UTC"),
        "DateTime64(6, 'UTC')",
        "DoubleDelta, ZSTD(1)",
        "timestamptz",
    ),
    # Fixed-width ASCII with a tiny alphabet; ZSTD with a higher level pays off.
    ("line1", pa.string(), "String", "ZSTD(3)", "text"),
    ("line2", pa.string(), "String", "ZSTD(3)", "text"),
    # Near-random doubles: Gorilla/FPC do little; plain ZSTD is the safe choice.
    ("inclination", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
    ("raan", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
    ("eccentricity", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
    ("arg_perigee", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
    ("mean_anomaly", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
    ("mean_motion", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
    ("bstar", pa.float64(), "Float64", "ZSTD(1)", "double precision"),
]

COLUMN_NAMES: list[str] = [c[0] for c in _COLUMNS]
COLUMN_LIST_SQL: str = ", ".join(COLUMN_NAMES)
ARROW_SCHEMA: pa.Schema = pa.schema([(c[0], c[1]) for c in _COLUMNS])

CH_TABLE = "tle"
PG_TABLES = {"compressed": "tle_columnstore", "uncompressed": "tle_rowstore"}
ALLOWED_TABLES = frozenset({CH_TABLE, *PG_TABLES.values()})
VARIANTS = tuple(PG_TABLES)


def validate_table(name: str) -> str:
    """Allow-list check for identifiers that end up inside SQL text."""
    if name not in ALLOWED_TABLES:
        raise ValueError(f"table {name!r} is not in the allow-list {sorted(ALLOWED_TABLES)}")
    return name


def pg_table_for(variant: str) -> str:
    if variant not in PG_TABLES:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
    return PG_TABLES[variant]


def clickhouse_ddl(table: str = CH_TABLE) -> str:
    validate_table(table)
    cols = ",\n".join(f"    {n} {t} CODEC({codec})" for n, _, t, codec, _ in _COLUMNS)
    return (
        f"CREATE TABLE IF NOT EXISTS {table}\n(\n{cols}\n)\n"
        "ENGINE = MergeTree\n"
        "PARTITION BY toYYYYMM(epoch)\n"
        "ORDER BY (epoch, norad_id)"
    )


def timescale_statements(
    variant: str, chunk_interval: str = "1 month"
) -> list[tuple[str, tuple[object, ...]]]:
    """Ordered (sql, params) statements; run each in autocommit mode (psycopg %s style)."""
    table = pg_table_for(variant)
    cols = ",\n".join(
        f"    {n} {t}" + (" NOT NULL" if n in ("norad_id", "epoch") else "")
        for n, _, _, _, t in _COLUMNS
    )
    stmts: list[tuple[str, tuple[object, ...]]] = [
        ("CREATE EXTENSION IF NOT EXISTS timescaledb", ()),
        (f"CREATE TABLE IF NOT EXISTS {table} (\n{cols}\n)", ()),
        (
            "SELECT create_hypertable(%s::regclass, by_range('epoch', %s::interval), "
            "if_not_exists => TRUE)",
            (table, chunk_interval),
        ),
    ]
    if variant == "compressed":
        # Workload: one time range across ALL objects, ~10M rows, delivered to a client.
        # - orderby 'epoch, norad_id': matches the query predicate and the row order the
        #   client wants, so each compressed batch (1000 rows) covers a narrow epoch span
        #   and min/max metadata lets chunk/batch pruning work; it mirrors the ClickHouse
        #   ORDER BY.
        # - segmentby '' (none): segmenting by norad_id would create ~30k segments per
        #   chunk with only a handful of rows each, giving tiny batches, poor compression
        #   and a decompression cost per segment on a scan across all objects. Per-object
        #   history is a secondary query and is allowed to scan.
        stmts.append(
            (
                f"ALTER TABLE {table} SET ("
                "timescaledb.enable_columnstore = true, "
                "timescaledb.segmentby = '', "
                "timescaledb.orderby = 'epoch, norad_id')",
                (),
            )
        )
    return stmts
