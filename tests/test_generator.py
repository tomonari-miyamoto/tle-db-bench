import numpy as np
import pyarrow.parquet as pq
import pytest

from tlebench.generator import (
    LINE_LEN,
    Manifest,
    generate_chunk,
    generate_dataset,
    make_manifest,
)
from tlebench.schema import ARROW_SCHEMA


@pytest.fixture
def manifest() -> Manifest:
    return make_manifest(rows=2_500, seed=7, objects=300, span_days=50, chunk_rows=1_000)


def checksum(line: str) -> int:
    return sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68]) % 10


def test_chunk_is_deterministic(manifest):
    assert generate_chunk(manifest, 1).equals(generate_chunk(manifest, 1))


def test_seed_changes_data(manifest):
    other = make_manifest(rows=2_500, seed=8, objects=300, span_days=50, chunk_rows=1_000)
    assert not generate_chunk(manifest, 0).equals(generate_chunk(other, 0))


def test_chunk_matches_schema_and_size(manifest):
    t = generate_chunk(manifest, 2)
    assert t.schema.equals(ARROW_SCHEMA)
    assert t.num_rows == 500


def test_epochs_strictly_increase_across_chunks(manifest):
    last = None
    for i in range(manifest.n_chunks):
        e = generate_chunk(manifest, i).column("epoch").cast("int64").to_numpy()
        assert (np.diff(e) > 0).all()
        if last is not None:
            assert e[0] > last
        last = e[-1]
    assert last < manifest.start_us + manifest.span_us


def test_tle_lines_are_valid_and_consistent_with_columns(manifest):
    t = generate_chunk(manifest, 0).slice(0, 200).to_pylist()
    for row in t:
        l1, l2 = row["line1"], row["line2"]
        assert len(l1) == LINE_LEN and len(l2) == LINE_LEN
        assert l1[0] == "1" and l2[0] == "2"
        assert int(l1[-1]) == checksum(l1) and int(l2[-1]) == checksum(l2)
        assert int(l1[2:7]) == int(l2[2:7]) == row["norad_id"]
        assert float(l2[8:16]) == row["inclination"]
        assert float(l2[17:25]) == row["raan"]
        assert float(f"0.{l2[26:33]}") == row["eccentricity"]
        assert float(l2[34:42]) == row["arg_perigee"]
        assert float(l2[43:51]) == row["mean_anomaly"]
        assert float(l2[52:63]) == row["mean_motion"]
        mant, exp = l1[53:59].replace(" ", "+"), l1[59:61]
        assert float(f"{mant[0]}0.{mant[1:]}e{exp}") == pytest.approx(row["bstar"], rel=1e-9)
        ep = row["epoch"]
        assert int(l1[18:20]) == ep.year % 100
        assert int(l1[20:23]) == ep.timetuple().tm_yday


def test_value_ranges_are_realistic(manifest):
    t = generate_chunk(manifest, 0)
    inc = t.column("inclination").to_numpy()
    mm = t.column("mean_motion").to_numpy()
    ecc = t.column("eccentricity").to_numpy()
    assert inc.min() >= 0 and inc.max() <= 180
    assert mm.min() > 0.5 and mm.max() < 20
    assert ecc.min() >= 0 and ecc.max() < 1
    for name in ("raan", "arg_perigee", "mean_anomaly"):
        v = t.column(name).to_numpy()
        assert v.min() >= 0 and v.max() < 360


def test_objects_bounded_by_catalog(manifest):
    ids = generate_chunk(manifest, 0).column("norad_id").to_numpy()
    assert len(np.unique(ids)) <= manifest.objects
    assert ids.min() >= 1 and ids.max() <= 99_999


def test_dataset_row_counts_and_manifest_roundtrip(manifest, tmp_path):
    paths = generate_dataset(manifest, tmp_path)
    assert len(paths) == manifest.n_chunks == 3
    assert sum(pq.ParquetFile(p).metadata.num_rows for p in paths) == manifest.rows
    assert Manifest.load(tmp_path) == manifest


def test_default_span_follows_growth_rate():
    m = make_manifest(rows=1_000_000)
    assert m.span_us == 100 * 86_400 * 1_000_000


def test_invalid_manifests_rejected():
    with pytest.raises(ValueError):
        make_manifest(rows=1_000, span_days=0.0)  # span shorter than 1 us per row
    with pytest.raises(ValueError):
        make_manifest(rows=10, objects=100_000)
