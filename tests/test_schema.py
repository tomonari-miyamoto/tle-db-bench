import pytest

from tlebench import schema
from tlebench.queries import Query, adbc_sql, clickhouse_sql, postgres_sql


def test_clickhouse_ddl_layout():
    ddl = schema.clickhouse_ddl()
    assert "ENGINE = MergeTree" in ddl
    assert "PARTITION BY toYYYYMM(epoch)" in ddl
    assert "ORDER BY (epoch, norad_id)" in ddl
    assert "epoch DateTime64(6, 'UTC') CODEC(DoubleDelta, ZSTD(1))" in ddl
    for name in schema.COLUMN_NAMES:
        assert f"    {name} " in ddl
    assert ddl.count("CODEC(") == len(schema.COLUMN_NAMES)


def test_columns_cover_the_tle_fields():
    assert schema.COLUMN_NAMES == [
        "norad_id", "epoch", "line1", "line2", "inclination", "raan",
        "eccentricity", "arg_perigee", "mean_anomaly", "mean_motion", "bstar",
    ]  # fmt: skip
    assert list(schema.ARROW_SCHEMA.names) == schema.COLUMN_NAMES


def test_timescale_compressed_has_columnstore_without_segmentby():
    sql = [s for s, _ in schema.timescale_statements("compressed")]
    alter = next(s for s in sql if s.startswith("ALTER TABLE tle_columnstore"))
    assert "timescaledb.enable_columnstore = true" in alter
    assert "timescaledb.segmentby = ''" in alter
    assert "timescaledb.orderby = 'epoch, norad_id'" in alter
    assert any("create_hypertable" in s for s in sql)


def test_timescale_uncompressed_variant_has_no_columnstore():
    stmts = schema.timescale_statements("uncompressed", "7 days")
    assert not any("ALTER TABLE" in s for s, _ in stmts)
    assert any("tle_rowstore" in s for s, _ in stmts)
    hyper = next(p for s, p in stmts if "create_hypertable" in s)
    assert hyper == ("tle_rowstore", "7 days")  # interval is a bound parameter


def test_unknown_variant_and_table_rejected():
    with pytest.raises(ValueError):
        schema.timescale_statements("bogus")
    with pytest.raises(ValueError):
        schema.clickhouse_ddl("tle; DROP TABLE x")
    with pytest.raises(ValueError):
        clickhouse_sql(Query("range", {"lo": 1, "hi": 2}), "users")
    with pytest.raises(ValueError):
        postgres_sql(Query("range", {"lo": 1, "hi": 2}), "users")
    with pytest.raises(ValueError):
        adbc_sql(Query("range", {"lo": 1, "hi": 2}), "users")


def test_values_are_bound_not_interpolated():
    q = Query("range", {"lo": 111_111, "hi": 222_222})
    sql, params = clickhouse_sql(q, "tle")
    assert "{lo:Int64}" in sql and "111111" not in sql and params == {"lo": 111_111, "hi": 222_222}
    sql, params = postgres_sql(q, "tle_columnstore")
    assert "%s" in sql and "111111" not in sql and len(params) == 2
    sql, params = postgres_sql(Query("object", {"nid": 25544}), "tle_rowstore")
    assert "25544" not in sql and params == (25544,)
    sql, _ = clickhouse_sql(Query("asof", {"ts": 99_999_999}), "tle")
    assert "99999999" not in sql and "GROUP BY norad_id" in sql
    sql, _ = postgres_sql(Query("asof", {"ts": 99_999_999}), "tle")
    assert "DISTINCT ON (norad_id)" in sql


def test_adbc_sql_has_no_placeholders_and_exact_literals():
    q = Query("range", {"lo": 946_684_800_000_001, "hi": 946_684_800_123_456})
    sql = adbc_sql(q, "tle_columnstore")
    assert not any(tok in sql for tok in ("$1", "$2", "%s", "{"))
    assert "epoch >= TIMESTAMPTZ '2000-01-01 00:00:00.000001+00'" in sql
    assert "AND epoch < TIMESTAMPTZ '2000-01-01 00:00:00.123456+00'" in sql
    sql = adbc_sql(Query("object", {"nid": 25544}), "tle_rowstore")
    assert "norad_id = 25544 ORDER BY epoch" in sql and "$" not in sql
    sql = adbc_sql(Query("asof", {"ts": 0}), "tle")
    assert "epoch <= TIMESTAMPTZ '1970-01-01 00:00:00.000000+00'" in sql and "$" not in sql


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None, 2**70])
def test_adbc_sql_rejects_non_int_inputs(bad):
    with pytest.raises(ValueError):
        adbc_sql(Query("range", {"lo": bad, "hi": 5}), "tle")
    with pytest.raises(ValueError):
        adbc_sql(Query("range", {"lo": 1, "hi": bad}), "tle")
    with pytest.raises(ValueError):
        adbc_sql(Query("object", {"nid": bad}), "tle")
    with pytest.raises(ValueError):
        adbc_sql(Query("asof", {"ts": bad}), "tle")


def test_adbc_literals_match_psycopg_bounds():
    from tlebench.queries import us_to_datetime

    lo, hi = 1_700_000_000_123_457, 1_700_000_999_999_999
    sql = adbc_sql(Query("range", {"lo": lo, "hi": hi}), "tle")
    _, params = postgres_sql(Query("range", {"lo": lo, "hi": hi}), "tle")
    assert params == (us_to_datetime(lo), us_to_datetime(hi))
    for dt in params:
        assert dt.strftime("%Y-%m-%d %H:%M:%S.%f") + "+00" in sql
    assert "epoch >= " in sql and "epoch < " in sql  # same half-open bounds as psycopg
