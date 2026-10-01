import math
import threading

import numpy as np
import pytest
from pyvisa.constants import StatusCode
from pyvisa.errors import VisaIOError

import hp3458a_studio.drivers as driver_module
import hp3458a_studio.workers as worker_module
from hp3458a_studio.drivers import (
    AcquisitionConfig,
    Fluke8508ADriver,
    InstrumentError,
    Keysight3458ADriver,
    Keysight34470ADriver,
    SimulatorDriver,
)
from hp3458a_studio.workers import PrecisionAcquisitionWorker


class _Clock:
    """Model Windows 3.11's coarse clock with a separate precise QPC origin."""

    def __init__(self):
        self.elapsed = 0.0
        self.coarse_reads = 0

    def monotonic(self):
        self.coarse_reads += 1
        return 7000.0 + math.floor(self.elapsed / 0.016) * 0.016

    def perf_counter(self):
        return 100.0 + self.elapsed

    def sleep(self, duration):
        self.elapsed += duration


class _ClockEvent(threading.Event):
    def __init__(self, clock, on_wait=None):
        super().__init__()
        self.clock = clock
        self.on_wait = on_wait
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.on_wait is not None:
            self.on_wait(timeout)
        if not self.is_set():
            self.clock.sleep(timeout or 0)
        return self.is_set()


@pytest.fixture
def clock(monkeypatch):
    result = _Clock()
    # Replace only the acquisition modules' bindings; GUI/test deadlines keep
    # their real clock and no native window is touched.
    monkeypatch.setattr(driver_module, "time", result)
    monkeypatch.setattr(worker_module, "time", result)
    return result


class _FaultSimulator(SimulatorDriver):
    def __init__(self, config):
        super().__init__(config)
        self.connects = 0
        self.reads = 0

    def connect(self):
        self.connects += 1
        return super().connect()

    def read_single(self, include_temperature=False):
        self.reads += 1
        if self.reads == 2:
            try:
                raise VisaIOError(StatusCode.error_timeout)
            except VisaIOError as exc:
                raise InstrumentError("Read timed out") from exc
        return super().read_single(include_temperature)


def test_millisecond_samples_and_reconnect_gap_use_precise_shared_origin(clock):
    config = AcquisitionConfig(sample_interval_s=0.001, max_samples=3)
    driver = _FaultSimulator(config)
    worker = PrecisionAcquisitionWorker(driver, config, reconnect_delays_s=(0.003,))
    event = _ClockEvent(clock)
    worker._stop_event = event
    samples, failures = [], []
    worker.measurement_ready.connect(samples.append)
    worker.failed.connect(failures.append)
    worker.run()

    np.testing.assert_allclose(
        [sample.elapsed_s for sample in samples], [0, 0.004, 0.005], atol=1e-12
    )
    assert np.all(np.diff([sample.elapsed_s for sample in samples]) > 0)
    np.testing.assert_allclose(event.waits, [0.001, 0.003, 0.001], atol=1e-12)
    assert driver.started_at == 100.0
    assert driver.connects == 2 and worker.reconnect_attempts == 1
    assert worker.completed_target and worker.samples_acquired == 3
    assert clock.coarse_reads == 0 and failures == []


def test_cancel_reconnect_backoff_does_not_depend_on_coarse_clock(clock):
    config = AcquisitionConfig(sample_interval_s=0.001, max_samples=3)
    driver = _FaultSimulator(config)
    worker = PrecisionAcquisitionWorker(driver, config, reconnect_delays_s=(30.0,))

    def cancel_backoff(timeout):
        if timeout == 30.0:
            worker.request_stop()

    worker._stop_event = _ClockEvent(clock, cancel_backoff)
    samples, failures = [], []
    worker.measurement_ready.connect(samples.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert len(samples) == worker.samples_acquired == 1
    assert driver.connects == 1 and not worker.completed_target
    assert worker.reconnect_attempts == 1 and failures == []
    assert clock.elapsed == pytest.approx(0.001)
    assert clock.coarse_reads == 0


class _Resource:
    def __init__(self, model):
        self.model = model
        self.command = ""
        self.closed = False

    def clear(self):
        pass

    def write(self, command):
        self.command = command

    def read(self):
        return {
            "ID?": "HEWLETT-PACKARD,3458A",
            "*IDN?": self.model,
            "REV?": "9.2,9.1",
            "OPT?": "1",
            "LINE?": "50",
            "MCOUNT?": "0",
        }.get(self.command, "1.00001")

    def close(self):
        self.closed = True


class _Manager:
    def __init__(self, instrument):
        self.instrument = instrument

    def open_resource(self, resource):
        return self.instrument

    def close(self):
        pass


@pytest.mark.parametrize("model", ["sim", "3458A", "34470A", "8508A"])
def test_every_driver_uses_same_precise_clock_for_connect_and_read(
    clock, monkeypatch, model
):
    if model == "sim":
        driver = SimulatorDriver()
    else:
        constructors = {
            "3458A": Keysight3458ADriver,
            "34470A": Keysight34470ADriver,
            "8508A": Fluke8508ADriver,
        }
        vendor = "FLUKE" if model == "8508A" else "KEYSIGHT"
        instrument = _Resource(f"{vendor},{model},1234,1.0")
        manager = _Manager(instrument)
        monkeypatch.setattr(driver_module.pyvisa, "ResourceManager", lambda _: manager)
        driver = constructors[model]("GPIB0::21::INSTR")
    try:
        driver.connect()
        assert driver.started_at == 100.0
        clock.sleep(0.001)
        first = driver.read_single()
        clock.sleep(0.001)
        second = driver.read_single()
        assert first.elapsed_s == pytest.approx(0.001, abs=1e-12)
        assert second.elapsed_s == pytest.approx(0.002, abs=1e-12)
        assert second.elapsed_s > first.elapsed_s
        assert clock.coarse_reads == 0
    finally:
        driver.disconnect()


def test_burst_completion_deadline_uses_precise_clock(clock, monkeypatch):
    instrument = _Resource("HEWLETT-PACKARD,3458A")
    instrument.read_termination = "\n"
    manager = _Manager(instrument)
    monkeypatch.setattr(driver_module.pyvisa, "ResourceManager", lambda _: manager)
    driver = Keysight3458ADriver("GPIB0::21::INSTR")
    try:
        driver.connect()
        with pytest.raises(InstrumentError, match="0/16"):
            driver.acquire_burst(16, 0.0001, 0.00001)
        assert clock.elapsed == pytest.approx(10.2516, abs=0.051)
        assert clock.coarse_reads == 0
    finally:
        driver.disconnect()
