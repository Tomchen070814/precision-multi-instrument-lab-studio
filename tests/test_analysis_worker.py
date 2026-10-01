import threading
import time

import numpy as np
import pytest
from PySide6 import QtCore

from hp3458a_studio import analysis_worker
from hp3458a_studio.analysis import allan_deviation, spectrum
from hp3458a_studio.analysis_worker import (
    AnalysisRequest,
    AnalysisWorker,
    calculate_analysis,
)


def request(signature=(1,), *, gap=False):
    x = np.arange(1024) * 0.1
    if gap:
        x[512:] += 5.0
    y = 1 + 1e-3 * np.sin(np.arange(1024) * 0.2)
    return AnalysisRequest(
        signature, "A", {"A": (x, y, np.full(1024, np.nan), "V")}, False, 5, False
    )


def wait_until(application, predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        application.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    pytest.fail("Background calculation did not complete")


def test_background_results_match_scientific_calculations():
    job = request()
    data = calculate_analysis(job)["channels"]["A"]
    expected = spectrum(job.arrays["A"][1], 0.1)
    np.testing.assert_allclose(data["spectrum"]["amplitude"], expected["amplitude"])
    tau, deviation = allan_deviation(job.arrays["A"][1], 0.1)
    np.testing.assert_allclose(data["allan"][0], tau)
    np.testing.assert_allclose(data["allan"][1], deviation)
    assert data["stats"].count == 1024
    assert sum(data["histogram"][1]) == 1024


def test_reconnect_gaps_do_not_produce_misleading_spectra():
    data = calculate_analysis(request(gap=True))["channels"]["A"]
    assert data["gaps"]
    assert "spectrum" not in data and "allan" not in data
    assert "drift" in data and data["stats"].count == 1024


def test_slow_analysis_keeps_gui_timer_alive_and_coalesces_pending(
    qt_application, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    original = analysis_worker.calculate_analysis
    calls = []

    def slow(job):
        calls.append(job.signature)
        if job.signature == (1,):
            entered.set()
            assert release.wait(3)
        return original(job)

    monkeypatch.setattr(analysis_worker, "calculate_analysis", slow)
    worker = AnalysisWorker()
    results, ticks = [], []
    worker.completed.connect(results.append)
    timer = QtCore.QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        worker.submit(request())
        wait_until(qt_application, entered.is_set)
        worker.submit(request((2,)))
        worker.submit(request((3,)))
        wait_until(qt_application, lambda: len(ticks) >= 5)
        assert not results
        release.set()
        wait_until(qt_application, lambda: len(results) == 2)
        assert calls == [(1,), (3,)]
    finally:
        timer.stop()
        release.set()
        worker.stop()
        assert worker.wait(3000)
