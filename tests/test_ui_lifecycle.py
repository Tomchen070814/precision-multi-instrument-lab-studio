import csv
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtCore, QtGui, QtTest, QtWidgets
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


def _control_size_diagnostics(control):
    metrics = control.fontMetrics()
    text = getattr(control, "text", lambda: "")()
    return {
        "text": text,
        "own_style": control.styleSheet(),
        "font": control.font().toString(),
        "requested_font_px": control.font().pixelSize(),
        "resolved_font_px": QtGui.QFontInfo(control.font()).pixelSize(),
        "metrics_dpi": metrics.fontDpi(),
        "metrics_height": metrics.height(),
        "line_widths": [metrics.horizontalAdvance(line) for line in text.splitlines()],
        "minimum_hint": control.minimumSizeHint().toTuple(),
        "preferred_hint": control.sizeHint().toTuple(),
        "size": control.size().toTuple(),
        "logical_dpi": (control.logicalDpiX(), control.logicalDpiY()),
    }


def test_reconnection_warning_is_nonmodal_and_keeps_existing_samples(window):
    window.channels["A"].session.append(Measurement(0, 10, "V"))
    window.channels["B"].session.append(Measurement(0, 20, "V"))
    window._worker_recovering("A", 1, 0.5, "mock VISA timeout")
    warning = window._hardware_warnings["A"]
    assert warning.isVisible() and not warning.isModal()
    assert window.channels["A"].state == "正在重连"
    ticks = []
    QtCore.QTimer.singleShot(0, lambda: ticks.append(1))
    assert _wait_until(lambda: ticks)
    assert window.channels["A"].session.values == [10]
    assert window.channels["B"].session.values == [20]
    window._worker_recovered("A")
    assert window.channels["A"].state == "正在采集"
    warning.close()


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def window(app, tmp_path, monkeypatch, request):
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    if getattr(request, "param", None) is not None:
        settings.setValue("language", request.param)
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


@pytest.mark.parametrize(
    ("window", "expected"),
    [(None, "en"), ("unsupported-language", "en"), ("zh", "zh"), ("en", "en")],
    indirect=["window"],
)
def test_startup_defaults_to_english_and_preserves_saved_language(window, expected):
    assert window.language == expected
    assert window.language_combo.currentData() == expected
    assert all(panel.language == expected for panel in window.panels.values())
    assert window.windowTitle() == (
        "Precision Multi-Instrument Lab Studio"
        if expected == "en"
        else "精密多仪器测量平台"
    )


def test_default_english_can_switch_to_and_remember_chinese(window):
    assert window.language == "en"
    window.language_combo.setCurrentIndex(window.language_combo.findData("zh"))
    assert window.language == "zh"
    assert window.settings.value("language") == "zh"
    assert all(panel.language == "zh" for panel in window.panels.values())
    assert window.panels["A"].start_button.text() == "启动 3458A A"
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert window.settings.value("language") == "en"
    assert window.panels["A"].start_button.text() == "Start 3458A A"


def test_standalone_instrument_panel_defaults_to_english(app):
    panel = main_window_module.InstrumentControlPanel("A", "GPIB0::21::INSTR")
    try:
        assert panel.language == "en"
        assert panel.start_button.text() == "Start 3458A A"
        panel.set_language("zh")
        assert panel.start_button.text() == "启动 3458A A"
    finally:
        panel.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("has_data", [False, True])
def test_charts_have_no_legend_overlay_and_preserve_channel_controls(window, has_data):
    if has_data:
        window.channel_c_enabled.setChecked(True)
        for channel, runtime in window.channels.items():
            runtime.session.replace(
                np.arange(16, dtype=float),
                np.linspace(1, 2, 16) + ord(channel),
                "V",
                "simulation",
            )
        window._refresh_views()
    for language in ("en", "zh"):
        window.language_combo.setCurrentIndex(window.language_combo.findData(language))
        for plot in (
            window.trend_plot,
            window.fft_plot,
            window.asd_plot,
            window.hist_plot,
            window.allan_plot,
            window.drift_plot,
        ):
            legend = plot.getPlotItem().legend
            assert legend is None or not legend.isVisible()
        assert set(window.readouts) == {"A", "B", "C"}
        assert set(window.panels) == {"A", "B", "C"}
        assert window.device_tabs.count() == 3
        for channel in window.CHANNELS:
            assert window.analysis_channel_combo.findData(channel) >= 0
            if has_data:
                _x, y = window.trend_plot._curves[channel].getData()
                assert y is not None and len(y) == 16


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
        window.rolling_spin.setValue(window.rolling_spin.maximum())
        window.sigma_spin.setValue(window.sigma_spin.maximum())
        window.resize(1180, 720)
        window.show()
        QtTest.QTest.qWait(100)

        assert scroll.width() == 260
        assert scroll.viewport().width() == 252
        assert scroll.widget().width() <= scroll.viewport().width(), json.dumps(
            {
                type(child).__name__ + ": " + getattr(child, "text", lambda: "")(): (
                    _control_size_diagnostics(child)
                )
                for child in scroll.widget().findChildren(QtWidgets.QWidget)
                if child.minimumSizeHint().width() > scroll.viewport().width() - 28
            },
            indent=2,
        )
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() > 0
        for spin in (window.rolling_spin, window.sigma_spin):
            edit = spin.lineEdit()
            assert (
                edit.fontMetrics().horizontalAdvance(spin.text())
                <= edit.contentsRect().width()
            )
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
                assert card.rect().contains(label.geometry()), {
                    "text": label.text(),
                    "card_field": field.text(),
                    "card_rect": card.rect().getRect(),
                    "label_rect": label.geometry().getRect(),
                }
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


@pytest.mark.parametrize("font_info_unavailable", [False, True])
def test_english_inspector_preserves_words_when_native_font_requires_fitting(
    window, monkeypatch, font_info_unavailable
):
    if font_info_unavailable:
        monkeypatch.setattr(
            main_window_module.QtGui,
            "QFontInfo",
            lambda font: SimpleNamespace(pixelSize=lambda: -1),
        )
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    scroll = window.inspector_scroll
    scroll.setMaximumWidth(260)
    control = window.allan_normalized
    requested_style = "font-size: 48px; font-family: 'Courier New';"
    control.setStyleSheet(requested_style)
    window.resize(1180, 720)
    window.show()
    QtTest.QTest.qWait(100)
    window._fit_inspector_controls()
    QtWidgets.QApplication.processEvents()

    canonical_text = "Normalize Allan to ppm"
    assert window._inspector_control_texts[control] == canonical_text
    assert " ".join(control.text().split()) == canonical_text
    assert "Normalize" in control.text().splitlines()
    assert 1 < control.font().pixelSize() < 48
    assert control.minimumSizeHint().width() <= scroll.viewport().width() - 28, (
        json.dumps(_control_size_diagnostics(control), indent=2)
    )
    assert all(
        control.fontMetrics().horizontalAdvance(line) <= control.width() - 26
        for line in control.text().splitlines()
    )
    fitted_font_px = control.font().pixelSize()
    window._fit_inspector_controls()
    assert control.font().pixelSize() == fitted_font_px
    window._retranslate_ui()
    assert " ".join(control.text().split()) == canonical_text
    assert control.minimumSizeHint().width() <= scroll.viewport().width() - 28

    # Fitting is responsive: once the complete words fit at the requested size,
    # widening the inspector restores that size without changing its text.
    control.setStyleSheet(requested_style)
    control.ensurePolished()
    wide_width = max(360, control.minimumSizeHint().width() + 38)
    scroll.setMaximumWidth(wide_width)
    scroll.setMinimumWidth(wide_width)
    QtTest.QTest.qWait(100)
    assert control.font().pixelSize() == 48
    assert control.styleSheet() == requested_style
    assert " ".join(control.text().split()) == canonical_text
    assert control.minimumSizeHint().width() <= scroll.viewport().width() - 28
    if font_info_unavailable:
        for spin in (window.rolling_spin, window.sigma_spin):
            spin.setValue(spin.maximum())
            spin.setStyleSheet("font-size: 24px;")
            spin.ensurePolished()
            spin.lineEdit().setStyleSheet("")
            spin.lineEdit().ensurePolished()
            window._inspector_spin_font_px.pop(spin, None)
        window._fit_inspector_controls()
        for spin in (window.rolling_spin, window.sigma_spin):
            edit = spin.lineEdit()
            assert window._inspector_spin_font_px[spin] == 24
            assert edit.font().pixelSize() > 1
            assert (
                edit.fontMetrics().horizontalAdvance(spin.text())
                <= edit.contentsRect().width()
            ), json.dumps(_control_size_diagnostics(edit), indent=2)
        value = window.readouts["A"]["value"]
        value.setStyleSheet("font-size: 32px;")
        value.setText("123456789012345.6789")
        assert value._maximum_font_px == 32
        assert value.font().pixelSize() > 1
        assert (
            value.fontMetrics().horizontalAdvance(value.text())
            <= value.contentsRect().width()
        ), json.dumps(_control_size_diagnostics(value), indent=2)


def test_readout_retains_readable_requested_size_without_native_font_info(
    window, monkeypatch
):
    monkeypatch.setattr(
        main_window_module.QtGui,
        "QFontInfo",
        lambda font: SimpleNamespace(pixelSize=lambda: -1),
    )
    window.resize(1800, 1000)
    window.show()
    QtTest.QTest.qWait(100)
    value = window.readouts["A"]["value"]
    value.setStyleSheet("font-size: 30px;")
    value.setText("10.000000")
    QtTest.QTest.qWait(30)
    requested_font = QtGui.QFont(value.font())
    requested_font.setPixelSize(30)
    requested_metrics = QtGui.QFontMetrics(requested_font, value)
    assert (
        requested_metrics.horizontalAdvance(value.text())
        <= value.contentsRect().width()
    )
    assert value._maximum_font_px == 30
    assert value.font().pixelSize() == 30, json.dumps(
        _control_size_diagnostics(value), indent=2
    )
    assert value.height() >= value.fontMetrics().height()
    assert (
        value.fontMetrics().horizontalAdvance(value.text())
        <= value.contentsRect().width()
    ), json.dumps(_control_size_diagnostics(value), indent=2)


@pytest.mark.parametrize(
    ("pixel_size", "point_size", "dpi", "metric_height", "expected"),
    [(24, -1, 144, 35, 24), (-1, 12, 144, 30, 24), (-1, -1, 96, 17, 17)],
)
def test_font_pixel_size_uses_requested_size_and_paint_device_fallbacks(
    pixel_size, point_size, dpi, metric_height, expected
):
    font = SimpleNamespace(
        pixelSize=lambda: pixel_size,
        pointSizeF=lambda: point_size,
    )
    paint_device = SimpleNamespace(
        font=lambda: font,
        logicalDpiY=lambda: dpi,
        fontMetrics=lambda: SimpleNamespace(height=lambda: metric_height),
    )
    assert main_window_module._font_pixel_size(paint_device) == expected


def test_inspector_fitting_invalidates_stale_native_checkbox_size_hint(window):
    class PreserveNativeSizeCache(QtCore.QObject):
        def eventFilter(self, watched, event):
            return event.type() in (
                QtCore.QEvent.Type.FontChange,
                QtCore.QEvent.Type.StyleChange,
                QtCore.QEvent.Type.PaletteChange,
            )

    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    scroll = window.inspector_scroll
    scroll.setMaximumWidth(260)
    window.resize(1180, 720)
    window.show()
    QtTest.QTest.qWait(100)
    control = window.allan_normalized
    control.setText("Normalize\nAllan\nto\nppm")
    control.setStyleSheet("font-size: 48px; font-family: 'Courier New';")
    control.ensurePolished()
    previous_hint = control.minimumSizeHint()
    previous_width = control.fontMetrics().horizontalAdvance("Normalize")
    assert previous_hint.width() > scroll.viewport().width() - 28
    cache_filter = PreserveNativeSizeCache(control)
    control.installEventFilter(cache_filter)
    try:
        # Reproduce the Windows failure: the requested font and actual glyph
        # metrics change while the native checkbox keeps its previous size hint.
        control.setStyleSheet("font-size: 24px; font-family: 'Courier New';")
        control.ensurePolished()
        assert control.fontMetrics().horizontalAdvance("Normalize") < previous_width
        assert control.minimumSizeHint() == previous_hint
        window._fit_inspector_controls()
        QtWidgets.QApplication.processEvents()
        assert control.minimumSizeHint().width() <= scroll.viewport().width() - 28, (
            _control_size_diagnostics(control)
        )
        assert " ".join(control.text().split()) == "Normalize Allan to ppm"
        assert all(
            control.fontMetrics().horizontalAdvance(line) <= control.width() - 26
            for line in control.text().splitlines()
        ), _control_size_diagnostics(control)
        assert scroll.widget().width() <= scroll.viewport().width()
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        control.removeEventFilter(cache_filter)


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
        assert control.width() >= control.sizeHint().width(), {
            "text": getattr(control, "text", lambda: "")(),
            "width": control.width(),
            "hint": control.sizeHint().width(),
        }
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
        assert value.fontMetrics().horizontalAdvance(value.text()) <= value.width(), {
            "font": value.font().toString(),
            "dpi": value.logicalDpiX(),
            "detached_width": QtGui.QFontMetrics(value.font()).horizontalAdvance(
                value.text()
            ),
            "device_width": QtGui.QFontMetrics(value.font(), value).horizontalAdvance(
                value.text()
            ),
            "label_width": value.width(),
        }
        assert unit.width() >= unit.sizeHint().width()
        assert card.rect().contains(value.geometry())
        assert card.rect().contains(unit.geometry())
        assert not value.geometry().intersects(unit.geometry())


@pytest.mark.parametrize("size", [(1517, 892), (1600, 1000)])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_large_window_shows_complete_readouts_and_all_metrics(window, size, language):
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
        runtime.sample_interval_s = 0.1
        runtime.last_temperature = 28.25
        runtime.minimum, runtime.maximum = 0.9, 1.1
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    for channel in window.CHANNELS:
        window._retranslate_readout(channel)
    window.resize(*size)
    window.show()
    QtTest.QTest.qWait(100)
    scroll = window.dashboard_scroll
    assert scroll.verticalScrollBar().maximum() == 0
    assert window.trend_plot.viewport().height() >= 120
    for card in (*window.readout_cards.values(), *window.metric_cards.values()):
        bounds = QtCore.QRect(
            card.mapTo(scroll.viewport(), QtCore.QPoint(0, 0)), card.size()
        )
        assert scroll.viewport().rect().contains(bounds), {
            "dashboard": scroll.viewport().rect().getRect(),
            "card": bounds.getRect(),
        }


def _assert_center_dashboard_allocation(window):
    scroll = window.dashboard_scroll
    tabs = window.tabs
    diagnostics = {
        "window": window.size().toTuple(),
        "center": window.center_panel.size().toTuple(),
        "dashboard_scroll": scroll.geometry().getRect(),
        "dashboard_content": scroll.widget().geometry().getRect(),
        "dashboard_minimum": scroll.widget().minimumSize().toTuple(),
        "readout_minimums": {
            channel: card.minimumSizeHint().toTuple()
            for channel, card in window.readout_cards.items()
        },
        "readout_states": {
            channel: _control_size_diagnostics(labels["state"])
            for channel, labels in window.readouts.items()
        },
        "tabs": tabs.geometry().getRect(),
        "tabs_minimum": tabs.minimumHeight(),
        "tabs_height_for_width": tabs.heightForWidth(tabs.width()),
        "plot_viewport": window.trend_plot.viewport().size().toTuple(),
    }
    assert (
        scroll.geometry().bottom() + window.center_panel.layout().spacing()
        < tabs.geometry().top()
    ), json.dumps(diagnostics, indent=2)
    assert window.trend_plot.viewport().height() >= 120, json.dumps(
        diagnostics, indent=2
    )
    assert scroll.widget().width() <= scroll.viewport().width(), json.dumps(
        diagnostics, indent=2
    )
    if scroll.verticalScrollBar().maximum() == 0:
        for card in (*window.readout_cards.values(), *window.metric_cards.values()):
            bounds = QtCore.QRect(
                card.mapTo(scroll.viewport(), QtCore.QPoint(0, 0)), card.size()
            )
            assert scroll.viewport().rect().contains(bounds), json.dumps(
                {**diagnostics, "card": bounds.getRect()}, indent=2
            )


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
@pytest.mark.parametrize("font_family", ["Segoe UI", "Arial"])
@pytest.mark.parametrize("size", [(1180, 720), (1180, 749)])
def test_dashboard_never_overlaps_tabs_during_startup_layout(
    window, style_name, font_family, size
):
    previous_style = QtWidgets.QApplication.style().objectName()
    try:
        QtWidgets.QApplication.setStyle(style_name)
        window.center_panel.setStyleSheet(f"* {{ font-family: '{font_family}'; }}")
        window.resize(*size)
        window.show()
        # Each event delivery can change wrapped readout heights. A final
        # qWait(200) alone hides the native frame that originally overlapped.
        for frame in range(4):
            QtWidgets.QApplication.processEvents()
            _assert_center_dashboard_allocation(window)
            if frame == 0:
                window.grab()
    finally:
        QtWidgets.QApplication.setStyle(previous_style)


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
@pytest.mark.parametrize("size", [(1180, 720), (1180, 749)])
def test_dashboard_stays_separate_while_samples_and_finalization_resize_text(
    window, style_name, size
):
    previous_style = QtWidgets.QApplication.style().objectName()
    try:
        QtWidgets.QApplication.setStyle(style_name)
        window.channel_c_enabled.setChecked(True)
        for check in window.sync_channel_checks.values():
            check.setChecked(True)
        for channel, function in zip(
            window.CHANNELS,
            (
                MeasurementFunction.DC_VOLTAGE,
                MeasurementFunction.RESISTANCE_4W,
                MeasurementFunction.DC_CURRENT,
            ),
            strict=True,
        ):
            panel = window.panels[channel]
            panel.driver_combo.setCurrentIndex(panel.driver_combo.findData("sim"))
            panel.function_combo.setCurrentIndex(
                panel.function_combo.findData(function.value)
            )
            panel.precision_length_combo.setCurrentIndex(
                panel.precision_length_combo.findData("fixed")
            )
            panel.precision_count.setValue(15)
            panel.interval_spin.setValue(0.01)
        window.resize(*size)
        window.show()
        window._start_both()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            QtWidgets.QApplication.processEvents()
            _assert_center_dashboard_allocation(window)
            if all(
                len(runtime.session) == 15 and not runtime.running
                for runtime in window.channels.values()
            ):
                break
            QtTest.QTest.qWait(5)
        assert all(
            len(runtime.session) == 15 and not runtime.running
            for runtime in window.channels.values()
        ), json.dumps(
            {
                channel: {
                    "samples": len(runtime.session),
                    "running": runtime.running,
                    "state": runtime.state,
                    "error": runtime.error,
                }
                for channel, runtime in window.channels.items()
            },
            indent=2,
        )
        assert all(runtime.state == "已完成" for runtime in window.channels.values())
        for _ in range(4):
            QtWidgets.QApplication.processEvents()
            _assert_center_dashboard_allocation(window)
    finally:
        QtWidgets.QApplication.setStyle(previous_style)


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
def test_long_native_readout_statuses_wrap_without_widening_dashboard(
    window, style_name
):
    previous_style = QtWidgets.QApplication.style().objectName()
    try:
        QtWidgets.QApplication.setStyle(style_name)
        window.resize(1180, 749)
        window.show()
        for labels in window.readouts.values():
            labels["state"].setStyleSheet("font-family: 'Arial'; font-size: 18px;")
        for status in ("等待同步", "正在重连", "采集错误", "已完成"):
            for channel in window.CHANNELS:
                window._set_channel_state(channel, status)
            for _ in range(3):
                QtWidgets.QApplication.processEvents()
                _assert_center_dashboard_allocation(window)
                for channel, readout in window.readouts.items():
                    state, tag = readout["state"], readout["tag"]
                    card = window.readout_cards[channel]
                    assert state.text() == main_window_module.tr("en", status)
                    assert card.rect().contains(state.geometry())
                    assert not state.geometry().intersects(tag.geometry())
                    assert state.height() >= state.heightForWidth(state.width()), (
                        json.dumps(_control_size_diagnostics(state), indent=2)
                    )
                    assert state.font().pixelSize() == 18
    finally:
        QtWidgets.QApplication.setStyle(previous_style)


@pytest.mark.parametrize("style_name", ["Windows", "Fusion"])
def test_full_sync_start_label_and_stop_button_fit_narrow_sidebar(window, style_name):
    previous_style = QtWidgets.QApplication.style().objectName()
    try:
        QtWidgets.QApplication.setStyle(style_name)
        window.channel_c_enabled.setChecked(True)
        for check in window.sync_channel_checks.values():
            check.setChecked(True)
        window.resize(1180, 720)
        window.show()
        QtWidgets.QApplication.processEvents()
        start, stop = window.start_both_button, window.stop_all_button
        assert start.text() == "Synchronized start A+B+C"
        for button in (start, stop):
            assert button.width() >= button.sizeHint().width(), json.dumps(
                _control_size_diagnostics(button), indent=2
            )
            assert button.parentWidget().rect().contains(button.geometry())
        assert not start.geometry().intersects(stop.geometry())
    finally:
        QtWidgets.QApplication.setStyle(previous_style)


@pytest.mark.parametrize("with_recovery", [False, True])
def test_autosave_language_preserves_recovery_status_without_rescanning(
    window, monkeypatch, with_recovery
):
    scans = []
    recovery = [SimpleNamespace(size_bytes=2048)] * 2 if with_recovery else []

    def scan(path):
        scans.append(path)
        return recovery

    monkeypatch.setattr(main_window_module, "list_recovery_files", scan)
    window._report_recovery_files()
    for language in ("en", "zh", "en"):
        window.language_combo.setCurrentIndex(window.language_combo.findData(language))
        text = window.autosave_status.text()
        if with_recovery:
            assert "4.0 KiB" in text
            assert (
                "2 interrupted capture(s) retained"
                if language == "en"
                else "检测到 2 个中断采集文件"
            ) in text
        else:
            assert (
                "Enabled · background batch fsync"
                if language == "en"
                else "已开启 · 后台批次 fsync"
            ) in text
    assert scans == [window.autosave_root]
    log = window.event_log.toPlainText()
    assert log.count("Recovered 2 interrupted") == (1 if with_recovery else 0)
    assert log.count("检测到 2 个异常中断") == 0


def test_readout_adapts_new_digits_without_waiting_for_a_parent_layout(window):
    window.resize(1180, 720)
    window.show()
    QtTest.QTest.qWait(100)
    value = window.readouts["A"]["value"]
    value.setStyleSheet("font-size: 32px;")
    for text in ("1.0", "0.010000021768000000000", "1.0"):
        value.setText(text)
        assert value.text() == text
        assert (
            value.fontMetrics().horizontalAdvance(text) <= value.contentsRect().width()
        )


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
    assert (
        "Requested sampling interval: 21.1 s" in window.readouts["A"]["time"].toolTip()
    )
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
