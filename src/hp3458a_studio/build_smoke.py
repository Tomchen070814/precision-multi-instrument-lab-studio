"""Exercise the frozen Windows executable without VISA or a physical instrument."""

from __future__ import annotations

import csv
import json
import logging
import math
import time
from pathlib import Path

from PySide6 import QtCore

from . import __version__
from .models import MeasurementFunction
from .smu_demo import SmuDemoDialog

EXPECTED_UNITS = {"A": "V", "B": "Ω", "C": "A"}


def _collect_smoke_report(window, demo, done: bool, beats: int) -> dict:
    reasons = []
    if not done:
        reasons.append(
            "Timed out waiting for acquisition and durable journal completion"
        )
    channels = {}
    for key, expected_unit in EXPECTED_UNITS.items():
        runtime = window.channels[key]
        channel = {
            "samples": len(runtime.session),
            "unit": runtime.session.unit,
            "error": runtime.error,
        }
        channels[key] = channel
        if channel["samples"] != 15:
            reasons.append(f"DMM {key}: expected 15 samples, got {channel['samples']}")
        if channel["unit"] != expected_unit:
            reasons.append(
                f"DMM {key}: expected unit {expected_unit}, got {channel['unit']}"
            )
        if channel["error"]:
            reasons.append(f"DMM {key}: {channel['error']}")
        try:
            if not runtime.last_autosave_path:
                raise ValueError("No finalized durable capture path")
            path = Path(runtime.last_autosave_path)
            if path.name.endswith(".partial.csv"):
                raise ValueError("Durable capture is still partial")
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            units = sorted({row.get("unit", "") for row in rows})
            channel["durable_csv"] = {
                "file": path.name,
                "samples": len(rows),
                "units": units,
            }
            if len(rows) != 15:
                raise ValueError(f"Expected 15 CSV rows, got {len(rows)}")
            if units != [expected_unit]:
                raise ValueError(f"Expected CSV unit {expected_unit}, got {units}")
            if any(row.get("channel") != key for row in rows):
                raise ValueError("CSV channel identity does not match the capture")
            values = [float(row.get("reading", "")) for row in rows]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("CSV contains non-finite readings")
            if values != runtime.session.values:
                raise ValueError("CSV readings do not match the captured session")
        except (OSError, UnicodeError, csv.Error, ValueError, TypeError) as exc:
            channel["csv_error"] = str(exc)
            reasons.append(f"DMM {key} CSV validation failed: {exc}")
    smu_samples = {key: len(demo.rows.get(key, [])) for key in EXPECTED_UNITS}
    for key, samples in smu_samples.items():
        if samples != 21:
            reasons.append(f"Virtual SMU {key}: expected 21 samples, got {samples}")
    if demo._error:
        reasons.append(f"Virtual SMU: {demo._error}")
    return {
        "version": __version__,
        "result": "failed" if reasons else "passed",
        "failure_reasons": reasons,
        "gui_timer_ticks": beats,
        "dmm_channels": channels,
        "virtual_smu_samples": smu_samples,
        "virtual_smu_error": demo._error,
    }


def _save_report(report_path: Path, report: dict) -> bool:
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return True
    except OSError:
        logging.getLogger(__name__).exception(
            "Smoke validation report could not be written"
        )
        return False


def start_smoke_test(app, window, report_path: Path) -> None:
    window.channel_c_enabled.setChecked(True)
    window.multi_analysis_check.setChecked(True)
    for check in window.sync_channel_checks.values():
        check.setChecked(True)
    for key, function in zip(
        ("A", "B", "C"),
        (
            MeasurementFunction.DC_VOLTAGE,
            MeasurementFunction.RESISTANCE_4W,
            MeasurementFunction.DC_CURRENT,
        ),
        strict=True,
    ):
        panel = window.panels[key]
        panel.driver_combo.setCurrentIndex(panel.driver_combo.findData("sim"))
        panel.function_combo.setCurrentIndex(
            panel.function_combo.findData(function.value)
        )
        panel.precision_length_combo.setCurrentIndex(
            panel.precision_length_combo.findData("fixed")
        )
        panel.precision_count.setValue(15)
        panel.interval_spin.setValue(0.01)
    demo = SmuDemoDialog(window)
    demo.points.setValue(21)
    demo.start_sweep()
    window._start_both()
    started = time.monotonic()
    timer = QtCore.QTimer(window)
    timer.setInterval(20)
    beats = 0
    closing = False
    report = None
    app.setQuitOnLastWindowClosed(False)

    def poll() -> None:
        nonlocal beats, closing, report
        beats += 1
        if closing:
            if window._shutdown_complete:
                timer.stop()
                report["shutdown_complete"] = True
                saved = _save_report(report_path, report)
                app.exit(0 if report["result"] == "passed" and saved else 1)
            return
        done = (
            not any(runtime.running for runtime in window.channels.values())
            and demo.worker is None
        )
        if not done and time.monotonic() - started < 20:
            return
        report = _collect_smoke_report(window, demo, done, beats)
        _save_report(
            report_path,
            dict(
                report,
                result="failed",
                shutdown_complete=False,
                failure_reasons=[
                    *report["failure_reasons"],
                    "Shutdown has not completed",
                ],
            ),
        )
        closing = True
        demo._stop()
        demo.close()
        window._smu_demo_dialog = demo
        window.close()

    timer.timeout.connect(poll)
    timer.start()
