import numpy as np
import pytest

from tlebench.generator import generate_chunk, make_manifest, row_epochs_us
from tlebench.windows import default_target_rows, size_window


def all_epochs(m):
    return np.concatenate(
        [generate_chunk(m, i).column("epoch").cast("int64").to_numpy() for i in range(m.n_chunks)]
    )


@pytest.mark.parametrize("position", [0.0, 0.2, 0.5, 1.0])
def test_window_returns_exactly_target_rows(position):
    m = make_manifest(rows=5_000, objects=100, span_days=37.3, chunk_rows=2_000)
    epochs = all_epochs(m)
    w = size_window(m, 1_234, position)
    assert w.rows == 1_234
    assert int(((epochs >= w.lo_us) & (epochs < w.hi_us)).sum()) == 1_234


def test_epoch_formula_matches_generated_data_and_big_scale_does_not_overflow():
    m = make_manifest(rows=3_000, objects=50, span_days=11, chunk_rows=1_000)
    assert np.array_equal(row_epochs_us(m, np.arange(3_000)), all_epochs(m))
    big = make_manifest(rows=100_000_000)
    e = row_epochs_us(big, np.array([0, 50_000_000, 99_999_999]))
    assert e[0] == big.start_us
    assert e[0] < e[1] < e[2] < big.start_us + big.span_us


def test_default_target_is_ten_percent():
    m = make_manifest(rows=1_000_000)
    assert default_target_rows(m) == 100_000
    assert size_window(m, default_target_rows(m)).rows == 100_000


def test_invalid_window_args():
    m = make_manifest(rows=1_000, objects=10)
    with pytest.raises(ValueError):
        size_window(m, 1_001)
    with pytest.raises(ValueError):
        size_window(m, 10, 1.5)
