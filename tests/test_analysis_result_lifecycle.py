import time

import numpy as np
import pytest
from PySide6 import QtCore

import hp3458a_studio.main_window as main_window_module
from hp3458a_studio.analysis_worker import AnalysisRequest, calculate_analysis
from hp3458a_studio.main_window import MainWindow
from hp3458a_studio.models import Measurement


@pytest.fixture
def window(qt_application, tmp_path, monkeypatch):
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.Format.IniFormat
    )
    monkeypatch.setattr(MainWindow, "_create_settings", staticmethod(lambda: settings))
    monkeypatch.setattr(
        main_window_module, "default_autosave_root", lambda: tmp_path / "autosave"
    )
    result = MainWindow()
    yield result
    result.close()
    deadline = time.monotonic() + 3
    while not result._shutdown_complete and time.monotonic() < deadline:
        qt_application.processEvents()
        time.sleep(0.002)
    assert result._shutdown_complete
    result.deleteLater()
    qt_application.processEvents()


def _snapshot(window):
    return calculate_analysis(
        AnalysisRequest(
            window._analysis_signature(),
            window.selected_channel,
            {
                key: (
                    window.channels[key].session.x.copy(),
                    window.channels[key].session.y.copy(),
                    window.channels[key].session.temperature.copy(),
                    window.channels[key].session.unit,
                )
                for key in window.analysis_channels
            },
            window.outlier_check.isChecked(),
            window.sigma_spin.value(),
            window.allan_normalized.isChecked(),
        )
    )


def _displayed_analysis(window):
    return (
        window.summary_labels["A"]["count"].text(),
        window.summary_labels["A"]["min"].text(),
        window.fft_curves["A"].getData()[1].copy(),
        np.asarray(window.hist_bars["A"].opts["height"]).copy(),
    )


def _assert_display_unchanged(window, expected):
    actual = _displayed_analysis(window)
    assert actual[:2] == expected[:2]
    np.testing.assert_array_equal(actual[2], expected[2])
    np.testing.assert_array_equal(actual[3], expected[3])


def test_final_synchronous_analysis_supersedes_older_live_snapshot(window):
    session = window.channels["A"].session
    session.replace(np.arange(8) * 0.1, np.linspace(1, 2, 8))
    old_result = _snapshot(window)
    original_values = session.values
    for index in range(8, 32):
        session.append(Measurement(index * 0.1, 10 + index / 100, "V"))
    # Appending samples keeps the same session list and first timestamp.
    assert session.values is original_values
    window._refresh_views()
    expected = _displayed_analysis(window)
    assert expected[0] == "32 / 0"
    assert old_result["signature"] != window._analysis_signature()
    window._apply_background_analysis(old_result)
    _assert_display_unchanged(window, expected)


def test_replaced_session_rejects_previous_source_analysis(window):
    session = window.channels["A"].session
    session.replace(
        np.arange(8) * 0.1,
        np.linspace(1, 2, 8),
        measurement_function="DCV",
        resource="SIM::A",
    )
    old_result = _snapshot(window)
    session.replace(
        np.arange(16) * 0.1,
        np.linspace(100, 101, 16),
        unit="Ω",
        measurement_function="OHMF",
        resource="CSV::replacement.csv",
    )
    window._refresh_views()
    expected = _displayed_analysis(window)
    assert expected[0] == "16 / 0"
    window._apply_background_analysis(old_result)
    _assert_display_unchanged(window, expected)
