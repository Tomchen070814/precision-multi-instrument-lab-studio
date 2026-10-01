import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from hp3458a_studio.csv_io import (
    read_measurement_csv,
    write_dual_session_csv,
    write_multi_session_csv,
    write_session_csv,
)
from hp3458a_studio.models import Measurement, SessionData
from hp3458a_studio.persistence import DurableSessionWriter


def test_csv_auto_detects_time_and_value(tmp_path: Path):
    source = tmp_path / "input.csv"
    source.write_text(
        "timestamp,voltage (V),comment\n"
        "2026-01-01T00:00:00+00:00,1.0,a\n"
        "2026-01-01T00:00:01+00:00,1.1,b\n",
        encoding="utf-8",
    )
    imported = read_measurement_csv(source)
    assert imported.x_column == "timestamp"
    assert imported.y_column == "voltage (V)"
    assert imported.unit == "V"
    assert np.allclose(imported.elapsed_s, [0, 1])
    assert np.allclose(imported.values, [1.0, 1.1])


def test_session_export_includes_temperature(tmp_path: Path):
    session = SessionData()
    session.append(Measurement(0.0, 10.0, "V", internal_temperature_c=23.1))
    output = tmp_path / "output.csv"
    write_session_csv(output, session)
    text = output.read_text(encoding="utf-8-sig")
    assert "internal_temperature_c" in text
    assert "23.100000" in text


def _session(values, unit):
    session = SessionData(unit=unit)
    for index, value in enumerate(values):
        session.append(
            Measurement(
                elapsed_s=index * 0.5,
                value=value,
                unit=unit,
                timestamp=datetime.now(timezone.utc),
                internal_temperature_c=23.0 + index * 0.1,
            )
        )
    return session


def test_dual_csv_preserves_independent_lengths(tmp_path: Path):
    output = tmp_path / "dual.csv"
    write_dual_session_csv(
        output,
        _session([1.0, 1.1, 1.2], "V"),
        _session([10.0], "Ω"),
    )
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert "reading_A (V)" in rows[0]
    assert "reading_B (Ω)" in rows[0]
    assert len(rows) == 4
    assert rows[1][6] == "10"
    assert rows[2][4:] == ["", "", "", ""]


def test_multi_csv_supports_reserved_third_channel(tmp_path: Path):
    sessions = {
        "A": _session([1.0], "V"),
        "B": _session([2.0, 2.1], "V"),
        "C": _session([3.0, 3.1, 3.2], "V"),
    }
    output = tmp_path / "triple.csv"
    write_multi_session_csv(output, sessions)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert "timestamp_A" in rows[0]
    assert "timestamp_B" in rows[0]
    assert "timestamp_C" in rows[0]
    assert len(rows) == 4
    assert rows[2][0:4] == ["", "", "", ""]
    assert rows[3][4:8] == ["", "", "", ""]
    assert float(rows[3][10]) == 3.2


@pytest.mark.parametrize("channel", [None, "A", "B", "C"])
def test_multi_import_pairs_readings_with_their_own_time_and_temperature(
    tmp_path: Path, channel: str | None
):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    sessions = {}
    for key, period, unit in [("A", 1.0, "V"), ("B", 2.0, "Ω"), ("C", 3.0, "A")]:
        session = SessionData()
        for index in range(4):
            session.append(
                Measurement(
                    index * period,
                    period * 10 + index,
                    unit,
                    timestamp=start + timedelta(seconds=index * period),
                    internal_temperature_c=20 + period + index,
                )
            )
        sessions[key] = session
    path = tmp_path / "three_channels.csv"
    write_multi_session_csv(path, sessions)

    imported = read_measurement_csv(path, channel=channel)
    expected_channel = channel or "A"
    expected = sessions[expected_channel]
    assert imported.x_column == f"elapsed_{expected_channel}_s"
    assert imported.y_column == f"reading_{expected_channel} ({expected.unit})"
    assert imported.unit == expected.unit
    np.testing.assert_array_equal(imported.elapsed_s, expected.x)
    np.testing.assert_array_equal(imported.values, expected.y)
    np.testing.assert_array_equal(imported.timestamps, expected.wall_clock_x)
    np.testing.assert_array_equal(imported.temperatures_c, expected.temperature)


def test_multi_import_keeps_short_channel_and_falls_back_for_missing_channel(
    tmp_path: Path,
):
    path = tmp_path / "unequal.csv"
    sessions = {"A": _session([1.0], "V"), "B": _session(list(range(20)), "Ω")}
    write_multi_session_csv(path, sessions)
    for channel in (None, "A", "C"):
        imported = read_measurement_csv(path, channel=channel)
        assert imported.y_column == "reading_A (V)"
        np.testing.assert_array_equal(imported.values, [1.0])
    assert read_measurement_csv(path, channel="B").values.size == 20


def test_durable_capture_import_restores_unit_timestamps_and_temperature(
    tmp_path: Path,
):
    writer = DurableSessionWriter(
        channel="B", instrument_model="DMM", resource="SIM", root=tmp_path
    )
    start = datetime(1999, 1, 1, tzinfo=timezone.utc)
    readings = [123.45678901234567, 124.12345678901234, 125.98765432109876]
    for index, value in enumerate(readings):
        writer.append(
            Measurement(
                index * 0.25,
                value,
                "Ω",
                timestamp=start + timedelta(seconds=index * 0.25),
                internal_temperature_c=23.25 + index * 0.125,
            )
        )
    imported = read_measurement_csv(writer.finalize("completed"))
    assert imported.unit == "Ω"
    np.testing.assert_array_equal(imported.values, readings)
    np.testing.assert_array_equal(imported.elapsed_s, [0, 0.25, 0.5])
    np.testing.assert_array_equal(
        imported.timestamps, start.timestamp() + np.arange(3) * 0.25
    )
    np.testing.assert_array_equal(imported.temperatures_c, [23.25, 23.375, 23.5])
    restored = SessionData()
    restored.replace(
        imported.elapsed_s,
        imported.values,
        imported.unit,
        timestamps=imported.timestamps,
        temperatures_c=imported.temperatures_c,
    )
    np.testing.assert_array_equal(restored.wall_clock_x, imported.timestamps)
    np.testing.assert_array_equal(restored.temperature, imported.temperatures_c)


def test_single_csv_roundtrip_retains_full_numeric_precision(tmp_path: Path):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    session = SessionData()
    for index, value in enumerate([1.2345678901234567, 3.2, -9.876543210987654]):
        session.append(
            Measurement(
                index * 1.23456789012345e-7,
                value,
                "V",
                timestamp=start + timedelta(seconds=index),
                internal_temperature_c=23.123456789012345 if index else None,
            )
        )
    path = tmp_path / "full_precision.csv"
    write_session_csv(path, session)
    imported = read_measurement_csv(path)
    np.testing.assert_array_equal(imported.elapsed_s, session.x)
    np.testing.assert_array_equal(imported.values, session.y)
    np.testing.assert_array_equal(imported.timestamps, session.wall_clock_x)
    np.testing.assert_array_equal(imported.temperatures_c, session.temperature)


def test_csv_rejects_mixed_units_in_one_reading_column(tmp_path: Path):
    path = tmp_path / "mixed_units.csv"
    path.write_text("elapsed_s,reading,unit\n0,1,V\n1,2,A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="单位"):
        read_measurement_csv(path)


def test_csv_keeps_unlabelled_numeric_x_with_labelled_readings(tmp_path: Path):
    path = tmp_path / "generic.csv"
    path.write_text("x,voltage (V)\n10,1\n12,2\n15,3\n", encoding="utf-8")
    imported = read_measurement_csv(path)
    assert imported.x_column == "x"
    np.testing.assert_array_equal(imported.elapsed_s, [0, 2, 5])


def test_csv_keeps_timestamp_and_temperature_aligned_after_invalid_row(tmp_path: Path):
    path = tmp_path / "invalid_sample.csv"
    path.write_text(
        "timestamp_iso,elapsed_s,reading (V),internal_temperature_c\n"
        "2020-01-01T00:00:00Z,0,1,20\n"
        "2020-01-01T00:00:01Z,1,invalid,21\n"
        "2020-01-01T00:00:02Z,2,3,22\n",
        encoding="utf-8",
    )
    imported = read_measurement_csv(path)
    np.testing.assert_array_equal(imported.elapsed_s, [0, 2])
    np.testing.assert_array_equal(imported.values, [1, 3])
    np.testing.assert_array_equal(imported.temperatures_c, [20, 22])
    np.testing.assert_array_equal(np.diff(imported.timestamps), [2])
