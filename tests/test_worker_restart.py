import threading

import numpy as np
import pytest
from PySide6 import QtCore

from hp3458a_studio import drivers as driver_module
from hp3458a_studio.csv_io import read_measurement_csv
from hp3458a_studio.drivers import AcquisitionConfig, ScpiDmmDriver
from hp3458a_studio.models import InstrumentModel, MeasurementFunction, SessionData
from hp3458a_studio.persistence import DurableSessionWriter
from hp3458a_studio.workers import PrecisionAcquisitionWorker


class _ScpiResource:
    def __init__(self):
        self.closed = False
        self.last_command = ""
        self.function = "VOLT:DC"
        self.commands = []

    def write(self, command):
        if self.closed:
            raise RuntimeError("VISA resource was closed")
        self.commands.append(command)
        self.last_command = command
        if command.startswith("CONF:"):
            self.function = command.removeprefix("CONF:")

    def read(self):
        if self.closed:
            raise RuntimeError("VISA resource was closed")
        if self.last_command == "*IDN?":
            return "KEYSIGHT TECHNOLOGIES,34470A,TEST,A.03.03"
        if self.last_command == "SYST:LFREQ?":
            return "50"
        if self.last_command == "SYST:ERR?":
            return '+0,"No error"'
        if self.last_command == "READ?":
            return {
                "VOLT:DC": "10.123456789012345",
                "CURR:DC": "0.0123456789012345",
                "FRES": "1234.56789012345",
            }[self.function]
        raise AssertionError(f"Unexpected query: {self.last_command}")

    def close(self):
        self.closed = True


class _CachedVisaManager:
    def __init__(self):
        self.resources = []
        self.close_calls = 0

    def open_resource(self, _name):
        resource = _ScpiResource()
        self.resources.append(resource)
        return resource

    def close(self):
        self.close_calls += 1
        for resource in self.resources:
            resource.close()


class _Capture:
    def __init__(self, root, channel, run_id):
        self.session = SessionData()
        self.writer = DurableSessionWriter(
            root=root,
            channel=channel,
            instrument_model="34470A",
            resource=f"USB0::{channel}::INSTR",
            run_id=run_id,
        )
        self.changed = threading.Condition()
        self.errors = []

    def receive(self, reading):
        with self.changed:
            try:
                self.writer.append(reading)
                self.session.append(reading)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                self.errors.append(exc)
            self.changed.notify_all()

    def wait_for_samples(self, count):
        with self.changed:
            assert self.changed.wait_for(
                lambda: len(self.session) >= count or self.errors, timeout=5
            ), "channel stopped producing samples"
            assert not self.errors


@pytest.mark.parametrize(
    ("function", "command", "value"),
    [
        (MeasurementFunction.DC_CURRENT, "CONF:CURR:DC", 0.0123456789012345),
        (MeasurementFunction.RESISTANCE_4W, "CONF:FRES", 1234.56789012345),
    ],
)
def test_one_channel_can_restart_with_new_function_while_peers_keep_sampling(
    tmp_path, monkeypatch, function, command, value
):
    application = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    manager = _CachedVisaManager()
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    workers = []
    captures = {}
    all_captures = []
    failures = []

    def start(channel, run_id, config):
        capture = _Capture(tmp_path, channel, run_id)
        all_captures.append(capture)
        driver = ScpiDmmDriver(
            f"USB0::{channel}::INSTR", InstrumentModel.KEYSIGHT_34470A, config
        )
        worker = PrecisionAcquisitionWorker(driver, config)
        worker.measurement_ready.connect(
            capture.receive, QtCore.Qt.ConnectionType.DirectConnection
        )
        worker.failed.connect(
            failures.append, QtCore.Qt.ConnectionType.DirectConnection
        )
        worker.connection_issue.connect(
            failures.append, QtCore.Qt.ConnectionType.DirectConnection
        )
        workers.append(worker)
        worker.start()
        return worker, capture

    try:
        config = AcquisitionConfig(sample_interval_s=0.005)
        for channel in "ABC":
            worker, capture = start(channel, f"first-{channel}", config)
            captures[channel] = capture
        for capture in captures.values():
            capture.wait_for_samples(3)

        first_a = workers[0]
        first_a.request_stop()
        assert first_a.wait(5000)
        original_values = captures["A"].session.y.copy()
        original_count = len(captures["A"].session)
        first_output = captures["A"].writer.finalize("stopped")
        peer_counts = {key: len(captures[key].session) for key in "BC"}
        assert manager.close_calls == 0

        new_config = AcquisitionConfig(
            function=function, sample_interval_s=0.001, max_samples=7
        )
        restarted_a, new_capture = start("A", "restarted-A", new_config)
        assert restarted_a.wait(5000)
        assert restarted_a.completed_target
        assert restarted_a.samples_acquired == 7
        assert new_capture.session.unit == function.unit
        np.testing.assert_array_equal(new_capture.session.y, np.full(7, value))
        assert new_capture.session.elapsed_s[0] < 1.0
        assert command in manager.resources[-1].commands
        assert not new_capture.errors

        for channel in "BC":
            captures[channel].wait_for_samples(peer_counts[channel] + 3)
            assert captures[channel].session.unit == "V"
        assert manager.close_calls == 0
        assert len(captures["A"].session) == original_count
        np.testing.assert_array_equal(captures["A"].session.y, original_values)

        restarted_output = new_capture.writer.finalize("completed")
        assert restarted_output != first_output
        first_imported = read_measurement_csv(first_output)
        restarted_imported = read_measurement_csv(restarted_output)
        assert first_imported.unit == "V"
        assert restarted_imported.unit == function.unit
        np.testing.assert_array_equal(first_imported.values, original_values)
        np.testing.assert_array_equal(restarted_imported.values, np.full(7, value))
        assert not failures
    finally:
        for worker in workers:
            if worker.isRunning():
                worker.request_stop()
        for worker in workers:
            assert worker.wait(5000)
        for capture in all_captures:
            capture.writer.finalize("stopped")
    assert manager.close_calls == 1
    assert application is not None
