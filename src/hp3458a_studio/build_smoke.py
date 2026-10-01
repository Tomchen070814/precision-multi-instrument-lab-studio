"""Exercise the frozen Windows executable without VISA or a physical instrument."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6 import QtCore

from . import __version__
from .models import MeasurementFunction
from .smu_demo import SmuDemoDialog


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
    passed = False
    app.setQuitOnLastWindowClosed(False)

    def poll() -> None:
        nonlocal beats, closing, passed
        beats += 1
        if closing:
            if window._shutdown_complete:
                timer.stop()
                app.exit(0 if passed else 1)
            return
        done = (
            not any(runtime.running for runtime in window.channels.values())
            and demo.worker is None
        )
        if not done and time.monotonic() - started < 20:
            return
        channels = {
            key: {
                "samples": len(runtime.session),
                "unit": runtime.session.unit,
                "error": runtime.error,
            }
            for key, runtime in window.channels.items()
        }
        passed = (
            done
            and all(
                value["samples"] == 15 and not value["error"]
                for value in channels.values()
            )
            and all(len(rows) == 21 for rows in demo.rows.values())
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "version": __version__,
                    "result": "passed" if passed else "failed",
                    "gui_timer_ticks": beats,
                    "dmm_channels": channels,
                    "virtual_smu_samples": {
                        key: len(rows) for key, rows in demo.rows.items()
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        closing = True
        demo._stop()
        demo.close()
        window._smu_demo_dialog = demo
        window.close()

    timer.timeout.connect(poll)
    timer.start()
