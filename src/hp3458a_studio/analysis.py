from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class Statistics:
    count: int = 0
    mean: float = np.nan
    minimum: float = np.nan
    maximum: float = np.nan
    peak_to_peak: float = np.nan
    std: float = np.nan
    rms: float = np.nan
    median: float = np.nan
    noise_ppm: float = np.nan
    drift_per_hour: float = np.nan


def _finite_xy(
    values: np.ndarray | list[float],
    elapsed_s: np.ndarray | list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(values, dtype=float)
    x = (
        np.arange(y.size, dtype=float)
        if elapsed_s is None
        else np.asarray(elapsed_s, dtype=float)
    )
    if x.size != y.size:
        raise ValueError("elapsed_s and values must have the same length")
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def descriptive_stats(
    values: np.ndarray | list[float],
    elapsed_s: np.ndarray | list[float] | None = None,
) -> Statistics:
    x, y = _finite_xy(values, elapsed_s)
    if y.size == 0:
        return Statistics()
    mean = float(np.mean(y))
    std = float(np.std(y, ddof=1)) if y.size > 1 else 0.0
    rms = float(np.sqrt(np.mean(np.square(y))))
    slope = (
        float(np.polyfit(x, y, 1)[0] * 3600.0) if y.size > 1 and np.ptp(x) > 0 else 0.0
    )
    return Statistics(
        count=int(y.size),
        mean=mean,
        minimum=float(np.min(y)),
        maximum=float(np.max(y)),
        peak_to_peak=float(np.ptp(y)),
        std=std,
        rms=rms,
        median=float(np.median(y)),
        noise_ppm=float(std / abs(mean) * 1e6) if mean != 0 else np.nan,
        drift_per_hour=slope,
    )


def estimate_sample_period(elapsed_s: np.ndarray | list[float]) -> float:
    x = np.asarray(elapsed_s, dtype=float)
    differences = np.diff(x[np.isfinite(x)])
    differences = differences[differences > 0]
    return float(np.median(differences)) if differences.size else 1.0


def spectrum(
    values: np.ndarray | list[float],
    sample_period_s: float,
) -> dict[str, np.ndarray]:
    y = np.asarray(values, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 4 or sample_period_s <= 0:
        empty = np.asarray([], dtype=float)
        return {"frequency": empty, "amplitude": empty, "asd": empty}
    detrended = signal.detrend(y, type="linear")
    window = signal.windows.hann(y.size, sym=False)
    coherent_gain = np.mean(window)
    amplitude = np.abs(np.fft.rfft(detrended * window)) * 2.0 / (y.size * coherent_gain)
    frequency = np.fft.rfftfreq(y.size, d=sample_period_s)
    if amplitude.size:
        amplitude[0] *= 0.5
        if y.size % 2 == 0:
            amplitude[-1] *= 0.5
    fs = 1.0 / sample_period_s
    nperseg = min(2048, y.size)
    welch_frequency, psd = signal.welch(
        detrended,
        fs=fs,
        window="hann",
        nperseg=nperseg,
        detrend=False,
        scaling="density",
    )
    asd = np.sqrt(np.maximum(psd, 0.0))
    return {
        "frequency": frequency,
        "amplitude": amplitude,
        "asd_frequency": welch_frequency,
        "asd": asd,
    }


def allan_deviation(
    values: np.ndarray | list[float],
    sample_period_s: float,
    normalize: bool = False,
    max_points: int = 36,
) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(values, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 4 or sample_period_s <= 0:
        return np.asarray([]), np.asarray([])
    if normalize:
        mean = np.mean(y)
        if mean != 0:
            y = y / mean
    max_m = max(1, y.size // 3)
    clusters = np.unique(
        np.maximum(
            1,
            np.logspace(0, np.log10(max_m), min(max_points, max_m)).astype(int),
        )
    )
    taus: list[float] = []
    deviations: list[float] = []
    cumulative = np.concatenate(([0.0], np.cumsum(y)))
    for m in clusters:
        if y.size - 2 * m + 1 < 1:
            continue
        averages = (cumulative[m:] - cumulative[:-m]) / m
        delta = averages[m:] - averages[:-m]
        if delta.size:
            taus.append(float(m * sample_period_s))
            deviations.append(float(np.sqrt(0.5 * np.mean(delta * delta))))
    return np.asarray(taus), np.asarray(deviations)


def linear_fit(
    elapsed_s: np.ndarray | list[float],
    values: np.ndarray | list[float],
) -> tuple[np.ndarray, float, float]:
    x, y = _finite_xy(values, elapsed_s)
    if y.size < 2 or np.ptp(x) == 0:
        return np.full_like(y, np.nan), np.nan, np.nan
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residual = y - fitted
    total = y - np.mean(y)
    denominator = float(np.sum(total * total))
    r_squared = (
        1.0 - float(np.sum(residual * residual)) / denominator if denominator else 1.0
    )
    return fitted, float(slope * 3600.0), r_squared


def rolling_mean(values: np.ndarray | list[float], window: int) -> np.ndarray:
    y = np.asarray(values, dtype=float)
    if window <= 1 or y.size == 0:
        return y.copy()
    window = min(int(window), y.size)
    kernel = np.ones(window, dtype=float) / window
    valid = np.convolve(y, kernel, mode="valid")
    prefix = np.full(window - 1, np.nan)
    return np.concatenate((prefix, valid))


def sigma_mask(values: np.ndarray | list[float], threshold: float) -> np.ndarray:
    y = np.asarray(values, dtype=float)
    if y.size < 2 or threshold <= 0:
        return np.isfinite(y)
    median = np.nanmedian(y)
    mad = np.nanmedian(np.abs(y - median))
    robust_sigma = 1.4826 * mad
    if not np.isfinite(robust_sigma) or robust_sigma == 0:
        robust_sigma = np.nanstd(y)
    if not np.isfinite(robust_sigma) or robust_sigma == 0:
        return np.isfinite(y)
    return np.isfinite(y) & (np.abs(y - median) <= threshold * robust_sigma)
