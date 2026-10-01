import threading

import pytest
from PySide6 import QtCore

from hp3458a_studio.drivers import (
    AcquisitionConfig,
    InstrumentDriver,
    InstrumentError,
    InstrumentIdentity,
    MeasurementFunction,
    SimulatorDriver,
)
from hp3458a_studio.workers import BurstAcquisitionWorker, PrecisionAcquisitionWorker


def _wait_for(worker, timeout_ms=3000):
    assert worker.wait(timeout_ms), "acquisition worker did not finish in time"
    application = QtCore.QCoreApplication.instance()
    if application is not None:
        application.processEvents()


def test_precision_worker_finishes_at_exact_sample_target():
    application = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    config = AcquisitionConfig(sample_interval_s=0.001, max_samples=7)
    worker = PrecisionAcquisitionWorker(
        SimulatorDriver(config, seed=1),
        config,
        temperature_interval_s=100.0,
    )

    worker.start()
    _wait_for(worker)

    assert worker.completed_target
    assert worker.samples_acquired == 7
    assert application is not None


def test_two_workers_finish_independent_targets_after_shared_release():
    application = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    gate = threading.Event()
    config_a = AcquisitionConfig(sample_interval_s=0.001, max_samples=5)
    config_b = AcquisitionConfig(sample_interval_s=0.001, max_samples=9)
    worker_a = PrecisionAcquisitionWorker(
        SimulatorDriver(config_a, seed=2, resource_name="SIM::3458A::A"),
        config_a,
        start_gate=gate,
    )
    worker_b = PrecisionAcquisitionWorker(
        SimulatorDriver(config_b, seed=3, resource_name="SIM::3458A::B"),
        config_b,
        start_gate=gate,
    )

    worker_a.start()
    worker_b.start()
    gate.set()
    _wait_for(worker_a)
    _wait_for(worker_b)

    assert worker_a.completed_target
    assert worker_b.completed_target
    assert worker_a.samples_acquired == 5
    assert worker_b.samples_acquired == 9
    assert application is not None


class _BlockingDriver(InstrumentDriver):
    """Model a VISA read that only session cancellation can release."""

    def __init__(self):
        super().__init__()
        self.read_started = threading.Event()
        self.cancelled = threading.Event()
        self.cancel_calls = 0

    def connect(self):
        self.connected = True
        self.identity = InstrumentIdentity("3458A TEST", "GPIB0::1::INSTR")
        return self.identity

    def configure(self, config):
        self.config = config

    def read_single(self, include_temperature=False):
        self.read_started.set()
        self.cancelled.wait(5)
        raise InstrumentError("session closed")

    def cancel_pending_io(self):
        self.cancel_calls += 1
        self.cancelled.set()


def test_stop_cancels_blocking_driver_io_without_reporting_failure():
    application = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    driver = _BlockingDriver()
    worker = PrecisionAcquisitionWorker(
        driver,
        AcquisitionConfig(sample_interval_s=1.0),
    )
    failures = []
    worker.failed.connect(failures.append)

    worker.start()
    assert driver.read_started.wait(1)
    worker.request_stop()
    _wait_for(worker, timeout_ms=1000)

    assert driver.cancel_calls == 1
    assert failures == []
    assert application is not None


def _worker_for(driver, mode):
    if mode == "precision":
        return PrecisionAcquisitionWorker(driver, AcquisitionConfig(max_samples=1))
    return BurstAcquisitionWorker(
        driver, 16, 0.001, 0.0001, MeasurementFunction.DIGITIZE_DC, "10"
    )


class _CountingDriver(_BlockingDriver):
    def __init__(self):
        super().__init__()
        self.connect_calls = 0
        self.configure_calls = 0
        self.capture_calls = 0
        self.disconnect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return super().connect()

    def configure(self, config):
        self.configure_calls += 1
        super().configure(config)

    def acquire_burst(self, **kwargs):
        self.capture_calls += 1
        raise TypeError("capture decoding failed")

    def disconnect(self):
        self.disconnect_calls += 1
        super().disconnect()


@pytest.mark.parametrize("mode", ["precision", "burst"])
def test_stop_before_start_never_connects_or_configures(mode):
    driver = _CountingDriver()
    worker = _worker_for(driver, mode)
    worker.request_stop()
    worker.run()
    assert driver.connect_calls == 0
    assert driver.configure_calls == 0
    assert driver.capture_calls == 0
    assert driver.disconnect_calls == 1


@pytest.mark.parametrize("mode", ["precision", "burst"])
def test_stop_during_connect_never_configures_or_captures(mode):
    driver = _CountingDriver()
    worker = _worker_for(driver, mode)
    connect = driver.connect

    def cancelled_connect():
        identity = connect()
        worker.request_stop()
        return identity

    driver.connect = cancelled_connect
    worker.run()
    assert driver.connect_calls == 1
    assert driver.configure_calls == 0
    assert driver.capture_calls == 0
    assert driver.disconnect_calls == 1


def test_burst_internal_type_error_does_not_repeat_capture():
    driver = _CountingDriver()
    worker = _worker_for(driver, "burst")
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert driver.capture_calls == 1
    assert failures == ["capture decoding failed"]
    assert driver.disconnect_calls == 1


def test_burst_connect_type_error_is_classified_without_capture():
    driver = _CountingDriver()
    worker = _worker_for(driver, "burst")
    issues = []
    worker.connection_issue.connect(issues.append)

    def broken_connect():
        raise TypeError("connection failed")

    driver.connect = broken_connect
    worker.run()
    assert len(issues) == 1
    assert driver.capture_calls == 0


@pytest.mark.parametrize("mode", ["precision", "burst"])
def test_cancellation_and_cleanup_errors_still_emit_stopped(mode):
    driver = _CountingDriver()
    worker = _worker_for(driver, mode)
    stopped = []
    worker.stopped.connect(lambda: stopped.append(True))

    def broken_cleanup():
        raise RuntimeError("vendor cleanup failed")

    driver.cancel_pending_io = broken_cleanup
    driver.disconnect = broken_cleanup
    worker.request_stop()
    worker.run()
    assert stopped == [True]


def test_three_workers_complete_independent_targets_after_shared_release():
    application = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    gate = threading.Event()
    workers = []
    for channel, target in zip("ABC", (3, 5, 7), strict=True):
        config = AcquisitionConfig(sample_interval_s=0.001, max_samples=target)
        worker = PrecisionAcquisitionWorker(
            SimulatorDriver(config, resource_name=f"SIM::3458A::{channel}"),
            config,
            start_gate=gate,
        )
        workers.append(worker)
        worker.start()
    gate.set()
    for worker, target in zip(workers, (3, 5, 7), strict=True):
        _wait_for(worker)
        assert worker.completed_target
        assert worker.samples_acquired == target
    assert application is not None
