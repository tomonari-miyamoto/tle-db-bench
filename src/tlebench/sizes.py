"""On-disk size, row counts and pre-benchmark settle checks per database."""

from __future__ import annotations

import time

from .config import Settings
from .schema import CH_TABLE, validate_table


def clickhouse_size(settings: Settings, table: str = CH_TABLE) -> dict:
    import clickhouse_connect

    validate_table(table)
    client = clickhouse_connect.get_client(
        host=settings.ch_host,
        port=settings.ch_port,
        username=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_database,
    )
    try:
        res = client.query(
            "SELECT sum(bytes_on_disk), sum(data_uncompressed_bytes), sum(rows) "
            "FROM system.parts WHERE database = {db:String} AND table = {t:String} AND active",
            parameters={"db": settings.ch_database, "t": table},
        )
        disk, raw, rows = (int(v or 0) for v in res.result_rows[0])
        parts = _ch_active_parts(client, settings.ch_database, table)
        count = int(client.query(f"SELECT count() FROM {table}").result_rows[0][0])
        return {
            "table": table,
            "bytes_on_disk": disk,
            "uncompressed_bytes": raw,
            "parts_rows": rows,
            "active_parts": parts,
            "row_count": count,
        }
    finally:
        client.close()


def timescale_size(settings: Settings, table: str) -> dict:
    import psycopg

    validate_table(table)
    with psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_database,
        autocommit=True,
    ) as conn:
        disk = conn.execute("SELECT hypertable_size(%s::regclass)", (table,)).fetchone()[0]
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return {"table": table, "bytes_on_disk": int(disk), "row_count": int(count)}


def _ch_active_parts(client, db: str, table: str) -> int:
    return int(
        client.query(
            "SELECT count() FROM system.parts WHERE database = {db:String} AND table = {t:String} "
            "AND active",
            parameters={"db": db, "t": table},
        ).result_rows[0][0]
    )


def settled(samples: list[tuple[int, int]], stable_polls: int = 3) -> bool:
    """True when the last `stable_polls` (busy, parts) samples show no work and equal parts."""
    if len(samples) < stable_polls:
        return False
    tail = samples[-stable_polls:]
    return all(busy == 0 for busy, _ in tail) and len({parts for _, parts in tail}) == 1


def clickhouse_settle(
    settings: Settings, table: str = CH_TABLE, timeout_s: float = 600.0, poll_s: float = 2.0
) -> dict:
    """Wait until no merge/mutation runs on the table and the active part count is stable."""
    import clickhouse_connect

    validate_table(table)
    client = clickhouse_connect.get_client(
        host=settings.ch_host,
        port=settings.ch_port,
        username=settings.ch_user,
        password=settings.ch_password,
        database=settings.ch_database,
    )
    params = {"db": settings.ch_database, "t": table}
    samples: list[tuple[int, int]] = []
    t0 = time.monotonic()
    try:
        while True:
            busy = int(
                client.query(
                    "SELECT (SELECT count() FROM system.merges WHERE database = {db:String} "
                    "AND table = {t:String}) + (SELECT count() FROM system.mutations "
                    "WHERE database = {db:String} AND table = {t:String} AND NOT is_done)",
                    parameters=params,
                ).result_rows[0][0]
            )
            samples.append((busy, _ch_active_parts(client, settings.ch_database, table)))
            ok = settled(samples)
            if ok or time.monotonic() - t0 > timeout_s:
                break
            time.sleep(poll_s)
    finally:
        client.close()
    return {
        "settled": ok,
        "active_parts": samples[-1][1],
        "running_merges": samples[-1][0],
        "waited_s": round(time.monotonic() - t0, 1),
    }


def timescale_settle(
    settings: Settings, table: str, timeout_s: float = 600.0, poll_s: float = 2.0
) -> dict:
    """Wait until no (auto)vacuum/analyze runs on the hypertable or any of its chunks."""
    import psycopg

    validate_table(table)
    samples: list[tuple[int, int]] = []
    t0 = time.monotonic()
    with psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_database,
        autocommit=True,
    ) as conn:
        chunk_sql = "SELECT count(*) FROM show_chunks(%s::regclass)"
        busy_sql = (
            "WITH rels AS (SELECT %s::regclass::oid AS oid "
            "UNION ALL SELECT c::regclass::oid FROM show_chunks(%s::regclass) c) "
            "SELECT (SELECT count(*) FROM pg_stat_progress_vacuum v JOIN rels r ON v.relid = r.oid)"
            " + (SELECT count(*) FROM pg_stat_progress_analyze a JOIN rels r ON a.relid = r.oid)"
        )
        while True:
            busy = int(conn.execute(busy_sql, (table, table)).fetchone()[0])
            chunks = int(conn.execute(chunk_sql, (table,)).fetchone()[0])
            samples.append((busy, chunks))
            ok = settled(samples)
            if ok or time.monotonic() - t0 > timeout_s:
                break
            time.sleep(poll_s)
    return {
        "settled": ok,
        "chunks": samples[-1][1],
        "running_vacuums": samples[-1][0],
        "waited_s": round(time.monotonic() - t0, 1),
    }
