"""Bulk loaders. Report ingest rows/s over insert time only (Parquet reading excluded)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .config import Settings
from .generator import Manifest, dataset_files
from .schema import CH_TABLE, clickhouse_ddl, pg_table_for, timescale_statements, validate_table

# Default read timeout for the ClickHouse load client, in seconds (override: CH_LOAD_TIMEOUT_S).
CH_LOAD_TIMEOUT_DEFAULT_S = 21600


class TableNotEmptyError(RuntimeError):
    """The target table already holds rows and neither --recreate nor --append was given."""


def plan_load(table: str, has_rows: bool, recreate: bool, append: bool) -> str:
    """Pure load decision: 'recreate', 'append' (into existing rows) or 'create' (empty/absent).

    Raises ValueError if both flags are set and TableNotEmptyError if the table has rows and
    neither flag allows loading into it (a double load silently duplicates the dataset).
    """
    if recreate and append:
        raise ValueError("--recreate and --append are mutually exclusive")
    if recreate:
        return "recreate"
    if has_rows and not append:
        raise TableNotEmptyError(
            f"table {table} already holds rows; pass --recreate to drop it first or --append "
            "to add to it deliberately"
        )
    return "append" if has_rows else "create"


def iter_tables(files: list[Path], batch_rows: int) -> Iterator[pa.Table]:
    for path in files:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_rows):
            yield pa.Table.from_batches([batch])


def _stats(db: str, table: str, rows: int, insert_s: float, wall_s: float, **extra) -> dict:
    return {
        "db": db,
        "table": table,
        "rows": rows,
        "insert_seconds": round(insert_s, 3),
        "ingest_rows_per_s": round(rows / insert_s) if insert_s > 0 else None,
        "wall_seconds": round(wall_s, 3),
        **extra,
    }


def load_clickhouse(
    settings: Settings,
    m: Manifest,
    data_dir: Path | str,
    recreate: bool = False,
    batch_rows: int = 1_000_000,
    optimize: bool = True,
    append: bool = False,
) -> dict:
    import clickhouse_connect

    table = validate_table(CH_TABLE)
    files = dataset_files(m, data_dir)
    client = clickhouse_connect.get_client(
        host=settings.ch_host,
        port=settings.ch_port,
        username=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_database,
        # OPTIMIZE ... FINAL rewrites every partition and blocks until done; at 100M rows
        # it far exceeds clickhouse-connect's default 300 s read timeout.
        send_receive_timeout=int(os.environ.get("CH_LOAD_TIMEOUT_S", CH_LOAD_TIMEOUT_DEFAULT_S)),
    )
    try:
        exists = bool(int(client.command(f"EXISTS TABLE {table}")))
        has_rows = exists and bool(int(client.command(f"SELECT count() > 0 FROM {table}")))
        if plan_load(table, has_rows, recreate, append) == "recreate":
            client.command(f"DROP TABLE IF EXISTS {table}")
        client.command(clickhouse_ddl(table))
        rows = 0
        insert_s = 0.0
        wall0 = time.perf_counter()
        for tbl in iter_tables(files, batch_rows):
            t0 = time.perf_counter()
            client.insert_arrow(table, tbl, settings={"max_partitions_per_insert_block": 5000})
            insert_s += time.perf_counter() - t0
            rows += tbl.num_rows
        post_s = 0.0
        if optimize:
            t0 = time.perf_counter()
            client.command(f"OPTIMIZE TABLE {table} FINAL")
            post_s = time.perf_counter() - t0
        parts = int(
            client.query(
                "SELECT count() FROM system.parts "
                "WHERE database = {db:String} AND table = {t:String} AND active",
                parameters={"db": settings.ch_database, "t": table},
            ).result_rows[0][0]
        )
        return _stats(
            "clickhouse",
            table,
            rows,
            insert_s,
            time.perf_counter() - wall0,
            optimized=optimize,
            optimize_seconds=round(post_s, 3),
            active_parts=parts,
        )
    finally:
        client.close()


def load_timescale(
    settings: Settings,
    m: Manifest,
    data_dir: Path | str,
    variant: str = "compressed",
    recreate: bool = False,
    batch_rows: int = 1_000_000,
    chunk_interval: str = "1 month",
    append: bool = False,
) -> dict:
    import adbc_driver_postgresql.dbapi as adbc_pg
    import psycopg

    table = pg_table_for(variant)
    files = dataset_files(m, data_dir)
    conn_args = {
        "host": settings.pg_host,
        "port": settings.pg_port,
        "user": settings.pg_user,
        "password": settings.pg_password,
        "dbname": settings.pg_database,
    }
    with psycopg.connect(**conn_args, autocommit=True) as ddl:
        exists = ddl.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]
        has_rows = exists and ddl.execute(f"SELECT EXISTS (SELECT 1 FROM {table})").fetchone()[0]
        if plan_load(table, bool(has_rows), recreate, append) == "recreate":
            ddl.execute(f"DROP TABLE IF EXISTS {table}")
        for sql, params in timescale_statements(variant, chunk_interval):
            ddl.execute(sql, params)

    rows = 0
    insert_s = 0.0
    wall0 = time.perf_counter()
    with adbc_pg.connect(settings.pg_uri()) as conn:
        for tbl in iter_tables(files, batch_rows):
            # Binary COPY needs exact types: the table column is int4, Parquet holds uint32.
            tbl = tbl.set_column(0, "norad_id", tbl.column("norad_id").cast(pa.int32()))
            t0 = time.perf_counter()
            with conn.cursor() as cur:
                cur.adbc_ingest(table, tbl, mode="append")
            conn.commit()
            insert_s += time.perf_counter() - t0
            rows += tbl.num_rows

    compress_s = 0.0
    if variant == "compressed":
        t0 = time.perf_counter()
        with psycopg.connect(**conn_args, autocommit=True) as c:
            chunks = [
                r[0]
                for r in c.execute(
                    "SELECT ch::text FROM show_chunks(%s::regclass) ch", (table,)
                ).fetchall()
            ]
            for ch in chunks:
                c.execute("SELECT compress_chunk(%s::regclass, if_not_compressed => true)", (ch,))
        compress_s = time.perf_counter() - t0

    # Put the table in a settled state before any timed read: ANALYZE for planner stats and,
    # for the rowstore, FREEZE so the first scan does not write hint bits and autovacuum has
    # nothing left to do mid-benchmark. VACUUM cannot run in a transaction block (autocommit).
    # `table` comes from the pg_table_for allow-list, so interpolating the identifier is safe.
    maint_sql = (
        f"ANALYZE {table}" if variant == "compressed" else f"VACUUM (ANALYZE, FREEZE) {table}"
    )
    t0 = time.perf_counter()
    with psycopg.connect(**conn_args, autocommit=True) as c:
        c.execute(maint_sql)
    maint_s = time.perf_counter() - t0
    return _stats(
        "timescaledb",
        table,
        rows,
        insert_s,
        time.perf_counter() - wall0,
        variant=variant,
        compress_seconds=round(compress_s, 3),
        maintenance=maint_sql.split(f" {table}")[0],
        maintenance_seconds=round(maint_s, 3),
    )
