from array import array
from datetime import datetime, timezone

import numpy as np

from hp3458a_studio.models import Measurement, SessionData
from hp3458a_studio.performance import (
    display_indices,
    memory_snapshot,
    windowed_display_indices,
)


def test_display_indices_bound_plot_payload_and_keep_endpoints():
    indices = display_indices(1_000_000, max_points=20_000)
    assert indices.size <= 20_000
    assert indices[0] == 0
    assert indices[-1] == 999_999
    assert np.all(np.diff(indices) > 0)


def test_short_display_payload_keeps_every_sample():
    assert np.array_equal(display_indices(5, 20_000), np.arange(5))


def test_windowed_display_indices_restore_local_detail():
    timestamps = array("d", (float(value) for value in range(100_000)))
    indices = windowed_display_indices(timestamps, 40_000.0, 40_099.0, max_points=200)
    assert np.array_equal(indices, np.arange(40_000, 40_100))


def test_windowed_display_indices_stay_bounded_for_wide_window():
    timestamps = array("d", (float(value) for value in range(100_000)))
    indices = windowed_display_indices(timestamps, 20_000.0, 79_999.0, max_points=500)
    assert indices.size <= 500
    assert indices[0] == 20_000
    assert indices[-1] == 79_999


def test_session_timestamps_use_compact_numeric_storage():
    session = SessionData()
    timestamp = datetime(2026, 7, 24, tzinfo=timezone.utc)
    session.append(Measurement(0.0, 1.0, "V", timestamp=timestamp))
    assert isinstance(session.timestamps, array)
    assert session.timestamps.typecode == "d"
    assert np.isclose(session.wall_clock_x[0], timestamp.timestamp())


def test_memory_monitor_returns_consistent_values():
    snapshot = memory_snapshot()
    assert 0.0 <= snapshot.system_percent <= 100.0
    assert snapshot.system_total_bytes > 0
    assert 0 <= snapshot.system_used_bytes <= snapshot.system_total_bytes
    assert snapshot.process_rss_bytes >= 0
