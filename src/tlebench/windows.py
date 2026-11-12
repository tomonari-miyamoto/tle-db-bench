"""Time-window sizing: choose [lo, hi) so a range scan returns exactly the target row count."""

from __future__ import annotations

from dataclasses import dataclass

from .generator import Manifest


@dataclass(frozen=True)
class Window:
    lo_us: int
    hi_us: int  # exclusive
    rows: int
    first_index: int


def size_window(m: Manifest, target_rows: int, position: float = 0.5) -> Window:
    """Window covering exactly `target_rows` rows, starting at fraction `position` of the slack.

    Exact because epochs are strictly increasing on the generator's integer grid.
    """
    if not 1 <= target_rows <= m.rows:
        raise ValueError(f"target_rows must be in 1..{m.rows}, got {target_rows}")
    if not 0.0 <= position <= 1.0:
        raise ValueError("position must be within [0, 1]")
    first = round(position * (m.rows - target_rows))
    last = first + target_rows
    hi = m.epoch_us(last) if last < m.rows else m.start_us + m.span_us
    return Window(m.epoch_us(first), hi, target_rows, first)


def default_target_rows(m: Manifest, fraction: float = 0.10) -> int:
    return max(1, round(m.rows * fraction))
