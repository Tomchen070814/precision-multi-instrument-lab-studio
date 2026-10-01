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
        session = window.channels[channel].session
        session.instrument_model = model.display_name
        session.resource = panel.resource_name
        session.measurement_function = function.command
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
    window.autosave_path_label.setText(
        "C:/Users/Windows-Measurement-Operator/AppData/Local/"
        "Precision Multi-Instrument Lab Studio/autosave/2026-10-01"
    )
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
    assert scroll.widget().width() <= scroll.viewport().width()

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


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
@pytest.mark.parametrize("font_px", [18, 24])
@pytest.mark.parametrize("font_family", ["Arial", "Courier New"])
def test_narrow_english_inspector_wraps_controls_with_larger_fonts(
    app, window, style_name, font_px, font_family
):
    previous_style = app.style().objectName()
    app.setStyle(QtWidgets.QStyleFactory.create(style_name))
    try:
        window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
        scroll = window.inspector_scroll
        scroll.setMaximumWidth(260)
        scroll.widget().setStyleSheet(
            f"* {{ font-size: {font_px}px; font-family: '{font_family}'; }}"
        )
        window.identity_model.setText("Keysight Technologies 34470A")
        window.identity_resource.setText("TCPIP0::192.168.100.123::inst0::INSTR")
        window.autosave_path_label.setText(
            "C:/Users/Windows-Measurement-Operator/AppData/Local/"
            "Precision Multi-Instrument Lab Studio/autosave/2026-10-01"
        )
        window.resize(1180, 720)
        window.show()
        QtTest.QTest.qWait(100)

        assert scroll.width() == 260
        assert scroll.viewport().width() == 252
        assert scroll.widget().width() <= scroll.viewport().width(), {
            type(child).__name__ + ": " + getattr(child, "text", lambda: "")(): (
                child.width(),
                child.minimumSizeHint().width(),
            )
            for child in scroll.widget().findChildren(QtWidgets.QWidget)
            if child.minimumSizeHint().width() > scroll.viewport().width() - 28
        }
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() > 0
        for field in (
            window.session_count,
            window.identity_model,
            window.autosave_status,
        ):
            card = field.parentWidget()
            labels = card.findChildren(
                QtWidgets.QLabel,
                options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly,
            )
            for label in labels:
                assert label.width() > 0
                assert card.rect().contains(label.geometry())
                if label.hasHeightForWidth():
                    assert label.height() >= label.heightForWidth(label.width())
            for index, first in enumerate(labels):
                for second in labels[index + 1 :]:
                    assert not first.geometry().intersects(second.geometry())
        for control in window._inspector_control_texts:
            scroll.ensureWidgetVisible(control)
            QtWidgets.QApplication.processEvents()
            bounds = QtCore.QRect(
                control.mapTo(scroll.viewport(), QtCore.QPoint(0, 0)), control.size()
            )
            assert scroll.viewport().rect().contains(bounds)
            assert control.width() >= control.minimumSizeHint().width()
            assert control.height() >= control.sizeHint().height()
            assert " ".join(control.text().split()) == " ".join(
                window._inspector_control_texts[control].split()
            )
            text_width = control.width() - 26
            assert all(
                control.fontMetrics().horizontalAdvance(line) <= text_width
                for line in control.text().splitlines()
            )
    finally:
        app.setStyle(QtWidgets.QStyleFactory.create(previous_style))


def test_language_change_preserves_live_sources_and_stopped_temperature(window):
    window.channel_c_enabled.setChecked(True)
    window.sync_channel_checks["C"].setChecked(True)
    for panel in window.panels.values():
        panel.interval_spin.setValue(0.02)
    window._start_both()
    assert _wait_until(
        lambda: all(len(runtime.session) >= 2 for runtime in window.channels.values())
    )
    window._stop_channel("A")
    assert _wait_until(lambda: not window.channels["A"].running)
    window.channels["A"].last_temperature = 28.25
    window._retranslate_readout("A")
    sources = window.header_source.text()
    temperature = window.readouts["A"]["temperature"].text()
    readout_sources = {
        key: labels["source"].text() for key, labels in window.readouts.items()
    }
    peers = {key: window.channels[key].worker for key in ("B", "C")}
    peer_counts = {key: len(window.channels[key].session) for key in peers}
    assert "C OFF" not in sources
    assert temperature == "TEMP 28.250°C"
    for language in ("en", "zh", "en"):
        window.language_combo.setCurrentIndex(window.language_combo.findData(language))
        assert window.header_source.text() == sources
        assert window.readouts["A"]["temperature"].text() == temperature
        assert {
            key: labels["source"].text() for key, labels in window.readouts.items()
        } == readout_sources
        assert window.brand_subtitle.text().startswith(
            "MULTI-INSTRUMENT" if language == "en" else "多仪表精密测量与分析"
        )
        assert all(
            window.channels[key].worker is worker for key, worker in peers.items()
        )
    assert _wait_until(
        lambda: all(
            len(window.channels[key].session) > peer_counts[key] for key in peers
        )
    )


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("size", [(1180, 720), (1600, 1000)])
def test_readout_interval_and_trend_toolbar_remain_readable(window, size, language):
    window.channel_c_enabled.setChecked(True)
    for channel in window.CHANNELS:
        runtime = window.channels[channel]
        runtime.session.replace(
            np.arange(20) * 0.1,
            np.linspace(0.9, 1.1, 20),
            "V",
            "test",
            timestamps=1_790_859_600 + np.arange(20) * 0.1,
        )
        runtime.sample_interval_s = 21.1
        runtime.target_samples = 9_999_999
        runtime.last_temperature = 28.25
        runtime.minimum, runtime.maximum = 0.9, 1.1
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    for channel in window.CHANNELS:
        window._retranslate_readout(channel)
    window.resize(*size)
    window.show()
    QtTest.QTest.qWait(100)
    assert window.size() == QtCore.QSize(*size)
    assert window.trend_plot.viewport().height() >= 120
    for channel, readout in window.readouts.items():
        card = window.readout_cards[channel]
        assert readout["interval"].text() == "Δt 21.1 s"
        assert readout["interval"].width() >= readout["interval"].sizeHint().width()
        assert "9,999,999" in readout["mode"].text()
        for label in readout.values():
            assert card.rect().contains(label.geometry())
            if label.hasHeightForWidth():
                assert label.height() >= label.heightForWidth(label.width())
        labels = list(readout.values())
        for index, first in enumerate(labels):
            for second in labels[index + 1 :]:
                assert not first.geometry().intersects(second.geometry())

    toolbar = window.trend_toolbar_scroll
    controls = (
        window.trend_axis_combo,
        window.zoom_x_in_button,
        window.zoom_x_out_button,
        window.zoom_y_in_button,
        window.zoom_y_out_button,
        window.box_zoom_button,
        window.reset_zoom_button,
        window.clear_marks_button,
    )
    for control in controls:
        toolbar.ensureWidgetVisible(control)
        QtWidgets.QApplication.processEvents()
        bounds = QtCore.QRect(
            control.mapTo(toolbar.viewport(), QtCore.QPoint(0, 0)), control.size()
        )
        assert toolbar.viewport().rect().contains(bounds)
        assert control.width() >= control.sizeHint().width()
        assert control.height() >= control.sizeHint().height()


@pytest.mark.parametrize("font_family", ["Arial", "Courier New"])
@pytest.mark.parametrize("size", [(1180, 720), (1600, 1000)])
def test_long_precision_readouts_and_units_stay_inside_cards(window, size, font_family):
    value_text = "0.010000021768"
    for channel, unit in zip(window.CHANNELS, ("mA", "Ω", "nF"), strict=True):
        window.readout_cards[channel].setStyleSheet(
            f"* {{ font-family: '{font_family}'; }}"
        )
        readout = window.readouts[channel]
        readout["value"].setStyleSheet("font-size: 32px;")
        readout["value"].setText(value_text)
        readout["unit"].setText(unit)
    window.resize(*size)
    window.show()
    QtTest.QTest.qWait(100)
    assert window.size() == QtCore.QSize(*size)
    assert window.trend_plot.viewport().height() >= 120
    for channel in window.CHANNELS:
        card = window.readout_cards[channel]
        value, unit = (
            window.readouts[channel]["value"],
            window.readouts[channel]["unit"],
        )
        assert value.text() == value_text
        assert value.fontMetrics().horizontalAdvance(value.text()) <= value.width()
        assert unit.width() >= unit.sizeHint().width()
        assert card.rect().contains(value.geometry())
        assert card.rect().contains(unit.geometry())
        assert not value.geometry().intersects(unit.geometry())


@pytest.mark.parametrize(
    ("function", "unit"),
    [(MeasurementFunction.RESISTANCE_4W, "Ω"), (MeasurementFunction.AC_VOLTAGE, "V")],
)
def test_restart_selected_channel_after_function_change_resets_old_zoom(
    window, function, unit
):
    window.channel_c_enabled.setChecked(True)
    window.sync_channel_checks["C"].setChecked(True)
    for panel in window.panels.values():
        panel.interval_spin.setValue(0.02)
    window.show()
    window._start_both()
    assert _wait_until(
        lambda: all(len(c.session) >= 4 for c in window.channels.values())
    )
    window._analysis_channel_activated()
    window._stop_channel("A")
    assert _wait_until(lambda: not window.channels["A"].running)
    peers = {key: window.channels[key].worker for key in ("B", "C")}
    peer_counts = {key: len(window.channels[key].session) for key in peers}
    old_latest = float(window.channels["A"].session.timestamps[-1])
    window.trend_plot.zoom_x(0.5)
    window.trend_plot.getViewBox().setXRange(old_latest - 10, old_latest - 5, padding=0)
    assert window._trend_x_window is not None
    curve = window.trend_plot._curves["A"]
    curve.setVisible(False)
    window.trend_plot._legend_visibility_changed("A", curve)
    assert "A" in window.trend_plot._legend_hidden
    panel = window.panels["A"]
    panel.function_combo.setCurrentIndex(panel.function_combo.findData(function.value))

    window._toggle_channel("A")

    assert window._trend_x_window is None
    assert _wait_until(lambda: len(window.channels["A"].session) >= 4)
    window._refresh_views()
    assert window.channels["A"].session.unit == unit
    assert window.session_unit.text() == unit
    assert window.trend_plot.available_units == (unit,)
    assert window.trend_plot._channel_data["A"][1].size >= 4
    assert window.trend_plot._curves["A"].isVisible()
    assert "A" not in window.trend_plot._legend_hidden
    assert window.readouts["A"]["interval"].text() == "Δt 0.02 s"
    assert function.command in window.metric_basis_label.text()
    for key, worker in peers.items():
        assert window.channels[key].worker is worker
        assert len(window.channels[key].session) > peer_counts[key]
        assert window.trend_plot._channel_data[key][1].size == 0
        assert not window.trend_plot._curves[key].isVisible()
    assert _wait_until(
        lambda: (
            window.trend_plot.getViewBox().viewRange()[0][0]
            > max(float(window.channels[key].session.timestamps[0]) for key in peers)
        )
    )


def test_long_sampling_interval_keeps_first_sample_and_explains_wait(window):
    window._analysis_channel_activated()
    window.panels["A"].interval_spin.setValue(21.1)
    window._toggle_channel("A")
    assert _wait_until(lambda: len(window.channels["A"].session) == 1)
    QtTest.QTest.qWait(100)
    assert window.channels["A"].running
    assert len(window.channels["A"].session) == 1
    assert window.trend_plot._channel_data["A"][1].size == 1
    assert window.trend_plot._curves["A"].isVisible()
    assert window.trend_plot._curves["A"].opts["symbol"] is not None
    assert window.readouts["A"]["interval"].text() == "Δt 21.1 s"
    assert "设定采样间隔：21.1 秒" in window.readouts["A"]["time"].toolTip()
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert (
        "Requested sampling interval: 21.1 s" in window.readouts["A"]["time"].toolTip()
    )
    window._stop_channel("A")
    assert _wait_until(lambda: not window.channels["A"].running, timeout_ms=2000)


def test_starting_hidden_channel_preserves_selected_channel_zoom(window):
    window.channels["A"].session.replace(
        np.arange(20) * 0.1, np.linspace(1.0, 2.0, 20), "V", "test"
    )
    window._analysis_channel_activated()
    window.trend_plot.zoom_x(0.5)
    saved_window = window._trend_x_window
    assert saved_window is not None
    window.panels["B"].interval_spin.setValue(0.02)
    window._toggle_channel("B")
    assert _wait_until(lambda: len(window.channels["B"].session) >= 2)
    assert window._trend_x_window == saved_window
    assert window.analysis_channels == ("A",)
    assert window.trend_plot._channel_data["A"][1].size > 0
    assert window.trend_plot._channel_data["B"][1].size == 0


@pytest.mark.parametrize("selector", ["dropdown", "tab"])
def test_reselect_current_instrument_restores_legend_hidden_curve(window, selector):
    window.channels["A"].session.replace(
        np.arange(20) * 0.1, np.linspace(1.0, 2.0, 20), "V", "test"
    )
    window._analysis_channel_activated()
    curve = window.trend_plot._curves["A"]
    curve.setVisible(False)
    window.trend_plot._legend_visibility_changed("A", curve)
    window._refresh_views()
    assert not curve.isVisible()
    if selector == "dropdown":
        window.analysis_channel_combo.activated.emit(0)
    else:
        window.device_tabs.tabBarClicked.emit(0)
    assert curve.isVisible()
    assert "A" not in window.trend_plot._legend_hidden
