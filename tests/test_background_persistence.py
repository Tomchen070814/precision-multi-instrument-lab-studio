import csv
import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtTest, QtWidgets

import hp3458a_studio.main_window as main_window_module
from hp3458a_studio.csv_io import read_measurement_csv, write_session_csv
from hp3458a_studio.main_window import MainWindow
from hp3458a_studio.models import Measurement
from hp3458a_studio.persistence import (
    BackgroundSessionWriter,
    DurableSessionWriter,
    PersistenceBackpressureError,
    list_recovery_files,
)


def _storage(tmp_path):
    return DurableSessionWriter(
        channel="A", instrument_model="3458A", resource="SIM::A", root=tmp_path
    )


def _wait_until(predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        if predicate():
            return True
        QtTest.QTest.qWait(10)
    return predicate()


def test_slow_disk_does_not_block_submission_and_queue_is_bounded(tmp_path):
    storage = _storage(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    sync = storage._sync

    def slow_sync():
        entered.set()
        assert release.wait(5)
        sync()

    storage._sync = slow_sync
    writer = BackgroundSessionWriter(storage, queue_capacity=4, batch_size=2)
    sample = Measurement(0, 10, "V")
    try:
        writer.append_many([sample, Measurement(1, 11, "V")])
        assert entered.wait(3)
        sample.value = 999
        writer.append_many([Measurement(2, 12, "V"), Measurement(3, 13, "V")])
        assert writer.count == writer.pending_count == 4
        assert writer.committed_count == 0
        with pytest.raises(PersistenceBackpressureError, match="queue full"):
            writer.append(Measurement(4, 14, "V"))
        assert writer.count == 4
        writer.request_finalize("stopped")
        assert not writer.finished
    finally:
        release.set()
        output = writer.finalize("stopped")
    assert writer.pending_count == 0
    assert writer.committed_count == 4
    np.testing.assert_array_equal(read_measurement_csv(output).values, [10, 11, 12, 13])


def test_background_batching_fsyncs_off_caller_thread_and_drains_every_row(tmp_path):
    storage = _storage(tmp_path)
    sync = storage._sync
    sync_threads = []

    def track_sync():
        sync_threads.append(threading.get_ident())
        sync()

    storage._sync = track_sync
    writer = BackgroundSessionWriter(storage, batch_size=128)
    writer.append_many(Measurement(index, index + 0.25, "V") for index in range(1000))
    output = writer.finalize("completed")
    assert writer.count == writer.committed_count == 1000
    assert writer.pending_count == 0
    assert 1 <= len(sync_threads) <= 9
    assert all(ident != threading.get_ident() for ident in sync_threads)
    np.testing.assert_array_equal(
        read_measurement_csv(output).values, np.arange(1000) + 0.25
    )
    metadata = json.loads(writer.metadata_path.read_text(encoding="utf-8"))
    assert metadata["samples"] == 1000
    assert "background batch" in metadata["durability"]


@pytest.mark.parametrize("failed_suffix", [".partial.csv", ".json.tmp"])
def test_background_finalize_can_retry_without_duplicate_rows(
    tmp_path, monkeypatch, failed_suffix
):
    writer = BackgroundSessionWriter(_storage(tmp_path))
    writer.append(Measurement(0, 10, "V"))
    rename = Path.replace
    failed = False

    def fail_once(path, target):
        nonlocal failed
        if str(path).endswith(failed_suffix) and not failed:
            failed = True
            raise OSError("temporary Windows file lock")
        return rename(path, target)

    monkeypatch.setattr(Path, "replace", fail_once)
    with pytest.raises(OSError, match="temporary Windows file lock"):
        writer.finalize("completed")
    assert writer.path.exists()
    output = writer.finalize("completed")
    np.testing.assert_array_equal(read_measurement_csv(output).values, [10])
    assert writer.finalize("completed") == output
    assert list_recovery_files(tmp_path) == []


@pytest.mark.parametrize("reading", [np.nan, np.inf, -np.inf, 9e36, -9.9e37])
def test_invalid_reading_never_enters_queue_or_journal(tmp_path, reading):
    writer = BackgroundSessionWriter(_storage(tmp_path))
    try:
        with pytest.raises(ValueError, match="Non-finite or overloaded"):
            writer.append_many([Measurement(0, 10, "V"), Measurement(1, reading, "V")])
        assert writer.count == 0
    finally:
        output = writer.finalize("stopped")
    with output.open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle)) == []


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(MainWindow, "_create_settings", staticmethod(lambda: settings))
    monkeypatch.setattr(
        main_window_module, "default_autosave_root", lambda: tmp_path / "autosave"
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *args: None)
    result = MainWindow()
    yield result
    result._stop_all()
    assert _wait_until(lambda: not any(c.running for c in result.channels.values()))
    result.close()
    assert _wait_until(lambda: result._shutdown_complete)
    result.deleteLater()
    app.processEvents()


def test_gui_close_and_restart_wait_for_durable_drain_while_events_keep_running(
    window, monkeypatch
):
    entered = threading.Event()
    release = threading.Event()

    class SlowWriter(DurableSessionWriter):
        def _sync(self):
            if self.count:
                entered.set()
                assert release.wait(5)
            super()._sync()

    monkeypatch.setattr(main_window_module, "DurableSessionWriter", SlowWriter)
    config = replace(
        window.panels["A"].read_config(), max_samples=3, sample_interval_s=0.001
    )
    ticks = []
    timer = QtCore.QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        assert window._start_channel("A", config)
        assert _wait_until(lambda: entered.is_set())
        runtime = window.channels["A"]
        assert _wait_until(lambda: runtime.worker is None)
        writer = runtime.durable_writer
        assert runtime.running
        assert len(runtime.session) == writer.count == 3
        assert not window._start_channel("A", config)
        assert runtime.durable_writer is writer
        window.close()
        assert window._shutdown_in_progress
        assert not window._shutdown_complete
        tick_count = len(ticks)
        assert _wait_until(lambda: len(ticks) >= tick_count + 3)
        assert not window._shutdown_complete
    finally:
        release.set()
        timer.stop()
    assert _wait_until(lambda: window._shutdown_complete)
    assert writer.committed_count == 3
    assert read_measurement_csv(runtime.last_autosave_path).values.size == 3


def test_background_disk_failure_preserves_session_for_export_and_reports_pending(
    window, monkeypatch, tmp_path
):
    fail_after_acceptance = threading.Event()

    class FailingWriter(DurableSessionWriter):
        def _sync(self):
            if self.count:
                assert fail_after_acceptance.wait(5)
                raise OSError("simulated disk full")
            super()._sync()

    monkeypatch.setattr(main_window_module, "DurableSessionWriter", FailingWriter)
    config = replace(
        window.panels["A"].read_config(), max_samples=3, sample_interval_s=0.001
    )
    assert window._start_channel("A", config)
    runtime = window.channels["A"]
    try:
        assert _wait_until(lambda: len(runtime.session) == 3)
    finally:
        fail_after_acceptance.set()
    assert _wait_until(lambda: not runtime.running)
    assert len(runtime.session) == 3
    assert runtime.state == "采集错误"
    assert "simulated disk full" in runtime.autosave_error
    assert "accepted=3" in runtime.autosave_error
    assert "fsync_confirmed=0" in runtime.autosave_error
    assert "pending=3" in runtime.autosave_error
    assert list_recovery_files(window.autosave_root)
    previous_error = runtime.error
    window._worker_recovered("A")
    assert runtime.error == previous_error
    exported = tmp_path / "manual-export.csv"
    write_session_csv(exported, runtime.session)
    np.testing.assert_array_equal(
        read_measurement_csv(exported).values, runtime.session.y
    )
