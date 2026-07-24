from __future__ import annotations

import ctypes
import os
import platform
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


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


def _windows_memory_snapshot() -> MemorySnapshot:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = (
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        )

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
        ctypes.byref(status)
    ):
        raise OSError("GlobalMemoryStatusEx failed")

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process_handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
    process_rss = 0
    if ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
        process_handle,
        ctypes.byref(counters),
        counters.cb,
    ):
        process_rss = int(counters.WorkingSetSize)

    total = int(status.ullTotalPhys)
    available = int(status.ullAvailPhys)
    used = max(0, total - available)
    percent = 100.0 * used / total if total else float(status.dwMemoryLoad)
    return MemorySnapshot(percent, used, total, process_rss)


def _linux_memory_snapshot() -> MemorySnapshot:
    fields: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, value = line.split(":", 1)
        fields[key] = int(value.strip().split()[0]) * 1024
    total = fields["MemTotal"]
    available = fields.get("MemAvailable", fields.get("MemFree", 0))
    used = max(0, total - available)
    process_rss = 0
    statm = Path("/proc/self/statm")
    if statm.is_file():
        pages = int(statm.read_text(encoding="ascii").split()[1])
        process_rss = pages * int(os.sysconf("SC_PAGE_SIZE"))
    return MemorySnapshot(
        100.0 * used / total if total else 0.0,
        used,
        total,
        process_rss,
    )


def memory_snapshot() -> MemorySnapshot:
    """Return current physical-memory and process-RSS usage."""
    system = platform.system()
    if system == "Windows":
        return _windows_memory_snapshot()
    if system == "Linux" and Path("/proc/meminfo").is_file():
        return _linux_memory_snapshot()
    raise OSError(f"Memory monitoring is not implemented for {system}")
