import csv
import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtCore, QtTest, QtWidgets
except ImportError as exc:
    pytest.skip(str(exc), allow_module_level=True)

import hp3458a_studio.main_window as main_window_module
from hp3458a_studio.drivers import SimulatorDriver
from hp3458a_studio.main_window import MainWindow
from hp3458a_studio.models import InstrumentModel, Measurement, MeasurementFunction
from hp3458a_studio.persistence import DurableSessionWriter


def _wait_until(predicate, timeout_ms=2500):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50
        )
        if predicate():
            return True
        QtTest.QTest.qWait(10)
    return predicate()


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
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
    QtWidgets.QApplication.processEvents()


@pytest.mark.parametrize("failed_channel", ["A", "B", "C"])
def test_autosave_initialization_failure_cancels_three_channel_start(
    window, monkeypatch, failed_channel
):
    window.channel_c_enabled.setChecked(True)
    window.sync_channel_checks["C"].setChecked(True)
    window.channels[failed_channel].session.append(Measurement(0.0, 42.0, "V"))

    def make_writer(**kwargs):
        if kwargs["channel"] == failed_channel:
            raise OSError("disk unavailable")
        return DurableSessionWriter(**kwargs)

    monkeypatch.setattr(main_window_module, "DurableSessionWriter", make_writer)
    window._start_both()

    assert _wait_until(lambda: not any(c.running for c in window.channels.values()))
    assert window._group_gate is None
    assert window._group_pending == set()
    assert window._group_members == set()
    assert window.channels[failed_channel].state == "采集错误"
    assert window.channels[failed_channel].session.values == [42.0]
    assert all(
        not len(runtime.session)
        for channel, runtime in window.channels.items()
        if channel != failed_channel
    )
    assert all(c.durable_writer is None for c in window.channels.values())


def test_stopping_one_waiting_channel_cancels_its_startup_peers(window, monkeypatch):
    configured = threading.Event()
    release_configuration = threading.Event()

    class SlowConfigurationSimulator(SimulatorDriver):
        def configure(self, config):
            super().configure(config)
            configured.set()
            assert release_configuration.wait(2.0)

        def cancel_pending_io(self):
            release_configuration.set()

    original_make_driver = window._make_driver

    def make_driver(channel, config):
        if channel == "B":
            return SlowConfigurationSimulator(config)
        return original_make_driver(channel, config)

    monkeypatch.setattr(window, "_make_driver", make_driver)
    window._start_both()
    assert _wait_until(lambda: configured.is_set() and window._group_pending == {"B"})

    window._stop_channel("A")

    assert _wait_until(lambda: not any(c.running for c in window.channels.values()))
    assert window._group_gate is None
    assert window._group_pending == set()
    assert not len(window.channels["A"].session)
    assert not len(window.channels["B"].session)


def test_shutdown_drains_queued_sample_before_finalizing_once(window, monkeypatch):
    finalized = []

    class CountingWriter(DurableSessionWriter):
        def finalize(self, status, error=""):
            finalized.append((self.channel, status, self.count))
            return super().finalize(status, error)

    monkeypatch.setattr(main_window_module, "DurableSessionWriter", CountingWriter)
    panel = window.panels["A"]
    panel.precision_length_combo.setCurrentIndex(
        panel.precision_length_combo.findData("fixed")
    )
    panel.precision_count.setValue(1)
    window._toggle_channel("A")
    worker = window.channels["A"].worker
    assert worker.wait(2500)
    assert not worker.isRunning()
    assert window.channels["A"].running
    assert not len(window.channels["A"].session)

    # A second start request during queued delivery must retain the first run.
    window._toggle_channel("A")
    assert window.channels["A"].worker is worker
    window.close()
    assert window._shutdown_in_progress
    assert not window._shutdown_complete
    assert _wait_until(lambda: window._shutdown_complete)

    assert window.channels["A"].worker is None
    assert len(window.channels["A"].session) == 1
    assert finalized == [("A", "completed", 1)]
    capture = Path(window.channels["A"].last_autosave_path)
    with capture.open(newline="", encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 1
    assert json.loads(capture.with_suffix(".json").read_text())["samples"] == 1


def test_stale_worker_events_do_not_reach_a_new_capture(window):
    old_worker = object()
    new_worker = object()
    calls = []
    window.channels["A"].worker = new_worker
    try:
        window._dispatch_worker_event(
            "A", old_worker, lambda channel, sample: calls.append((channel, sample)), 1
        )
        assert calls == []
        window._dispatch_worker_event(
            "A", new_worker, lambda channel, sample: calls.append((channel, sample)), 2
        )
        assert calls == [("A", 2)]
    finally:
        window.channels["A"].worker = None


def test_device_tabs_select_individual_data_statistics_and_units(window):
    window.channel_c_enabled.setChecked(True)
    examples = (
        ("A", InstrumentModel.KEYSIGHT_3458A, MeasurementFunction.DC_VOLTAGE, "V", 1.0),
        (
            "B",
            InstrumentModel.KEYSIGHT_34470A,
            MeasurementFunction.RESISTANCE_4W,
            "Ω",
            100.0,
        ),
        ("C", InstrumentModel.FLUKE_8846A, MeasurementFunction.DC_CURRENT, "A", 0.01),
    )
    for channel, model, function, unit, value in examples:
        panel = window.panels[channel]
        panel.model_combo.setCurrentIndex(panel.model_combo.findData(model.value))
        panel.function_combo.setCurrentIndex(
            panel.function_combo.findData(function.value)
        )
        for index in range(8):
            window.channels[channel].session.append(
                Measurement(index * 0.1, value + index * value * 1e-6, unit)
            )
    window._refresh_views()
    assert window.analysis_channels == ("A", "B", "C")

    for channel, model, function, unit, _value in examples[1:]:
        window.device_tabs.setCurrentIndex(window.CHANNELS.index(channel))
        assert window.selected_channel == channel
        assert window.analysis_channels == (channel,)
        assert not window.multi_analysis_check.isChecked()
        assert window.session_unit.text() == unit
        assert (
            f"{model.short_name} {channel}"
            in window.analysis_banners["statistics"]["channel"].text()
        )
        assert function.command in window.metric_basis_label.text()
        assert window.metric_cards["mean"].value.text().endswith(unit)
        assert window.metric_cards["count"].value.text() == "8"
        for other in window.CHANNELS:
            assert window.statistics_summary_cards[other].isHidden() == (
                other != channel
            )
            y = window.trend_plot._channel_data[other][1]
            assert (np.asarray(y).size > 0) == (other == channel)
            assert window.trend_plot._curves[other].isVisible() == (other == channel)

    window.multi_analysis_check.setChecked(True)
    assert window.analysis_channels == ("A", "B", "C")
    assert all(not c.isHidden() for c in window.statistics_summary_cards.values())
    window.analysis_channel_combo.setCurrentIndex(
        window.analysis_channel_combo.findData("A")
    )
    assert window.device_tabs.currentIndex() == 0
    assert window.analysis_channels == ("A",)

    window.multi_analysis_check.setChecked(True)
    window.analysis_channel_combo.activated.emit(0)
    assert window.analysis_channels == ("A",)
    window.multi_analysis_check.setChecked(True)
    window.device_tabs.tabBarClicked.emit(0)
    assert window.analysis_channels == ("A",)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_outlier_gaps_pause_uniform_grid_analysis_per_channel(window, language):
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    sample_time = np.arange(1000) * 0.001
    signal = 10.0 + np.sin(2 * np.pi * 50.0 * sample_time)
    with_outliers = signal.copy()
    with_outliers[::4] += 100.0
    for channel, values in (("A", with_outliers), ("B", signal)):
        window.channels[channel].session.replace(sample_time, values, "V", "test")
    window.outlier_check.setChecked(True)

    def point_count(curve):
        _x, y = curve.getData()
        return 0 if y is None else np.asarray(y).size

    for curves in (window.fft_curves, window.asd_curves, window.allan_curves):
        assert point_count(curves["A"]) == 0
        assert point_count(curves["B"]) > 0
    frequency, amplitude = window.fft_curves["B"].getData()
    assert frequency[np.argmax(amplitude)] == pytest.approx(50.0)
    assert point_count(window.drift_points["A"]) == 750
    assert np.asarray(window.hist_bars["A"].opts["height"]).sum() == 750
    assert window.summary_labels["A"]["count"].text() == "750 / 250"
    assert window.metric_cards["count"].value.text() == "750"
    instruction = "Disable outlier rejection" if language == "en" else "关闭异常值剔除"
    assert instruction in window.spectrum_note.text()
    assert not window.spectrum_note.isHidden()
    assert instruction in window.stability_note.text()
    assert "A FFT/ASD" in window.analysis_banners["spectrum"]["meta"].text()
    assert "A Allan" in window.analysis_banners["stability"]["meta"].text()

    window.outlier_check.setChecked(False)

    for curves in (window.fft_curves, window.asd_curves, window.allan_curves):
        assert point_count(curves["A"]) > 0
        assert point_count(curves["B"]) > 0
    assert window.metric_cards["count"].value.text() == "1,000"
    assert window.spectrum_note.isHidden()
    assert window.spectrum_note.text() == ""
    assert instruction not in window.stability_note.text()
    for page in ("spectrum", "stability"):
        assert window.analysis_banners[page]["meta"].toolTip() == ""


@pytest.mark.parametrize("size", [(1180, 720), (1600, 1000)])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_inspector_scrolls_without_compressing_parameter_cards(window, size, language):
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    window.identity_model.setText("Keysight Technologies 34470A")
    window.identity_resource.setText("TCPIP0::192.168.100.123::inst0::INSTR")
    window.identity_fw.setText("A.03.03-03.15-03.03-00.52-04-03")
    window.resize(*size)
    window.show()
    QtTest.QTest.qWait(50)
    QtWidgets.QApplication.processEvents()

    scroll = window.inspector_scroll
    assert isinstance(window.main_splitter.widget(2), QtWidgets.QScrollArea)
    assert scroll.widgetResizable()
    assert scroll.verticalScrollBar().maximum() > 0
    assert scroll.verticalScrollBar().isVisible()
    assert scroll.widget().height() > scroll.viewport().height()
    assert scroll.minimumWidth() == 260

    for field in (window.session_count, window.identity_model, window.autosave_status):
        card = field.parentWidget()
        assert card.height() >= card.minimumSizeHint().height()
        labels = card.findChildren(
            QtWidgets.QLabel, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly
        )
        for label in labels:
            assert card.rect().contains(label.geometry())
            assert label.height() >= label.minimumSizeHint().height()
            if label.hasHeightForWidth():
                assert label.height() >= label.heightForWidth(label.width())
        for index, first in enumerate(labels):
            for second in labels[index + 1 :]:
                assert not first.geometry().intersects(second.geometry())

    scroll.ensureWidgetVisible(window.open_autosave_button)
    QtWidgets.QApplication.processEvents()
    position = window.open_autosave_button.mapTo(scroll.viewport(), QtCore.QPoint(0, 0))
    button_bounds = QtCore.QRect(position, window.open_autosave_button.size())
    assert scroll.viewport().rect().contains(button_bounds)
    assert "automatically" not in window.box_zoom_button.toolTip()
