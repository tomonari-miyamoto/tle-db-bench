"""Deterministic, vectorised synthetic TLE generator that writes Parquet chunks.

Epochs lie on an exact integer grid (row i has epoch start + floor(i * span / rows)), so a
time window returning exactly k rows can be computed arithmetically, with no data scan.
Every chunk is generated from its own RNG seeded with (seed, chunk index), so chunks are
reproducible independently and 100M rows never sit in memory at once.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .schema import ARROW_SCHEMA

LINE_LEN = 69
MANIFEST_NAME = "manifest.json"
DEFAULT_ROWS_PER_DAY = 10_000
US_PER_DAY = 86_400 * 1_000_000


@dataclass(frozen=True)
class Manifest:
    seed: int
    rows: int
    objects: int
    start_us: int
    span_us: int
    chunk_rows: int

    def __post_init__(self) -> None:
        if self.rows < 1:
            raise ValueError("rows must be >= 1")
        if not 1 <= self.objects <= 99_999:
            raise ValueError("objects must be in 1..99999 (5-digit NORAD ids)")
        if self.chunk_rows < 1:
            raise ValueError("chunk_rows must be >= 1")
        if self.span_us < self.rows:
            raise ValueError("time span too short: need at least 1 microsecond per row")

    @property
    def n_chunks(self) -> int:
        return -(-self.rows // self.chunk_rows)

    def chunk_filename(self, idx: int) -> str:
        return f"part-{idx:05d}.parquet"

    def chunk_bounds(self, idx: int) -> tuple[int, int]:
        """(first row index, row count) of chunk idx."""
        if not 0 <= idx < self.n_chunks:
            raise IndexError(idx)
        first = idx * self.chunk_rows
        return first, min(self.chunk_rows, self.rows - first)

    def epoch_us(self, index: int) -> int:
        """Exact epoch (microseconds since the Unix epoch) of global row index."""
        return int(row_epochs_us(self, np.asarray([index], dtype=np.int64))[0])

    def save(self, directory: Path | str) -> None:
        (Path(directory) / MANIFEST_NAME).write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls, directory: Path | str) -> Manifest:
        return cls(**json.loads((Path(directory) / MANIFEST_NAME).read_text()))


def make_manifest(
    rows: int,
    seed: int = 42,
    objects: int = 30_000,
    start: str = "2000-01-01",
    span_days: float | None = None,
    chunk_rows: int = 1_000_000,
) -> Manifest:
    """Build a manifest; the default span follows the production growth of ~10k rows/day."""
    start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
    days = span_days if span_days is not None else max(1.0, rows / DEFAULT_ROWS_PER_DAY)
    return Manifest(
        seed=seed,
        rows=rows,
        objects=objects,
        start_us=int(start_dt.timestamp()) * 1_000_000,
        span_us=int(days * US_PER_DAY),
        chunk_rows=chunk_rows,
    )


def row_epochs_us(m: Manifest, idx: np.ndarray) -> np.ndarray:
    """start + floor(idx * span / rows) in int64 without overflow (idx*span can exceed 2^63)."""
    q, r = divmod(m.span_us, m.rows)
    idx = idx.astype(np.int64)
    return m.start_us + idx * q + (idx * r) // m.rows


# ---------------------------------------------------------------- object catalog


@cache
def make_catalog(seed: int, n: int) -> dict[str, np.ndarray]:
    """Per-object base orbit parameters, a function of (seed, n) only."""
    rng = np.random.default_rng([seed, 0])
    norad = np.sort(rng.choice(np.arange(1, 100_000), size=n, replace=False)).astype(np.uint32)
    # 0 LEO, 1 sun-synchronous, 2 MEO (GNSS), 3 GEO, 4 HEO/GTO
    klass = rng.choice(5, size=n, p=[0.55, 0.25, 0.04, 0.11, 0.05])
    inc = np.empty(n)
    mm = np.empty(n)
    ecc = np.minimum(rng.exponential(0.002, n), 0.05)
    bstar_mag = 10 ** rng.uniform(-5.0, -3.0, n)
    for k, (lo, hi) in enumerate([(13.5, 16.0), (13.8, 15.3), (1.8, 2.2), (0.9, 1.1), (1.5, 3.0)]):
        sel = klass == k
        mm[sel] = rng.uniform(lo, hi, sel.sum())
    leo = klass == 0
    inc[leo] = rng.choice([51.6, 53.0, 70.0, 82.0, 87.9, 45.0], leo.sum()) + rng.normal(
        0, 0.3, leo.sum()
    )
    inc[klass == 1] = rng.normal(98.0, 0.6, (klass == 1).sum())
    inc[klass == 2] = rng.normal(55.0, 3.0, (klass == 2).sum())
    inc[klass == 3] = np.abs(rng.normal(0.0, 3.0, (klass == 3).sum()))
    inc[klass == 4] = np.clip(rng.normal(63.0, 10.0, (klass == 4).sum()), 0, 120)
    heo = klass == 4
    ecc[heo] = rng.uniform(0.3, 0.75, heo.sum())
    high = klass >= 2
    bstar_mag[high] = 10 ** rng.uniform(-7.0, -5.0, high.sum())
    year = rng.integers(57, 125, n) % 100
    return {
        "norad": norad,
        "klass": klass.astype(np.int8),
        "inc": np.clip(inc, 0.0, 179.0),
        "mm": mm,
        "ecc": ecc,
        "bstar_mag": bstar_mag,
        "bstar_sign": np.where(rng.random(n) < 0.95, 1.0, -1.0),
        "raan0": rng.uniform(0, 360, n),
        "raan_rate": np.where(leo, rng.normal(-3.0, 2.0, n), rng.normal(0.0, 0.05, n)),
        "argp0": rng.uniform(0, 360, n),
        "intl": _intl_designators(year, rng.integers(1, 999, n), rng.integers(0, 26, n)),
    }


def _intl_designators(year: np.ndarray, launch: np.ndarray, piece: np.ndarray) -> np.ndarray:
    out = np.full((len(year), 8), 32, dtype=np.uint8)
    out[:, 0:2] = _digits(year, 2)
    out[:, 2:5] = _digits(launch, 3)
    out[:, 5] = 65 + piece
    return out


# ---------------------------------------------------------------- byte-level TLE formatting


def _digits(values: np.ndarray, width: int, zero_pad: bool = True) -> np.ndarray:
    """(n, width) ASCII digits of non-negative ints; optionally space-padded on the left."""
    v = values.astype(np.int64)
    out = np.empty((len(v), width), dtype=np.uint8)
    for j in range(width):
        p = width - 1 - j
        out[:, j] = 48 + (v // 10**p) % 10
        if not zero_pad and p > 0:
            out[v < 10**p, j] = 32
    return out


def _fixed(scaled: np.ndarray, width: int, dec: int) -> np.ndarray:
    """Like '%{width}.{dec}f' for non-negative values given as ints scaled by 10**dec."""
    v = scaled.astype(np.int64)
    out = np.empty((len(v), width), dtype=np.uint8)
    point = width - dec - 1
    for j in range(width):
        if j == point:
            out[:, j] = 46
            continue
        p = width - 1 - j if j > point else width - 2 - j
        out[:, j] = 48 + (v // 10**p) % 10
        if p > dec:
            out[v < 10**p, j] = 32
    return out


def _exp_field(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """TLE 'assumed decimal point' field, e.g. ' 12345-3' = 0.12345e-3.

    Returns ((n, 8) bytes, quantised float values) for non-zero finite inputs.
    """
    sign = np.where(values < 0, -1.0, 1.0)
    a = np.clip(np.abs(values), 1e-9, 0.99)
    e = np.floor(np.log10(a)).astype(np.int64) + 1
    m5 = np.rint(a / 10.0**e * 1e5).astype(np.int64)
    carry = m5 >= 100_000
    m5[carry] = 10_000
    e[carry] += 1
    e = np.clip(e, -9, 9)
    out = np.empty((len(a), 8), dtype=np.uint8)
    out[:, 0] = np.where(sign < 0, 45, 32)
    out[:, 1:6] = _digits(m5, 5)
    out[:, 6] = np.where(e < 0, 45, 43)
    out[:, 7] = 48 + np.abs(e)
    shift = e - 5  # value = m5 * 10**shift; divide for negative shifts so rounding is exact
    quant = np.where(
        shift < 0, m5 / 10.0 ** np.maximum(-shift, 0), m5 * 10.0 ** np.maximum(shift, 0)
    )
    return out, sign * quant


def _checksum(buf: np.ndarray) -> None:
    body = buf[:, : LINE_LEN - 1]
    digit = (body >= 48) & (body <= 57)
    total = np.where(digit, body - 48, 0).sum(axis=1) + (body == 45).sum(axis=1)
    buf[:, LINE_LEN - 1] = 48 + total % 10


def _to_string_array(buf: np.ndarray) -> pa.Array:
    n = buf.shape[0]
    offsets = (np.arange(n + 1, dtype=np.int64) * LINE_LEN).astype(np.int32)
    return pa.Array.from_buffers(
        pa.string(),
        n,
        [None, pa.py_buffer(offsets), pa.py_buffer(np.ascontiguousarray(buf))],
    )


def _epoch_field(epoch_us: np.ndarray) -> np.ndarray:
    """YYDDD.DDDDDDDD (14 chars)."""
    t = epoch_us.astype("datetime64[us]")
    year_start = t.astype("datetime64[Y]")
    day = t.astype("datetime64[D]")
    doy = (day - year_start.astype("datetime64[D]")).astype(np.int64) + 1
    yy = year_start.astype(np.int64) + 1970
    frac_us = (t - day.astype("datetime64[us]")).astype(np.int64)
    frac = np.minimum(np.rint(frac_us / US_PER_DAY * 1e8).astype(np.int64), 99_999_999)
    out = np.empty((len(t), 14), dtype=np.uint8)
    out[:, 0:2] = _digits(yy % 100, 2)
    out[:, 2:5] = _digits(doy, 3)
    out[:, 5] = 46
    out[:, 6:14] = _digits(frac, 8)
    return out


# ---------------------------------------------------------------- chunk generation


def generate_chunk(m: Manifest, chunk_idx: int) -> pa.Table:
    first, count = m.chunk_bounds(chunk_idx)
    rng = np.random.default_rng([m.seed, 1, chunk_idx])
    cat = make_catalog(m.seed, m.objects)

    epoch_us = row_epochs_us(m, np.arange(first, first + count, dtype=np.int64))
    obj = rng.integers(0, m.objects, count)
    days = (epoch_us - m.start_us) / US_PER_DAY

    inc_s = np.clip(np.rint((cat["inc"][obj] + rng.normal(0, 0.002, count)) * 1e4), 0, 1_800_000)
    raan_s = np.rint(np.mod(cat["raan0"][obj] + cat["raan_rate"][obj] * days, 360.0) * 1e4)
    argp_s = np.rint(np.mod(cat["argp0"][obj] + rng.normal(0, 3.0, count), 360.0) * 1e4)
    ma_s = np.rint(rng.uniform(0, 360, count) * 1e4)
    ecc_s = np.clip(np.rint(cat["ecc"][obj] * (1 + rng.normal(0, 0.02, count)) * 1e7), 0, 9_999_999)
    mm_s = np.clip(
        np.rint(cat["mm"][obj] * (1 + rng.normal(0, 1e-4, count)) * 1e8), 0, 9_999_999_999
    )
    # Rounding can reach 360.0000 exactly; wrap so the 8-char field stays valid.
    raan_s, argp_s, ma_s = (np.where(x >= 3_600_000, 0, x) for x in (raan_s, argp_s, ma_s))
    inc_s, raan_s, argp_s, ma_s, ecc_s, mm_s = (
        x.astype(np.int64) for x in (inc_s, raan_s, argp_s, ma_s, ecc_s, mm_s)
    )

    bstar_in = cat["bstar_sign"][obj] * cat["bstar_mag"][obj] * (1 + rng.normal(0, 0.05, count))
    bstar_field, bstar = _exp_field(bstar_in)
    ndot_s = np.minimum(np.rint(np.abs(rng.normal(0, 2e-5, count)) * 1e8), 99_999_999)
    ndot_neg = rng.random(count) < 0.5
    elset = rng.integers(1, 999, count)
    revnum = rng.integers(1, 99_999, count)

    norad_digits = _digits(cat["norad"][obj], 5)

    l1 = np.full((count, LINE_LEN), 32, dtype=np.uint8)
    l1[:, 0] = 49
    l1[:, 2:7] = norad_digits
    l1[:, 7] = 85  # 'U'
    l1[:, 9:17] = cat["intl"][obj]
    l1[:, 18:32] = _epoch_field(epoch_us)
    l1[:, 33] = np.where(ndot_neg, 45, 32)
    l1[:, 34] = 46
    l1[:, 35:43] = _digits(ndot_s, 8)
    l1[:, 44:52] = np.frombuffer(b" 00000-0", dtype=np.uint8)
    l1[:, 53:61] = bstar_field
    l1[:, 62] = 48
    l1[:, 64:68] = _digits(elset, 4, zero_pad=False)
    _checksum(l1)

    l2 = np.full((count, LINE_LEN), 32, dtype=np.uint8)
    l2[:, 0] = 50
    l2[:, 2:7] = norad_digits
    l2[:, 8:16] = _fixed(inc_s, 8, 4)
    l2[:, 17:25] = _fixed(raan_s, 8, 4)
    l2[:, 26:33] = _digits(ecc_s, 7)
    l2[:, 34:42] = _fixed(argp_s, 8, 4)
    l2[:, 43:51] = _fixed(ma_s, 8, 4)
    l2[:, 52:63] = _fixed(mm_s, 11, 8)
    l2[:, 63:68] = _digits(revnum, 5, zero_pad=False)
    _checksum(l2)

    return pa.table(
        {
            "norad_id": pa.array(cat["norad"][obj], type=pa.uint32()),
            "epoch": pa.array(
                epoch_us.astype("datetime64[us]"), type=ARROW_SCHEMA.field("epoch").type
            ),
            "line1": _to_string_array(l1),
            "line2": _to_string_array(l2),
            "inclination": inc_s / 1e4,
            "raan": raan_s / 1e4,
            "eccentricity": ecc_s / 1e7,
            "arg_perigee": argp_s / 1e4,
            "mean_anomaly": ma_s / 1e4,
            "mean_motion": mm_s / 1e8,
            "bstar": bstar,
        },
        schema=ARROW_SCHEMA,
    )


def generate_dataset(
    m: Manifest,
    out_dir: Path | str,
    progress: Callable[[int, int], None] | None = None,
    row_group_size: int = 250_000,
) -> list[Path]:
    """Write all chunks as Parquet (zstd) plus manifest.json; returns the file paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for idx in range(m.n_chunks):
        path = out / m.chunk_filename(idx)
        pq.write_table(
            generate_chunk(m, idx), path, compression="zstd", row_group_size=row_group_size
        )
        paths.append(path)
        if progress:
            progress(idx + 1, m.n_chunks)
    m.save(out)
    return paths


def dataset_files(m: Manifest, data_dir: Path | str) -> list[Path]:
    paths = [Path(data_dir) / m.chunk_filename(i) for i in range(m.n_chunks)]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"missing Parquet chunks in {data_dir}: {missing[:3]}...")
    return paths
