"""Client fetch paths. Each returns timing and volume for one query, rows kept columnar."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

import pyarrow as pa

from .config import Settings
from .queries import Query, adbc_sql, clickhouse_sql, postgres_sql
from .schema import ARROW_SCHEMA, CH_TABLE

PSYCOPG_BATCH_ROWS = 65_536
# psycopg binary COPY type names, in ARROW_SCHEMA column order.
_PG_COPY_TYPES = ["int4", "timestamptz", "text", "text"] + ["float8"] * 7


@dataclass
class FetchResult:
    rows: int
    nbytes: int  # in-memory Arrow bytes received by the client (decoded size)
    ttfb_s: float  # query issued -> first batch available in the client
    ttlr_s: float  # query issued -> last row consumed
    window_id: int = 0

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def consume(batches: Iterable[pa.RecordBatch], t0: float) -> FetchResult:
    """Drain batches, timing the first one and the end. Batches are dropped after counting."""
    rows = nbytes = 0
    ttfb: float | None = None
    for batch in batches:
        if ttfb is None:
            ttfb = time.perf_counter() - t0
        rows += batch.num_rows
        nbytes += batch.nbytes
    end = time.perf_counter() - t0
    return FetchResult(rows, nbytes, end if ttfb is None else ttfb, end)


class BaseFetcher:
    db = ""
    path = ""

    def connect(self) -> None:
        raise NotImplementedError

    def fetch(self, q: Query) -> FetchResult:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ClickHouseArrow(BaseFetcher):
    db = "clickhouse"
    path = "clickhouse-connect-arrow"

    def __init__(self, settings: Settings, table: str = CH_TABLE):
        self.s, self.table, self.client = settings, table, None

    def connect(self) -> None:
        import clickhouse_connect

        self.client = clickhouse_connect.get_client(
            host=self.s.ch_host,
            port=self.s.ch_port,
            username=self.s.ch_user,
            password=self.s.ch_password,
            database=self.s.ch_database,
            compress=self.s.ch_compress,
        )
        self.client.command("SELECT 1")

    def fetch(self, q: Query) -> FetchResult:
        sql, params = clickhouse_sql(q, self.table)
        t0 = time.perf_counter()
        with self.client.query_arrow_stream(sql, parameters=params) as stream:
            res = consume(stream, t0)
        res.window_id = q.window_id
        return res

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


class PsycopgBinaryCopy(BaseFetcher):
    """COPY (SELECT ...) TO STDOUT (FORMAT BINARY), decoded by psycopg and batched to Arrow.

    Row decoding happens in Python objects, so this path is expected to be CPU bound on the
    client; that is the honest cost of getting columnar data out of psycopg3.
    """

    db = "timescaledb"
    path = "psycopg3-binary-copy"

    def __init__(self, settings: Settings, table: str):
        self.s, self.table, self.conn = settings, table, None

    def connect(self) -> None:
        import psycopg

        self.conn = psycopg.connect(
            host=self.s.pg_host,
            port=self.s.pg_port,
            user=self.s.pg_user,
            password=self.s.pg_password,
            dbname=self.s.pg_database,
            autocommit=True,
        )

    def _batches(self, copy) -> Iterable[pa.RecordBatch]:
        rows: list[tuple] = []
        for row in copy.rows():
            rows.append(row)
            if len(rows) >= PSYCOPG_BATCH_ROWS:
                yield self._to_batch(rows)
                rows = []
        if rows:
            yield self._to_batch(rows)

    @staticmethod
    def _to_batch(rows: list[tuple]) -> pa.RecordBatch:
        cols = list(zip(*rows, strict=True))
        arrays = [pa.array(c, type=f.type) for c, f in zip(cols, ARROW_SCHEMA, strict=True)]
        return pa.RecordBatch.from_arrays(arrays, schema=ARROW_SCHEMA)

    def fetch(self, q: Query) -> FetchResult:
        sql, params = postgres_sql(q, self.table)
        stmt = f"COPY ({sql}) TO STDOUT (FORMAT BINARY)"
        t0 = time.perf_counter()
        with self.conn.cursor() as cur, cur.copy(stmt, params) as copy:
            copy.set_types(_PG_COPY_TYPES)
            res = consume(self._batches(copy), t0)
        res.window_id = q.window_id
        return res

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


class AdbcPostgres(BaseFetcher):
    db = "timescaledb"
    path = "adbc-postgresql-arrow"

    def __init__(self, settings: Settings, table: str):
        self.s, self.table, self.conn = settings, table, None

    def connect(self) -> None:
        import adbc_driver_postgresql.dbapi as adbc_pg

        self.conn = adbc_pg.connect(self.s.pg_uri())

    def fetch(self, q: Query) -> FetchResult:
        # Literal SQL, no parameters: bound parameters make the driver buffer the full result.
        sql = adbc_sql(q, self.table)
        t0 = time.perf_counter()
        with self.conn.cursor() as cur:
            cur.execute(sql)
            res = consume(cur.fetch_record_batch(), t0)
        res.window_id = q.window_id
        return res

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


FETCH_PATHS = ("clickhouse-connect-arrow", "psycopg3-binary-copy", "adbc-postgresql-arrow")


def make_factory(path: str, settings: Settings, pg_table: str) -> Callable[[], BaseFetcher]:
    """Factory for the named fetch path (validated against FETCH_PATHS)."""
    if path == "clickhouse-connect-arrow":
        return lambda: ClickHouseArrow(settings)
    if path == "psycopg3-binary-copy":
        return lambda: PsycopgBinaryCopy(settings, pg_table)
    if path == "adbc-postgresql-arrow":
        return lambda: AdbcPostgres(settings, pg_table)
    raise ValueError(f"unknown fetch path {path!r}; choose from {FETCH_PATHS}")
