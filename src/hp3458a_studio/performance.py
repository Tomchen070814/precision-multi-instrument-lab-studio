from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import psutil


@dataclass(frozen=True)
class MemorySnapshot:
    system_percent: float
    system_used_bytes: int
    system_total_bytes: int
    process_rss_bytes: int


def display_indices(length: int, max_points: int = 20_000) -> np.ndarray:
    """Return bounded, monotonic indices while always retaining both ends."""
    if length <= 0:
        return np.asarray([], dtype=np.int64)
    if length <= max_points:
        return np.arange(length, dtype=np.int64)
    indices = np.linspace(0, length - 1, max_points, dtype=np.int64)
    indices[0] = 0
    indices[-1] = length - 1
    return np.unique(indices)


def windowed_display_indices(
    timestamps: Sequence[float],
    x_min: float,
    x_max: float,
    max_points: int = 20_000,
) -> np.ndarray:
    """Return a bounded, full-resolution selection for one visible time window."""
    if not timestamps:
        return np.asarray([], dtype=np.int64)
    lower, upper = sorted((float(x_min), float(x_max)))
    start = bisect_left(timestamps, lower)
    stop = bisect_right(timestamps, upper)
    if stop <= start:
        return np.asarray([], dtype=np.int64)
    local_indices = display_indices(stop - start, max_points)
    return local_indices + start


def memory_snapshot() -> MemorySnapshot:
    """Return comparable physical RAM and process RSS on supported platforms."""
    try:
        memory = psutil.virtual_memory()
        rss = psutil.Process().memory_info().rss
    except psutil.Error as exc:
        raise OSError(str(exc)) from exc
    total = int(memory.total)
    used = max(0, min(total, total - int(memory.available)))
    return MemorySnapshot(
        100.0 * used / total if total else 0.0,
        used,
        total,
        int(rss),
    )
