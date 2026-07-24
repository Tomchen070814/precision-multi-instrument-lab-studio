import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtCore, QtTest, QtWidgets
except ImportError as exc:  # Linux CI images may not include libEGL
    pytest.skip(str(exc), allow_module_level=True)

import hp3458a_studio.main_window as main_window_module
from hp3458a_studio.main_window import MainWindow
from hp3458a_studio.models import InstrumentModel, Measurement


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


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep UI tests independent from a user's saved language and layout."""
    settings = QtCore.QSettings(
        str(tmp_path / "3458a-test-settings.ini"),
        QtCore.QSettings.Format.IniFormat,
    )
    monkeypatch.setattr(
        MainWindow,
        "_create_settings",
        staticmethod(lambda: settings),
    )
    monkeypatch.setattr(
        main_window_module,
        "default_autosave_root",
        lambda: tmp_path / "autosave",
    )
    yield
    settings.clear()
    settings.sync()


def _curve_point_count(curve) -> int:
    """Read curve data through pyqtgraph's public API.

    Depending on the pyqtgraph version, an empty PlotDataItem may expose
    ``xData`` as either an empty ndarray or ``None``. ``getData`` is stable
    across both representations.
    """
    x_data, _y_data = curve.getData()
    return 0 if x_data is None else int(np.asarray(x_data).size)


def _histogram_bin_count(bar) -> int:
    heights = bar.opts.get("height")
    return 0 if heights is None else int(np.asarray(heights).size)


def test_channels_can_start_at_different_times(app):
    window = MainWindow()
    window.panels["A"].interval_spin.setValue(0.02)
    window.panels["B"].interval_spin.setValue(0.02)
    window._toggle_channel("A")
    assert _wait_until(lambda: len(window.channels["A"].session) >= 2)
    assert not window.channels["B"].running
    window._toggle_channel("B")
    assert _wait_until(lambda: len(window.channels["B"].session) >= 2)
    assert window.channels["A"].worker is not window.channels["B"].worker
    window._stop_all()
    assert _wait_until(
        lambda: not window.channels["A"].running and not window.channels["B"].running
    )
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_window_can_close_and_reopen_in_same_process(app):
    first = MainWindow()
    first.show()
    first.close()
    assert _wait_until(lambda: not first.isVisible())
    first.deleteLater()
    QtWidgets.QApplication.processEvents()

    second = MainWindow()
    second.show()
    assert second.isVisible()
    second.close()
    second.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_coordinated_start_releases_both_channels(app):
    window = MainWindow()
    window.panels["A"].interval_spin.setValue(0.02)
    window.panels["B"].interval_spin.setValue(0.02)
    window._start_both()
    assert _wait_until(
        lambda: (
            len(window.channels["A"].session) >= 1
            and len(window.channels["B"].session) >= 1
        )
    )
    assert window._group_gate is None
    first_a = window.channels["A"].session.elapsed_s[0]
    first_b = window.channels["B"].session.elapsed_s[0]
    assert first_a < 0.1
    assert first_b < 0.1
    assert abs(first_a - first_b) < 0.05
    window._stop_all()
    assert _wait_until(
        lambda: not window.channels["A"].running and not window.channels["B"].running
    )
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_duplicate_real_resource_is_rejected(app):
    window = MainWindow()
    for panel in window.panels.values():
        panel.driver_combo.setCurrentIndex(1)
        panel.resource_combo.setCurrentText("GPIB0::22::INSTR")
    with pytest.raises(ValueError) as error:
        window._validate_distinct_resources({"A", "B"})
    assert "VISA" in str(error.value)
    assert "不能连接同一个 VISA 地址" in str(error.value)
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_scan_replaces_stale_addresses_and_assigns_two_instruments(app, monkeypatch):
    window = MainWindow()
    window.panels["A"].resource_combo.setCurrentText("GPIB0::21::INSTR")
    window.panels["B"].resource_combo.setCurrentText("GPIB0::22::INSTR")
    monkeypatch.setattr(
        main_window_module,
        "discover_visa_resources",
        lambda: ["GPIB0::22::INSTR", "GPIB0::23::INSTR"],
    )

    window._discover_resources()
    assert _wait_until(lambda: window._visa_scan_worker is None)

    assert window.panels["A"].resource_name == "GPIB0::22::INSTR"
    assert window.panels["B"].resource_name == "GPIB0::23::INSTR"
    assert (
        "当前地址分配：A=GPIB0::22::INSTR，B=GPIB0::23::INSTR"
        in window.event_log.toPlainText()
    )
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_every_analysis_page_identifies_selected_instrument_and_resource(app):
    window = MainWindow()
    window.dual_analysis_check.setChecked(False)
    window.panels["A"].driver_combo.setCurrentIndex(1)
    window.panels["B"].driver_combo.setCurrentIndex(1)
    window.panels["A"].resource_combo.setCurrentText("GPIB0::21::INSTR")
    window.panels["B"].resource_combo.setCurrentText("GPIB1::22::INSTR")
    for index in range(8):
        window.channels["A"].session.append(
            Measurement(index * 0.1, 1.0 + index * 1e-6, "V")
        )
        window.channels["B"].session.append(
            Measurement(index * 0.1, 2.0 + index * 1e-6, "V")
        )

    window.analysis_channel_combo.setCurrentIndex(0)
    window._refresh_views()
    assert window.tabs.tabText(window.spectrum_tab_index).endswith("· A")
    assert window.tabs.tabText(window.statistics_tab_index).endswith("· A")
    assert window.tabs.tabText(window.stability_tab_index).endswith("· A")
    for banner in window.analysis_banners.values():
        assert banner["channel"].text() == "3458A A"
        assert banner["resource"].text() == "GPIB0::21::INSTR"
        assert "8 样本" in banner["meta"].text()
    assert window.statistics_summary_titles["A"].text() == "3458A A · 统计摘要"
    assert not window.statistics_summary_cards["A"].isHidden()
    assert window.statistics_summary_cards["B"].isHidden()
    assert window.stability_note.text().startswith("3458A A ·")

    window.analysis_channel_combo.setCurrentIndex(1)
    window._refresh_views()
    assert window.tabs.tabText(window.spectrum_tab_index).endswith("· B")
    assert window.tabs.tabText(window.statistics_tab_index).endswith("· B")
    assert window.tabs.tabText(window.stability_tab_index).endswith("· B")
    for banner in window.analysis_banners.values():
        assert banner["channel"].text() == "3458A B"
        assert banner["resource"].text() == "GPIB1::22::INSTR"
        assert "8 样本" in banner["meta"].text()
    assert window.statistics_summary_titles["B"].text() == "3458A B · 统计摘要"
    assert window.statistics_summary_cards["A"].isHidden()
    assert not window.statistics_summary_cards["B"].isHidden()
    assert window.stability_note.text().startswith("3458A B ·")

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_dual_analysis_displays_a_and_b_on_every_analysis_page(app):
    window = MainWindow()
    window.panels["A"].driver_combo.setCurrentIndex(1)
    window.panels["B"].driver_combo.setCurrentIndex(1)
    window.panels["A"].resource_combo.setCurrentText("GPIB0::21::INSTR")
    window.panels["B"].resource_combo.setCurrentText("GPIB1::22::INSTR")
    for index in range(32):
        temperature = 25.0 + index * 0.01
        window.channels["A"].session.append(
            Measurement(
                index * 0.1,
                1.0 + np.sin(index / 3) * 1e-6,
                "V",
                internal_temperature_c=temperature,
            )
        )
        window.channels["B"].session.append(
            Measurement(
                index * 0.12,
                2.0 + np.cos(index / 4) * 2e-6,
                "V",
                internal_temperature_c=temperature + 0.2,
            )
        )

    window.dual_analysis_check.setChecked(True)
    window._refresh_views()

    assert window.analysis_channels == ("A", "B")
    assert window.tabs.tabText(window.spectrum_tab_index).endswith("· A+B")
    assert window.tabs.tabText(window.statistics_tab_index).endswith("· A+B")
    assert window.tabs.tabText(window.stability_tab_index).endswith("· A+B")
    for banner in window.analysis_banners.values():
        assert banner["channel"].text() == "3458A A + B"
        assert "A GPIB0::21::INSTR" in banner["resource"].text()
        assert "B GPIB1::22::INSTR" in banner["resource"].text()
        assert "A 32 样本" in banner["meta"].text()
        assert "B 32 样本" in banner["meta"].text()
    for channel in ("A", "B"):
        assert _curve_point_count(window.fft_curves[channel]) > 0
        assert _curve_point_count(window.asd_curves[channel]) > 0
        assert _histogram_bin_count(window.hist_bars[channel]) > 0
        assert _curve_point_count(window.allan_curves[channel]) > 0
        assert _curve_point_count(window.drift_points[channel]) == 32
        assert _curve_point_count(window.drift_fit_curves[channel]) == 32
        assert not window.statistics_summary_cards[channel].isHidden()
    assert "3458A A · 线性漂移" in window.stability_note.text()
    assert "3458A B · 线性漂移" in window.stability_note.text()

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_mixed_units_use_independent_trend_axes_and_selected_analysis(app):
    window = MainWindow()
    for index in range(8):
        window.channels["A"].session.append(
            Measurement(index * 0.1, 1.0 + index * 1e-6, "V")
        )
        window.channels["B"].session.append(
            Measurement(index * 0.1, 100.0 + index * 1e-3, "Ω")
        )

    window.dual_analysis_check.setChecked(True)
    window._refresh_views()

    assert window.trend_plot.axis_assignments["A"] == 0
    assert window.trend_plot.axis_assignments["B"] == 1
    assert _curve_point_count(window.fft_curves["A"]) > 0
    assert _curve_point_count(window.asd_curves["A"]) > 0
    assert _curve_point_count(window.allan_curves["A"]) > 0
    assert _curve_point_count(window.drift_points["A"]) == 8
    assert _curve_point_count(window.fft_curves["B"]) == 0
    assert _curve_point_count(window.asd_curves["B"]) == 0
    assert "混合物理量" in window.stability_note.text()
    assert "混合单位" in window.analysis_banners["spectrum"]["meta"].text()

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def _set_fixed_count(window, channel, count):
    panel = window.panels[channel]
    panel.interval_spin.setValue(0.01)
    panel.precision_length_combo.setCurrentIndex(
        panel.precision_length_combo.findData("fixed")
    )
    panel.precision_count.setValue(count)


def test_fixed_count_precision_acquisition_stops_automatically(app):
    window = MainWindow()
    _set_fixed_count(window, "A", 7)

    window._toggle_channel("A")

    assert _wait_until(
        lambda: (
            not window.channels["A"].running and len(window.channels["A"].session) == 7
        )
    )
    assert window.channels["A"].state == "已完成"
    assert window.readouts["A"]["time"].text().startswith("完成 · 7 / 7 点 · ")
    assert "固定点数采集完成：7 点，已自动停止" in window.event_log.toPlainText()
    assert not window.channels["B"].running

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_synchronized_channels_finish_their_own_fixed_counts(app):
    window = MainWindow()
    _set_fixed_count(window, "A", 5)
    _set_fixed_count(window, "B", 9)

    window._start_both()

    assert _wait_until(
        lambda: (
            not window.channels["A"].running
            and not window.channels["B"].running
            and len(window.channels["A"].session) == 5
            and len(window.channels["B"].session) == 9
        )
    )
    assert window.channels["A"].state == "已完成"
    assert window.channels["B"].state == "已完成"
    assert window.readouts["A"]["time"].text().startswith("完成 · 5 / 5 点 · ")
    assert window.readouts["B"]["time"].text().startswith("完成 · 9 / 9 点 · ")

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_reserved_channel_c_can_be_enabled_without_changing_a_or_b(app):
    window = MainWindow()
    window.channel_c_enabled.setChecked(False)
    assert window.enabled_channels == ("A", "B")
    assert window.sync_channels == ("A", "B")
    assert not window.panels["C"].isEnabled()
    assert not window.sync_channel_checks["C"].isEnabled()

    window.channel_c_enabled.setChecked(True)

    assert window.enabled_channels == ("A", "B", "C")
    assert window.panels["A"].isEnabled()
    assert window.panels["B"].isEnabled()
    assert window.panels["C"].isEnabled()
    assert window.analysis_channels == ("A", "B", "C")
    assert window.sync_channel_checks["C"].isEnabled()
    assert window.sync_channels == ("A", "B")
    assert "A+B" in window.start_both_button.text()

    window.channel_c_enabled.setChecked(False)
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_channel_can_switch_to_34470a_without_changing_other_channels(app):
    window = MainWindow()
    b_panel = window.panels["B"]
    b_panel.model_combo.setCurrentIndex(
        b_panel.model_combo.findData(InstrumentModel.KEYSIGHT_34470A)
    )

    assert b_panel.instrument_model is InstrumentModel.KEYSIGHT_34470A
    assert window.device_tabs.tabText(1) == "34470A B"
    assert (
        not b_panel.mode_combo.model()
        .item(b_panel.mode_combo.findData("burst"))
        .isEnabled()
    )
    assert window.panels["A"].instrument_model is InstrumentModel.KEYSIGHT_3458A

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_any_pair_can_be_selected_for_synchronized_start(app):
    window = MainWindow()
    window.channel_c_enabled.setChecked(True)

    window.sync_channel_checks["A"].setChecked(True)
    window.sync_channel_checks["B"].setChecked(False)
    window.sync_channel_checks["C"].setChecked(True)
    assert window.sync_channels == ("A", "C")
    assert window.start_both_button.text() == "同步启动 A+C"

    window.sync_channel_checks["A"].setChecked(False)
    window.sync_channel_checks["B"].setChecked(True)
    assert window.sync_channels == ("B", "C")
    assert window.start_both_button.text() == "同步启动 B+C"

    window.channel_c_enabled.setChecked(False)
    assert window.sync_channels == ("B",)
    assert window.start_both_button.text() == "启动 B"
    assert not window.sync_channel_checks["C"].isChecked()

    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_selected_a_and_c_start_without_touching_b(app):
    window = MainWindow()
    window.channel_c_enabled.setChecked(True)
    window.sync_channel_checks["A"].setChecked(True)
    window.sync_channel_checks["B"].setChecked(False)
    window.sync_channel_checks["C"].setChecked(True)
    _set_fixed_count(window, "A", 5)
    _set_fixed_count(window, "C", 7)

    window._start_both()

    assert _wait_until(
        lambda: (
            not window.channels["A"].running
            and not window.channels["C"].running
            and len(window.channels["A"].session) == 5
            and len(window.channels["C"].session) == 7
        )
    )
    assert len(window.channels["B"].session) == 0
    assert not window.channels["B"].running
    assert "A+C 同步启动" in window.event_log.toPlainText()

    window.channel_c_enabled.setChecked(False)
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_language_switch_updates_main_and_instrument_controls(app):
    window = MainWindow()
    english_index = window.language_combo.findData("en")
    window.language_combo.setCurrentIndex(english_index)

    assert window.stop_all_button.text() == "Stop all"
    assert window.import_button.text() == "Import to selected"
    assert window.panels["A"].resource_refresh.text() == "Scan"
    assert window.panels["A"].start_button.text() == "Start 3458A A"
    assert window.start_both_button.text() == "Synchronized start A+B"
    assert window.export_diagnostic_button.text() == "Export diagnostic report"
    assert "Multi-channel trend" in window.tabs.tabText(window.trend_tab_index)

    chinese_index = window.language_combo.findData("zh")
    window.language_combo.setCurrentIndex(chinese_index)
    window.close()
    window.deleteLater()
    QtWidgets.QApplication.processEvents()
