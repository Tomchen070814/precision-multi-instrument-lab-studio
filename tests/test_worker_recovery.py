import threading
import time

import numpy as np
import pytest
from PySide6 import QtCore
from pyvisa.constants import StatusCode
from pyvisa.errors import VisaIOError

import hp3458a_studio.drivers as driver_module
from hp3458a_studio.drivers import (
    AcquisitionConfig,
    InstrumentDriver,
    InstrumentError,
    InstrumentIdentity,
    Keysight3458ADriver,
)
from hp3458a_studio.models import Measurement, MeasurementFunction
from hp3458a_studio.workers import BurstAcquisitionWorker, PrecisionAcquisitionWorker


def _wrapped_visa_error(code):
    try:
        raise VisaIOError(code)
    except VisaIOError as exc:
        try:
            raise InstrumentError(f"Instrument read failed: {exc}") from exc
        except InstrumentError as error:
            return error


class _ScriptedDriver(InstrumentDriver):
    def __init__(self, readings, connects=()):
        super().__init__()
        self.readings = list(readings)
        self.connects = list(connects)
        self.resource_name = "GPIB0::21::INSTR"
        self.connect_calls = 0
        self.configure_calls = 0
        self.cancel_calls = 0
        self.disconnect_calls = 0
        self.recovery_started = threading.Event()

    def connect(self):
        self.connect_calls += 1
        if self.connects:
            effect = self.connects.pop(0)
            if isinstance(effect, Exception):
                raise effect
        self.connected = True
        self.started_at = time.monotonic()
        return InstrumentIdentity("3458A", self.resource_name)

    def configure(self, config):
        self.configure_calls += 1
        self.config = config

    def read_single(self, include_temperature=False):
        effect = self.readings.pop(0)
        if isinstance(effect, Exception):
            raise effect
        if isinstance(effect, Measurement):
            return effect
        return Measurement(time.monotonic() - self.started_at, effect, "V")

    def cancel_pending_io(self):
        self.cancel_calls += 1
        self.recovery_started.set()

    def disconnect(self):
        self.disconnect_calls += 1
        super().disconnect()


def _worker(driver, target, delays=(0.003, 0.006)):
    return PrecisionAcquisitionWorker(
        driver,
        AcquisitionConfig(sample_interval_s=0.001, max_samples=target),
        reconnect_delays_s=delays,
    )


@pytest.mark.parametrize(
    "code",
    [
        StatusCode.error_timeout,
        StatusCode.error_connection_lost,
        StatusCode.error_io,
        StatusCode.error_no_listeners,
        StatusCode.error_resource_not_found,
        StatusCode.error_invalid_object,
    ],
)
def test_wrapped_visa_failure_reconnects_same_capture_without_losing_samples(code):
    driver = _ScriptedDriver([10.0, _wrapped_visa_error(code), 11.0, 12.0])
    worker = _worker(driver, 3)
    samples, failures, recoveries, recovered = [], [], [], []
    worker.measurement_ready.connect(samples.append)
    worker.failed.connect(failures.append)
    worker.recovering.connect(lambda *event: recoveries.append(event))
    worker.recovered.connect(lambda: recovered.append(True))
    worker.run()

    assert [sample.value for sample in samples] == [10, 11, 12]
    assert np.all(np.diff([sample.elapsed_s for sample in samples]) > 0)
    assert samples[1].elapsed_s - samples[0].elapsed_s >= 0.003
    assert worker.completed_target and worker.samples_acquired == 3
    assert driver.connect_calls == driver.configure_calls == 2
    assert driver.disconnect_calls == 2
    assert len(recoveries) == len(recovered) == 1
    assert failures == []


def test_initial_connect_and_reconnect_failures_use_backoff_then_recover():
    driver = _ScriptedDriver(
        [1.0],
        [_wrapped_visa_error(StatusCode.error_timeout), ConnectionError("unplugged")],
    )
    worker = _worker(driver, 1)
    issues, failures, attempts = [], [], []
    worker.connection_issue.connect(issues.append)
    worker.failed.connect(failures.append)
    worker.recovering.connect(lambda attempt, delay, error: attempts.append(attempt))
    worker.run()
    assert driver.connect_calls == 3
    assert attempts == [1, 2]
    assert worker.completed_target and worker.samples_acquired == 1
    assert issues == failures == []


def test_recovery_budget_resets_only_after_a_valid_sample():
    timeout = _wrapped_visa_error(StatusCode.error_timeout)
    driver = _ScriptedDriver([1.0, timeout, timeout, timeout])
    worker = _worker(driver, 2, delays=(0, 0))
    samples, failures = [], []
    worker.measurement_ready.connect(samples.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert [sample.value for sample in samples] == [1]
    assert driver.connect_calls == 3
    assert worker.reconnect_attempts == 2
    assert not worker.completed_target and worker.samples_acquired == 1
    assert len(failures) == 1 and "exhausted after 2 attempts" in failures[0]


def test_separate_outages_get_a_new_budget_after_valid_samples():
    timeout = _wrapped_visa_error(StatusCode.error_timeout)
    driver = _ScriptedDriver([1.0, timeout, 2.0, timeout, 3.0])
    worker = _worker(driver, 3, delays=(0,))
    worker.run()
    assert worker.completed_target and worker.samples_acquired == 3
    assert worker.reconnect_attempts == 2


@pytest.mark.parametrize(
    "error",
    [
        InstrumentError("Timeout option invalid; ERR=123"),
        _wrapped_visa_error(StatusCode.error_invalid_parameter),
        ValueError("bad range"),
    ],
)
def test_configuration_and_data_errors_do_not_reconnect(error):
    driver = _ScriptedDriver([error])
    worker = _worker(driver, 1)
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert driver.connect_calls == 1
    assert worker.samples_acquired == 0
    assert len(failures) == 1


def test_instrument_configuration_error_does_not_retry_or_take_a_reading():
    driver = _ScriptedDriver([1.0])

    def bad_config(config):
        raise InstrumentError("3458A configuration error ERR=123")

    driver.configure = bad_config
    worker = _worker(driver, 1)
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert driver.connect_calls == 1 and worker.reconnect_attempts == 0
    assert driver.readings == [1.0] and worker.samples_acquired == 0
    assert len(failures) == 1


def test_failed_initial_connections_exhaust_budget_and_report_one_diagnostic():
    driver = _ScriptedDriver([], connects=[TimeoutError("read timed out")] * 3)
    worker = _worker(driver, 1, delays=(0, 0))
    issues, failures = [], []
    worker.connection_issue.connect(issues.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert driver.connect_calls == 3 and worker.reconnect_attempts == 2
    assert len(issues) == 1 and failures == []
    assert worker.samples_acquired == 0


def _finish(worker, timeout=1000):
    try:
        assert worker.wait(timeout)
    finally:
        if worker.isRunning():
            worker.request_stop()
            worker.wait(3000)
    application = QtCore.QCoreApplication.instance()
    if application is not None:
        application.processEvents()


def test_stop_interrupts_long_backoff_and_other_channel_keeps_acquiring():
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    driver = _ScriptedDriver([ConnectionError("USB disconnected")])
    worker = _worker(driver, 1, delays=(30,))
    peer = _worker(_ScriptedDriver(range(5)), 5)
    failures = []
    worker.failed.connect(failures.append)
    worker.start()
    assert driver.recovery_started.wait(1)
    peer.start()
    _finish(peer)
    assert worker.isRunning()
    worker.request_stop()
    _finish(worker)
    assert peer.completed_target and peer.samples_acquired == 5
    assert driver.connect_calls == 1
    assert worker.samples_acquired == 0 and failures == []
    assert app is not None


def test_stop_cancels_reconnect_io_before_configuring_again():
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    driver = _ScriptedDriver([ConnectionError("connection lost")])
    reconnect_started, cancel = threading.Event(), threading.Event()
    connect = driver.connect

    def blocking_reconnect():
        if driver.connect_calls == 1:
            reconnect_started.set()
            cancel.wait(3)
        return connect()

    driver.connect = blocking_reconnect
    original_cancel = driver.cancel_pending_io

    def cancel_reconnect():
        original_cancel()
        if reconnect_started.is_set():
            cancel.set()

    driver.cancel_pending_io = cancel_reconnect
    worker = _worker(driver, 1, delays=(0,))
    failures = []
    worker.failed.connect(failures.append)
    worker.start()
    assert reconnect_started.wait(1)
    worker.request_stop()
    _finish(worker)
    assert driver.connect_calls == 2 and driver.configure_calls == 1
    assert failures == []
    assert app is not None


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf, 9.9e37, -9.9e37])
def test_nonfinite_and_overflow_readings_are_never_emitted(value):
    driver = _ScriptedDriver([1.0, value, 2.0])
    worker = _worker(driver, 3)
    samples, failures = [], []
    worker.measurement_ready.connect(samples.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert [sample.value for sample in samples] == [1]
    assert worker.samples_acquired == 1
    assert worker.reconnect_attempts == 0
    assert len(failures) == 1 and "Invalid/overflow" in failures[0]


@pytest.mark.parametrize("elapsed", [np.nan, np.inf, -1.0])
def test_invalid_sample_time_is_never_emitted(elapsed):
    driver = _ScriptedDriver([Measurement(elapsed, 1.0, "V")])
    worker = _worker(driver, 1)
    samples, failures = [], []
    worker.measurement_ready.connect(samples.append)
    worker.failed.connect(failures.append)
    worker.run()
    assert samples == [] and worker.samples_acquired == 0
    assert len(failures) == 1 and "Invalid/overflow" in failures[0]


@pytest.mark.parametrize("value", [np.nan, np.inf, 9.9e37])
def test_invalid_burst_batch_is_never_emitted_or_retriggered(value):
    driver = _ScriptedDriver([])
    captures = []

    def burst(**kwargs):
        captures.append(kwargs)
        values = np.ones(16)
        values[5] = value
        return np.arange(16) * 0.001, values

    driver.acquire_burst = burst
    worker = BurstAcquisitionWorker(
        driver, 16, 0.001, 0.0001, MeasurementFunction.DIGITIZE_DC, "10"
    )
    batches, failures = [], []
    worker.result_ready.connect(lambda *batch: batches.append(batch))
    worker.failed.connect(failures.append)
    worker.run()
    assert len(captures) == 1 and batches == []
    assert len(failures) == 1 and "Invalid/overflow" in failures[0]


def test_burst_transport_error_does_not_repeat_unknown_hardware_capture():
    driver = _ScriptedDriver([])
    captures = []

    def burst(**kwargs):
        captures.append(kwargs)
        raise _wrapped_visa_error(StatusCode.error_timeout)

    driver.acquire_burst = burst
    worker = BurstAcquisitionWorker(
        driver, 16, 0.001, 0.0001, MeasurementFunction.DIGITIZE_DC, "10"
    )
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert len(captures) == 1 and driver.connect_calls == 1
    assert len(failures) == 1


def test_native_visa_driver_recovery_keeps_both_peer_sessions_open(monkeypatch):
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    class Resource:
        def __init__(self, resource, generation):
            self.resource = resource
            self.generation = generation
            self.command = ""
            self.closed = False
            self.samples = 0

        def clear(self):
            pass

        def write(self, command):
            if self.closed:
                raise VisaIOError(StatusCode.error_invalid_object)
            self.command = command

        def read(self):
            if self.closed:
                raise VisaIOError(StatusCode.error_invalid_object)
            if self.command == "TRIG SGL":
                self.samples += 1
                if (
                    self.resource == "GPIB0::21::INSTR"
                    and self.generation == 1
                    and self.samples == 2
                ):
                    raise VisaIOError(StatusCode.error_timeout)
                return "10.00001"
            return {
                "ID?": "HEWLETT-PACKARD,3458A",
                "REV?": "9.2,9.1",
                "OPT?": "1",
                "LINE?": "50",
                "ERR?": "0",
                "TEMP?": "23.5",
            }[self.command]

        def close(self):
            self.closed = True

    class Manager:
        def __init__(self):
            self.resources = []
            self.close_calls = 0

        def open_resource(self, name):
            generation = 1 + sum(item.resource == name for item in self.resources)
            resource = Resource(name, generation)
            self.resources.append(resource)
            return resource

        def close(self):
            self.close_calls += 1
            for resource in self.resources:
                resource.close()

    manager = Manager()
    monkeypatch.setattr(driver_module.pyvisa, "ResourceManager", lambda _: manager)
    peers = []
    failures, samples = [], []
    for address in (22, 23):
        config = AcquisitionConfig(sample_interval_s=0.005)
        peer = PrecisionAcquisitionWorker(
            Keysight3458ADriver(f"GPIB0::{address}::INSTR"),
            config,
            reconnect_delays_s=(0.003,),
        )
        peer.failed.connect(failures.append)
        peers.append(peer)
        peer.start()
    config = AcquisitionConfig(sample_interval_s=0.001, max_samples=3)
    worker = PrecisionAcquisitionWorker(
        Keysight3458ADriver("GPIB0::21::INSTR"),
        config,
        reconnect_delays_s=(0.003,),
    )
    worker.failed.connect(failures.append)
    worker.measurement_ready.connect(samples.append)
    try:
        deadline = time.monotonic() + 1
        while not all(peer.samples_acquired for peer in peers):
            assert time.monotonic() < deadline
            time.sleep(0.001)
        worker.start()
        _finish(worker)
        assert worker.completed_target and worker.reconnect_attempts == 1
        assert manager.close_calls == 0
        assert all(peer.isRunning() for peer in peers)
        deadline = time.monotonic() + 1
        while not all(peer.samples_acquired >= 10 for peer in peers):
            assert time.monotonic() < deadline
            time.sleep(0.001)
        for peer in peers:
            peer.request_stop()
            _finish(peer)
            assert peer.samples_acquired >= 10
    finally:
        for thread in [worker, *peers]:
            if thread.isRunning():
                thread.request_stop()
                thread.wait(3000)
    assert len(samples) == 3 and failures == []
    assert manager.close_calls == 1
    assert all(resource.closed for resource in manager.resources)
    assert app is not None
