from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
from PySide6 import QtCore

from .analysis import (
    allan_deviation,
    descriptive_stats,
    estimate_sample_period,
    has_time_gaps,
    linear_fit,
    sigma_mask,
)
from .analysis import spectrum as calculate_spectrum
from .performance import display_indices


@dataclass(frozen=True)
class AnalysisRequest:
    signature: tuple
    selected: str
    arrays: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, str]]
    reject_outliers: bool
    threshold: float
    normalized: bool


def calculate_analysis(request: AnalysisRequest) -> dict:
    """Pure calculation on owned snapshots; this function never touches Qt widgets."""
    result: dict = {"signature": request.signature, "channels": {}}
    for channel, (raw_x, raw_y, raw_temperature, unit) in request.arrays.items():
        mask = (
            sigma_mask(raw_y, request.threshold)
            if request.reject_outliers
            else np.ones(raw_y.size, dtype=bool)
        )
        x, y, temperature = raw_x[mask], raw_y[mask], raw_temperature[mask]
        removed = raw_y.size - y.size
        period = estimate_sample_period(raw_x)
        # Missing samples after a reconnect must not be treated as a uniform grid.
        gaps = has_time_gaps(raw_x)
        data = {
            "unit": unit,
            "stats": descriptive_stats(y, x),
            "removed": removed,
            "gaps": gaps,
            "raw_count": raw_y.size,
            "duration": float(np.ptp(raw_x)) if raw_x.size > 1 else 0.0,
            "period": period if raw_x.size > 1 else np.nan,
        }
        result["channels"][channel] = data
        if y.size >= 4:
            if not removed and not gaps:
                data["spectrum"] = calculate_spectrum(y, estimate_sample_period(x))
                tau, deviation = allan_deviation(
                    y, estimate_sample_period(x), normalize=request.normalized
                )
                if request.normalized:
                    deviation *= 1e6
                valid = (tau > 0) & (deviation > 0)
                data["allan"] = (tau[valid], deviation[valid])
            fitted, drift, r_squared = linear_fit(x, y)
            indices = display_indices(y.size, 20_000)
            data["drift"] = (x[indices], y[indices], fitted[indices], drift, r_squared)
            temperature_mask = np.isfinite(temperature) & np.isfinite(y)
            if (
                temperature_mask.sum() >= 3
                and np.ptp(temperature[temperature_mask]) > 0
            ):
                coefficient = np.polyfit(
                    temperature[temperature_mask], y[temperature_mask], 1
                )[0]
                mean = float(np.mean(y[temperature_mask]))
                data["temperature_ppm"] = (
                    coefficient / abs(mean) * 1e6 if mean else np.nan
                )
        # Keep filtered values only inside this calculation, never in the result.
        data["_hist_y"] = y

    units = {data["unit"] for data in result["channels"].values()}
    plot_channels = (request.selected,) if len(units) > 1 else tuple(result["channels"])
    result["plot_channels"] = plot_channels
    populated = [
        result["channels"][key]["_hist_y"]
        for key in plot_channels
        if result["channels"][key]["_hist_y"].size
    ]
    if populated:
        combined = np.concatenate(populated)
        bins = min(100, max(8, int(np.sqrt(combined.size))))
        if np.ptp(combined) == 0:
            span = max(abs(float(combined[0])) * 1e-9, 1e-12)
            edges = np.linspace(combined[0] - span, combined[0] + span, bins + 1)
        else:
            edges = np.histogram_bin_edges(combined, bins=bins)
        for key in plot_channels:
            counts, _ = np.histogram(result["channels"][key]["_hist_y"], bins=edges)
            result["channels"][key]["histogram"] = (
                (edges[:-1] + edges[1:]) / 2,
                counts,
                float(np.mean(np.diff(edges))) * 0.92,
            )
    for data in result["channels"].values():
        del data["_hist_y"]
    return result


class AnalysisWorker(QtCore.QThread):
    completed = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._condition = threading.Condition()
        self._pending: AnalysisRequest | None = None
        self._stopping = False

    def submit(self, request: AnalysisRequest) -> None:
        with self._condition:
            if self._stopping:
                return
            # One running job plus one newest snapshot; refreshes cannot build a backlog.
            self._pending = request
            self._condition.notify()
        if not self.isRunning():
            self.start()

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._pending = None
            self._condition.notify()

    def run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stopping or self._pending is not None
                )
                if self._stopping:
                    return
                request, self._pending = self._pending, None
            try:
                result = calculate_analysis(request)
            except Exception as exc:
                logging.getLogger(__name__).exception("Background analysis failed")
                self.failed.emit(str(exc))
            else:
                with self._condition:
                    if self._stopping:
                        return
                self.completed.emit(result)
