import csv
import time

import numpy as np
import pytest
from PySide6 import QtCore, QtTest
from shiboken6 import isValid

from hp3458a_studio.smu_demo import (
    DiodeModel,
    SmuDemoDialog,
    SweepConfig,
    VirtualSmuDriver,
    VirtualSweepWorker,
)


def test_diode_is_monotonic_and_compliance_changes_actual_voltage():
    diode = DiodeModel()
    readings = [
        diode.current(voltage, 0.001) for voltage in np.linspace(-0.2, 1.5, 100)
    ]
    assert np.all(np.diff([row[1] for row in readings]) >= 0)
    voltage, current, limited = readings[-1]
    assert limited and current == 0.001 and voltage < 1.5
    assert readings[0][1] < 0 and not readings[0][2]


def test_seeded_gaussian_noise_is_reproducible_and_not_exact_curve():
    first, second = VirtualSmuDriver("A"), VirtualSmuDriver("A")
    noisy = [first.read(0.6, 0.01)[1] for _ in range(100)]
    assert noisy == [second.read(0.6, 0.01)[1] for _ in range(100)]
    exact = VirtualSmuDriver("A").read(0.6, 0.01, noise=False)[1]
    assert np.std(noisy) > 0 and np.mean(noisy) == pytest.approx(exact, rel=0.001)


def test_invalid_sweep_is_rejected_before_start():
    with pytest.raises(ValueError):
        VirtualSweepWorker(SweepConfig(start_v=1, stop_v=0))
    with pytest.raises(ValueError):
        DiodeModel().current(float("nan"), 0.01)


@pytest.mark.parametrize("close_method", ["close", "escape", "done"])
def test_virtual_three_channel_sweep_individual_plot_export_and_cancel(
    qt_application, tmp_path, close_method
):
    dialog = SmuDemoDialog()
    dialog.points.setValue(41)
    dialog.show()
    try:
        dialog.start_sweep()
        deadline = time.monotonic() + 5
        while dialog.worker is not None and time.monotonic() < deadline:
            qt_application.processEvents()
            time.sleep(0.002)
        assert dialog.worker is None
        assert all(len(rows) == 41 for rows in dialog.rows.values())
        dialog.channel.setCurrentText("B")
        assert dialog.curves["B"].isVisible() and not dialog.curves["A"].isVisible()
        output = tmp_path / "virtual.csv"
        dialog.write_csv(output)
        with output.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 123 and all(
            row["source"].startswith("SIM::") for row in rows
        )
        assert any(row["compliance_active"] == "1" for row in rows)
        dialog.points.setValue(5000)
        dialog.start_sweep()
        if close_method == "escape":
            QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
        elif close_method == "done":
            dialog.done(0)
        else:
            dialog.close()
        deadline = time.monotonic() + 3
        while dialog.worker is not None and time.monotonic() < deadline:
            qt_application.processEvents()
            time.sleep(0.002)
        assert dialog.worker is None
    finally:
        if dialog.worker is not None:
            dialog.worker.stop()
            assert dialog.worker.wait(3000)
        if isValid(dialog):
            dialog.close()
