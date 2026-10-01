from array import array
from datetime import datetime, timezone

import numpy as np
import pytest

from hp3458a_studio.models import Measurement, SessionData


@pytest.mark.parametrize(
    "replacement",
    [
        {"elapsed_s": [0, 1], "values": [1]},
        {"elapsed_s": [[0]], "values": [1]},
        {"elapsed_s": [np.nan], "values": [1]},
        {"elapsed_s": [0], "values": [1], "timestamps": []},
        {"elapsed_s": [0], "values": [1], "timestamps": [np.nan]},
        {"elapsed_s": [0], "values": [1], "temperatures_c": [20, 21]},
    ],
)
def test_invalid_replacement_preserves_existing_capture(replacement):
    session = SessionData()
    timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    session.append(Measurement(0, 10, "Ω", timestamp, 23))
    with pytest.raises(ValueError):
        session.replace(**replacement)
    assert session.elapsed_s == [0]
    assert session.values == [10]
    assert session.unit == "Ω"
    assert session.timestamps[0] == timestamp.timestamp()
    assert session.temperatures_c == [23]


def test_explicit_wall_clock_times_override_elapsed_timestamp_inference():
    session = SessionData()
    session.replace(
        np.array([100, 100.5]),
        np.array([1, 2]),
        timestamps=np.array([946684800, 946684800.5]),
        temperatures_c=np.array([20, np.nan]),
    )
    np.testing.assert_array_equal(session.x, [0, 0.5])
    np.testing.assert_array_equal(session.wall_clock_x, [946684800, 946684800.5])
    np.testing.assert_array_equal(session.temperature, [20, np.nan])


def test_clear_keeps_compact_timestamp_storage_without_array_clear_method():
    class LegacyTimestampArray(array):
        def clear(self):
            raise AttributeError("Python 3.10–3.12 array has no clear method")

    session = SessionData(timestamps=LegacyTimestampArray("d"))
    session.append(Measurement(0, 10, "V", internal_temperature_c=23))
    session.clear()
    assert len(session) == 0
    assert session.elapsed_s == []
    assert session.temperatures_c == []
    assert isinstance(session.timestamps, array)
    assert session.timestamps.typecode == "d"
    assert len(session.timestamps) == 0
