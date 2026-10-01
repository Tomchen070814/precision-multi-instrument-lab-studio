import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtGui, QtWidgets

import hp3458a_studio.__main__ as main_module
import hp3458a_studio.build_smoke as smoke_module
from hp3458a_studio.models import SessionData


@pytest.fixture
def captures(tmp_path):
    channels = {}
    for key, unit in smoke_module.EXPECTED_UNITS.items():
        path = tmp_path / f"capture-{key}.csv"
        values = [float(index) + 0.25 for index in range(15)]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["reading", "unit", "channel"])
            writer.writerows((value, unit, key) for value in values)
        channels[key] = SimpleNamespace(
            session=SessionData(values=values, unit=unit),
            error="",
            last_autosave_path=str(path),
        )
    demo = SimpleNamespace(rows={key: [1] * 21 for key in channels}, _error="")
    return SimpleNamespace(channels=channels), demo


def test_smoke_validates_actual_csv_counts_units_and_values(captures):
    window, demo = captures
    report = smoke_module._collect_smoke_report(window, demo, True, 12)
    assert report["result"] == "passed"
    assert report["failure_reasons"] == []
    for key, unit in smoke_module.EXPECTED_UNITS.items():
        journal = report["dmm_channels"][key]["durable_csv"]
        assert journal["samples"] == 15
        assert journal["units"] == [unit]


@pytest.mark.parametrize("broken", ["unit", "missing", "partial", "short", "reading"])
def test_smoke_reports_capture_file_and_unit_failures(captures, broken):
    window, demo = captures
    runtime = window.channels["B"]
    path = Path(runtime.last_autosave_path)
    if broken == "unit":
        runtime.session.unit = "V"
    elif broken == "missing":
        path.unlink()
    elif broken == "partial":
        runtime.last_autosave_path = str(path.with_suffix(".partial.csv"))
    elif broken == "short":
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:-1]), encoding="utf-8")
    else:
        path.write_text(
            path.read_text(encoding="utf-8").replace("0.25", "nan", 1), encoding="utf-8"
        )
    report = smoke_module._collect_smoke_report(window, demo, True, 12)
    assert report["result"] == "failed"
    assert any("DMM B" in reason for reason in report["failure_reasons"])
    if broken == "unit":
        assert any(
            "expected unit Ω, got V" in reason for reason in report["failure_reasons"]
        )
    else:
        assert report["dmm_channels"]["B"]["csv_error"]


def test_smoke_rejects_smu_error_even_when_all_sample_counts_match(captures):
    window, demo = captures
    demo._error = "Virtual transport failure"
    report = smoke_module._collect_smoke_report(window, demo, True, 12)
    assert report["result"] == "failed"
    assert "Virtual SMU: Virtual transport failure" in report["failure_reasons"]


def test_smoke_timeout_report_is_explicit(captures, tmp_path):
    window, demo = captures
    report = smoke_module._collect_smoke_report(window, demo, False, 12)
    assert report["result"] == "failed"
    assert "Timed out" in report["failure_reasons"][0]
    target = tmp_path / "result.json"
    assert smoke_module._save_report(target, report)
    assert json.loads(target.read_text(encoding="utf-8"))["failure_reasons"]


@pytest.fixture
def screenshot_widgets():
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    window.readouts = {}
    window.readout_cards = {}
    for key in smoke_module.EXPECTED_UNITS:
        card = QtWidgets.QWidget()
        card_layout = QtWidgets.QVBoxLayout(card)
        label = QtWidgets.QLabel("10.123456789")
        font = QtGui.QFont(label.font())
        font.setPixelSize(22)
        label.setFont(font)
        label.setFixedSize(320, 42)
        card_layout.addWidget(label)
        layout.addWidget(card)
        window.readouts[key] = {"value": label}
        window.readout_cards[key] = card
    window.resize(380, 250)
    window.show()
    demo = QtWidgets.QWidget()
    QtWidgets.QApplication.processEvents()
    yield window, demo
    window.close()
    demo.close()
    window.deleteLater()
    demo.deleteLater()
    QtWidgets.QApplication.processEvents()


def test_smoke_screenshot_records_real_qt_fonts_and_geometry(
    screenshot_widgets, tmp_path
):
    window, demo = screenshot_widgets
    report = {"result": "passed", "failure_reasons": []}
    path = tmp_path / "validation.json"
    smoke_module._capture_ui_evidence(window, demo, path, report)
    assert report["result"] == "passed"
    assert path.with_suffix(".png").is_file()
    assert (tmp_path / "validation-smu.png").is_file()
    assert report["screenshot"]["width"] > 0
    for evidence in report["readout_layout"].values():
        assert evidence["requested_font_pixel_size"] == 22
        assert evidence["effective_font_pixel_size"] >= 12
        assert evidence["text_fits_width"]
        assert evidence["text_fits_height"]
        assert evidence["font_metrics_width"] > 0
        assert evidence["readout_card_rect"]["width"] > 0


def test_smoke_does_not_accept_a_fitting_one_pixel_readout(
    screenshot_widgets, tmp_path
):
    window, demo = screenshot_widgets
    label = window.readouts["A"]["value"]
    font = QtGui.QFont(label.font())
    font.setPixelSize(1)
    label.setFont(font)
    report = {"result": "passed", "failure_reasons": []}
    smoke_module._capture_ui_evidence(
        window, demo, tmp_path / "validation.json", report
    )
    assert report["readout_layout"]["A"]["text_fits_width"]
    assert report["result"] == "failed"
    assert any("font is too small" in reason for reason in report["failure_reasons"])


def test_smoke_screenshot_failure_cannot_pass(screenshot_widgets, tmp_path):
    window, demo = screenshot_widgets
    window.grab = lambda: QtGui.QPixmap()
    report = {"result": "passed", "failure_reasons": []}
    smoke_module._capture_ui_evidence(
        window, demo, tmp_path / "validation.json", report
    )
    assert report["result"] == "failed"
    assert any("screenshot failed" in reason for reason in report["failure_reasons"])


def test_smoke_font_info_negative_pixels_does_not_reject_readable_actual_font(
    screenshot_widgets, tmp_path, monkeypatch
):
    window, demo = screenshot_widgets
    monkeypatch.setattr(
        smoke_module.QtGui,
        "QFontInfo",
        lambda font: SimpleNamespace(pixelSize=lambda: -1),
    )
    report = {"result": "passed", "failure_reasons": []}
    smoke_module._capture_ui_evidence(
        window, demo, tmp_path / "validation.json", report
    )
    assert report["result"] == "passed"
    assert all(
        evidence["resolved_font_pixel_size"] == -1
        and evidence["effective_font_pixel_size"] == 22
        for evidence in report["readout_layout"].values()
    )


@pytest.mark.parametrize("startup_fails", [False, True])
def test_smoke_entrypoint_isolates_logging_settings_and_startup_failures(
    tmp_path, monkeypatch, startup_fails
):
    captured = {}
    report_path = tmp_path / "smoke.json"

    class FakeApplication:
        def __init__(self, _arguments):
            pass

        def __getattr__(self, _name):
            return lambda *args: None

        def exec(self):
            return 0

    class FakeWindow:
        def __init__(self):
            captured["settings"] = Path(self._create_settings().fileName())
            if startup_fails:
                raise RuntimeError("frozen dependency unavailable")

        def show(self):
            pass

    def forbidden_user_state(*_args):
        raise AssertionError("Smoke test accessed user state or opened a modal error")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("HP3458A_SCREENSHOT", raising=False)
    monkeypatch.setattr(sys, "argv", ["program.exe", "--smoke-test", str(report_path)])
    monkeypatch.setattr(main_module.QtWidgets, "QApplication", FakeApplication)
    monkeypatch.setattr(main_module, "MainWindow", FakeWindow)
    monkeypatch.setattr(
        main_module, "configure_logging", lambda path: captured.update(log=path)
    )
    monkeypatch.setattr(main_module, "_install_exception_hook", lambda: None)
    monkeypatch.setattr(main_module, "_show_fatal_startup_error", forbidden_user_state)
    monkeypatch.setattr(main_module.logging, "shutdown", lambda: None)
    monkeypatch.setattr(
        main_module.QtCore.QStandardPaths, "writableLocation", forbidden_user_state
    )
    monkeypatch.setattr(smoke_module, "start_smoke_test", lambda *args: None)
    assert main_module.main() == int(startup_fails)
    assert captured["log"].name == "logs"
    assert captured["log"].parent == captured["settings"].parent
    assert captured["log"].parent != tmp_path
    if startup_fails:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["result"] == "failed"
        assert "frozen dependency unavailable" in report["failure_reasons"][0]
