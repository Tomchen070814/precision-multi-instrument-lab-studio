import numpy as np

from hp3458a_studio.analysis import (
    allan_deviation,
    descriptive_stats,
    linear_fit,
    sigma_mask,
    spectrum,
)


def test_descriptive_statistics_and_drift():
    x = np.arange(10, dtype=float)
    y = 2.0 + 0.5 * x
    stats = descriptive_stats(y, x)
    assert stats.count == 10
    assert np.isclose(stats.mean, 4.25)
    assert np.isclose(stats.minimum, 2.0)
    assert np.isclose(stats.maximum, 6.5)
    assert np.isclose(stats.peak_to_peak, 4.5)
    assert np.isclose(stats.drift_per_hour, 1800.0)


def test_spectrum_finds_tone_and_returns_asd():
    sample_period = 0.001
    x = np.arange(4096) * sample_period
    y = np.sin(2 * np.pi * 50 * x)
    result = spectrum(y, sample_period)
    peak = result["frequency"][np.argmax(result["amplitude"][1:]) + 1]
    assert abs(peak - 50) < 0.5
    assert result["asd"].size > 0
    assert np.all(result["asd"] >= 0)


def test_allan_constant_signal_is_zero():
    tau, deviation = allan_deviation(np.ones(128), 1.0)
    assert tau.size > 0
    assert np.allclose(deviation, 0.0)


def test_linear_fit():
    x = np.linspace(0, 20, 100)
    y = 10 + 2e-6 * x
    fitted, drift_hour, r_squared = linear_fit(x, y)
    assert np.allclose(fitted, y)
    assert np.isclose(drift_hour, 0.0072)
    assert r_squared > 0.999999


def test_sigma_mask_removes_outlier():
    y = np.asarray([1.0, 1.01, 0.99, 1.0, 100.0])
    mask = sigma_mask(y, 5.0)
    assert mask.tolist() == [True, True, True, True, False]
