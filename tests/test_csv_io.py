import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from hp3458a_studio.csv_io import (
    read_measurement_csv,
    write_dual_session_csv,
    write_multi_session_csv,
    write_session_csv,
)
from hp3458a_studio.models import Measurement, SessionData


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
    assert rows[3][10] == "3.2"
