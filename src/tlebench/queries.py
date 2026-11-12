"""SQL builders. Values are bound parameters except on the ADBC path (validated int
literals, see adbc_sql); table names are always allow-listed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .schema import COLUMN_LIST_SQL, COLUMN_NAMES, validate_table

KINDS = ("range", "object", "asof")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Query:
    """A logical query. Params: range -> lo, hi (us); object -> nid; asof -> ts (us)."""

    kind: str
    params: dict[str, int] = field(default_factory=dict)
    expected_rows: int | None = None
    window_id: int = 0

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown query kind {self.kind!r}")


def us_to_datetime(us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=us)


def clickhouse_sql(q: Query, table: str) -> tuple[str, dict[str, int]]:
    """Server-side bound parameters: {name:Type} placeholders plus a params dict."""
    validate_table(table)
    if q.kind == "range":
        sql = (
            f"SELECT {COLUMN_LIST_SQL} FROM {table} "
            "WHERE epoch >= fromUnixTimestamp64Micro({lo:Int64}, 'UTC') "
            "AND epoch < fromUnixTimestamp64Micro({hi:Int64}, 'UTC')"
        )
        return sql, {"lo": q.params["lo"], "hi": q.params["hi"]}
    if q.kind == "object":
        sql = (
            f"SELECT {COLUMN_LIST_SQL} FROM {table} WHERE norad_id = {{nid:UInt32}} ORDER BY epoch"
        )
        return sql, {"nid": q.params["nid"]}
    # asof: newest element set per object at or before ts. Aliases are prefixed so they do not
    # shadow source columns inside the aggregates.
    aggs = ", ".join(
        f"argMax({c}, epoch) AS last_{c}" for c in COLUMN_NAMES if c not in ("norad_id", "epoch")
    )
    sql = (
        f"SELECT norad_id, max(epoch) AS last_epoch, {aggs} FROM {table} "
        "WHERE epoch <= fromUnixTimestamp64Micro({ts:Int64}, 'UTC') GROUP BY norad_id"
    )
    return sql, {"ts": q.params["ts"]}


def postgres_sql(q: Query, table: str) -> tuple[str, tuple[Any, ...]]:
    """psycopg path: %s placeholders and bound parameters."""
    validate_table(table)
    if q.kind == "range":
        sql = f"SELECT {COLUMN_LIST_SQL} FROM {table} WHERE epoch >= %s AND epoch < %s"
        return sql, (us_to_datetime(q.params["lo"]), us_to_datetime(q.params["hi"]))
    if q.kind == "object":
        sql = f"SELECT {COLUMN_LIST_SQL} FROM {table} WHERE norad_id = %s ORDER BY epoch"
        return sql, (q.params["nid"],)
    sql = (
        f"SELECT DISTINCT ON (norad_id) {COLUMN_LIST_SQL} FROM {table} "
        "WHERE epoch <= %s ORDER BY norad_id, epoch DESC"
    )
    return sql, (us_to_datetime(q.params["ts"]),)


def _int_literal(value: object, name: str) -> int:
    """Only a true int may reach a SQL literal; bool (an int subclass) and the rest are rejected."""
    if type(value) is not int:
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    return value


def _tstz_literal(us: object, name: str) -> str:
    """Exact UTC timestamptz literal (microsecond precision) from an int of epoch microseconds.

    The text is rendered from integer fields by a fixed format with an explicit +00 offset, so it
    does not depend on the session TimeZone and has no float rounding.
    """
    try:
        dt = us_to_datetime(_int_literal(us, name))
    except OverflowError as exc:
        raise ValueError(f"{name} out of range: {us}") from exc
    return f"TIMESTAMPTZ '{dt.strftime('%Y-%m-%d %H:%M:%S.%f')}+00'"


def adbc_sql(q: Query, table: str) -> str:
    """ADBC path: no bound parameters, so the driver can use its COPY streaming path.

    With parameters the ADBC PostgreSQL driver materialises the whole result before returning
    the first batch. Values are validated Python ints rendered as literals; bounds match the
    psycopg form (range: epoch >= lo AND epoch < hi; asof: epoch <= ts).
    """
    validate_table(table)
    if q.kind == "range":
        lo = _tstz_literal(q.params["lo"], "lo")
        hi = _tstz_literal(q.params["hi"], "hi")
        return f"SELECT {COLUMN_LIST_SQL} FROM {table} WHERE epoch >= {lo} AND epoch < {hi}"
    if q.kind == "object":
        nid = _int_literal(q.params["nid"], "nid")
        if not 0 <= nid <= 2**31 - 1:  # norad_id is int4
            raise ValueError(f"nid out of range: {nid}")
        return f"SELECT {COLUMN_LIST_SQL} FROM {table} WHERE norad_id = {nid} ORDER BY epoch"
    ts = _tstz_literal(q.params["ts"], "ts")
    return (
        f"SELECT DISTINCT ON (norad_id) {COLUMN_LIST_SQL} FROM {table} "
        f"WHERE epoch <= {ts} ORDER BY norad_id, epoch DESC"
    )
