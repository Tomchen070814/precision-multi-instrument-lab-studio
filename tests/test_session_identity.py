import csv
import os
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6 import QtCore, QtTest, QtWidgets
except ImportError as exc:
    pytest.skip(str(exc), allow_module_level=True)

import hp3458a_studio.main_window as main_window_module
from hp3458a_studio.main_window import MainWindow
from hp3458a_studio.models import InstrumentModel, MeasurementFunction, SessionData


def _wait_until(predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
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


def _capture_dc_voltage(window):
    panel = window.panels["A"]
    panel.driver_combo.setCurrentIndex(panel.driver_combo.findData("sim"))
    panel.function_combo.setCurrentIndex(
        panel.function_combo.findData(MeasurementFunction.DC_VOLTAGE)
    )
    config = replace(
        panel.read_config(),
        max_samples=3,
        sample_interval_s=0.001,
        measurement_range="10",
        nplc=1.0,
    )
    assert window._start_channel("A", config)
    assert _wait_until(lambda: not window.channels["A"].running)
    assert len(window.channels["A"].session) == 3
    window._refresh_views()
    return config


@pytest.mark.parametrize(
    "proposed_function",
    [MeasurementFunction.AC_VOLTAGE, MeasurementFunction.RESISTANCE_4W],
)
def test_retained_capture_identity_survives_control_changes_and_restart(
    window, proposed_function
):
    original_config = _capture_dc_voltage(window)
    runtime = window.channels["A"]
    original_path = Path(runtime.last_autosave_path)
    original_resource = window._analysis_resource_text("A")
    original_csv_resource = runtime.session.resource
    original_values = runtime.session.values.copy()
    panel = window.panels["A"]
    panel.model_combo.setCurrentIndex(
        panel.model_combo.findData(InstrumentModel.KEYSIGHT_34470A.value)
    )
    panel.function_combo.setCurrentIndex(
        panel.function_combo.findData(proposed_function)
    )
    panel.resource_combo.setCurrentText("GPIB0::99::INSTR")
    panel.range_combo.setCurrentIndex(0)
    panel.nplc_combo.setCurrentText("100")
    window._refresh_views()
    window._retranslate_readout("A")

    assert runtime.session.values == original_values
    assert runtime.capture_config == original_config
    assert window.metric_basis_label.text().endswith(
        f"A · 3458A · DCV · {original_resource} · V"
    )
    assert window.trend_plot._legend_labels["A"] == (
        f"A · 3458A · DCV · {original_resource} (V)"
    )
    assert "DCV" in window.comparison_note.text()
    assert "GPIB0::99::INSTR" not in window.comparison_note.text()
    assert window.readouts["A"]["tag"].text() == "3458A A"
    assert window.readouts["A"]["mode"].text().startswith("DCV · 10 ·")
    for banner in window.analysis_banners.values():
        assert "3458A A" in banner["channel"].text()
        assert f"A {original_resource}" in banner["resource"].text()
    snapshot = window._diagnostic_channel_snapshot("A")
    assert snapshot["instrument_model"] == "Keysight 3458A"
    assert snapshot["measurement_function"] == "DCV"
    assert snapshot["measurement_unit"] == "V"
    assert snapshot["resource"] == original_resource
    assert snapshot["range"] == "10"
    assert snapshot["nplc"] == "1"
    assert snapshot["configured_settings"]["measurement_function"] == (
        proposed_function.command
    )

    new_config = replace(panel.read_config(), max_samples=3, sample_interval_s=0.001)
    assert window._start_channel("A", new_config)
    assert _wait_until(lambda: not runtime.running)
    window._refresh_views()
    assert runtime.session.measurement_function == proposed_function.command
    assert runtime.session.instrument_model == "Keysight 34470A"
    assert runtime.session.unit == proposed_function.unit
    assert f"34470A · {proposed_function.command}" in window.metric_basis_label.text()
    with original_path.open(newline="", encoding="utf-8") as handle:
        original_rows = list(csv.DictReader(handle))
    assert len(original_rows) == 3
    assert {row["unit"] for row in original_rows} == {"V"}
    assert {row["resource"] for row in original_rows} == {original_csv_resource}


def test_failed_restart_preserves_capture_identity(window, monkeypatch):
    original_config = _capture_dc_voltage(window)
    panel = window.panels["A"]
    panel.function_combo.setCurrentIndex(
        panel.function_combo.findData(MeasurementFunction.AC_VOLTAGE)
    )

    def fail_writer(**kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(main_window_module, "DurableSessionWriter", fail_writer)
    assert not window._start_channel("A", panel.read_config())
    window._refresh_views()
    assert window.channels["A"].capture_config == original_config
    assert "3458A · DCV" in window.metric_basis_label.text()
    assert len(window.channels["A"].session) == 3


def test_burst_data_replacement_preserves_capture_provenance(window):
    panel = window.panels["A"]
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("burst"))
    panel.function_combo.setCurrentIndex(
        panel.function_combo.findData(MeasurementFunction.DIGITIZE_AC)
    )
    panel.burst_count.setValue(16)
    assert window._start_channel("A", panel.read_config())
    runtime = window.channels["A"]
    assert _wait_until(lambda: not runtime.running)
    window._refresh_views()
    assert len(runtime.session) == 16
    assert runtime.session.measurement_function == "DSAC"
    assert runtime.session.instrument_model == "Keysight 3458A"
    assert runtime.session.resource == "3458A A Simulator"
    assert "3458A · DSAC" in window.metric_basis_label.text()


def test_clearing_capture_returns_identity_to_current_controls(window):
    _capture_dc_voltage(window)
    panel = window.panels["A"]
    panel.function_combo.setCurrentIndex(
        panel.function_combo.findData(MeasurementFunction.RESISTANCE_4W)
    )
    window._clear_selected_session()
    runtime = window.channels["A"]
    assert runtime.capture_config is None
    assert runtime.session.measurement_function == ""
    assert not len(runtime.session)
    assert "3458A · OHMF" in window.metric_basis_label.text()
    assert window.metric_basis_label.text().endswith("· Ω")


def test_plain_csv_import_clears_previous_capture_identity(
    window, tmp_path, monkeypatch
):
    _capture_dc_voltage(window)
    runtime = window.channels["A"]
    assert runtime.identity is not None
    imported_path = tmp_path / "external.csv"
    imported_path.write_text("elapsed_s,reading (Ω)\n0,100\n1,101\n", encoding="utf-8")
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *args: (str(imported_path), "")
    )
    window._import_csv()

    assert runtime.identity is None
    assert runtime.capture_config is None
    assert runtime.session.instrument_model == ""
    assert runtime.session.measurement_function == ""
    assert window.metric_basis_label.text().endswith(
        "A · — · — · CSV::external.csv · Ω"
    )
    assert window.trend_plot._legend_labels["A"] == (
        "A · — · — · CSV::external.csv (Ω)"
    )
    assert window.readouts["A"]["mode"].text() == "— · — · CSV"
    assert window.readouts["A"]["temperature"].text() == "TEMP —"
    snapshot = window._diagnostic_channel_snapshot("A")
    assert snapshot["measurement_function"] == "—"
    assert snapshot["measurement_unit"] == "Ω"
    assert snapshot["range"] is None
    assert snapshot["identity"] is None


def test_session_replacement_requires_explicit_provenance():
    session = SessionData()
    times = np.array([0.0, 1.0])
    values = np.array([1.0, 2.0])
    metadata = {
        "instrument_model": "Keysight 3458A",
        "resource": "GPIB0::21::INSTR",
        "measurement_function": "ACV",
    }
    session.replace(times, values, **metadata)
    assert all(getattr(session, key) == value for key, value in metadata.items())
    with pytest.raises(ValueError):
        session.replace(times, np.array([1.0]))
    assert all(getattr(session, key) == value for key, value in metadata.items())
    session.replace(times, values)
    assert all(getattr(session, key) == "" for key in metadata)
    session.replace(times, values, **metadata)
    session.clear()
    assert all(getattr(session, key) == "" for key in metadata)
