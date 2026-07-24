from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import numpy as np


class MeasurementFunction(str, Enum):
    DC_VOLTAGE = "直流电压"
    AC_VOLTAGE = "交流电压"
    RESISTANCE_2W = "二线电阻"
    RESISTANCE_4W = "四线电阻"
    DC_CURRENT = "直流电流"
    AC_CURRENT = "交流电流"
    AC_DC_VOLTAGE = "交直流电压"
    AC_DC_CURRENT = "交直流电流"
    FREQUENCY = "频率"
    PERIOD = "周期"
    DIGITIZE_DC = "高速采样 DC"
    DIGITIZE_AC = "高速采样 AC"

    @property
    def unit(self) -> str:
        return {
            self.DC_VOLTAGE: "V",
            self.AC_VOLTAGE: "V",
            self.RESISTANCE_2W: "Ω",
            self.RESISTANCE_4W: "Ω",
            self.DC_CURRENT: "A",
            self.AC_CURRENT: "A",
            self.AC_DC_VOLTAGE: "V",
            self.AC_DC_CURRENT: "A",
            self.FREQUENCY: "Hz",
            self.PERIOD: "s",
            self.DIGITIZE_DC: "V",
            self.DIGITIZE_AC: "V",
        }[self]

    @property
    def command(self) -> str:
        return {
            self.DC_VOLTAGE: "DCV",
            self.AC_VOLTAGE: "ACV",
            self.RESISTANCE_2W: "OHM",
            self.RESISTANCE_4W: "OHMF",
            self.DC_CURRENT: "DCI",
            self.AC_CURRENT: "ACI",
            self.AC_DC_VOLTAGE: "ACDCV",
            self.AC_DC_CURRENT: "ACDCI",
            self.FREQUENCY: "FREQ",
            self.PERIOD: "PER",
            self.DIGITIZE_DC: "DSDC",
            self.DIGITIZE_AC: "DSAC",
        }[self]


class InstrumentModel(str, Enum):
    """Instrument adapters supported by the channel-agnostic acquisition core."""

    KEYSIGHT_3458A = "keysight_3458a"
    KEYSIGHT_34465A = "keysight_34465a"
    KEYSIGHT_34470A = "keysight_34470a"
    FLUKE_8588A = "fluke_8588a"
    FLUKE_8508A = "fluke_8508a"
    FLUKE_8846A = "fluke_8846a"
    KEITHLEY_DMM7510 = "keithley_dmm7510"
    ROHDE_SCHWARZ_HMC8012 = "rohde_schwarz_hmc8012"
    RIGOL_DM3068 = "rigol_dm3068"
    SIGLENT_SDM3065X = "siglent_sdm3065x"
    GW_INSTEK_GDM9061 = "gw_instek_gdm9061"
    HIOKI_DM7276 = "hioki_dm7276"
    YOKOGAWA_DM7560 = "yokogawa_dm7560"
    PICOTEST_M3510A = "picotest_m3510a"

    @property
    def display_name(self) -> str:
        return {
            self.KEYSIGHT_3458A: "Keysight 3458A",
            self.KEYSIGHT_34465A: "Keysight 34465A",
            self.KEYSIGHT_34470A: "Keysight 34470A",
            self.FLUKE_8588A: "Fluke 8588A",
            self.FLUKE_8508A: "Fluke 8508A",
            self.FLUKE_8846A: "Fluke 8846A",
            self.KEITHLEY_DMM7510: "Keithley DMM7510",
            self.ROHDE_SCHWARZ_HMC8012: "Rohde & Schwarz HMC8012",
            self.RIGOL_DM3068: "Rigol DM3068",
            self.SIGLENT_SDM3065X: "Siglent SDM3065X",
            self.GW_INSTEK_GDM9061: "GW Instek GDM-9061",
            self.HIOKI_DM7276: "Hioki DM7276",
            self.YOKOGAWA_DM7560: "Yokogawa DM7560",
            self.PICOTEST_M3510A: "Picotest M3510A",
        }[self]

    @property
    def short_name(self) -> str:
        return {
            self.KEYSIGHT_3458A: "3458A",
            self.KEYSIGHT_34465A: "34465A",
            self.KEYSIGHT_34470A: "34470A",
            self.FLUKE_8588A: "8588A",
            self.FLUKE_8508A: "8508A",
            self.FLUKE_8846A: "8846A",
            self.KEITHLEY_DMM7510: "DMM7510",
            self.ROHDE_SCHWARZ_HMC8012: "HMC8012",
            self.RIGOL_DM3068: "DM3068",
            self.SIGLENT_SDM3065X: "SDM3065X",
            self.GW_INSTEK_GDM9061: "GDM-9061",
            self.HIOKI_DM7276: "DM7276",
            self.YOKOGAWA_DM7560: "DM7560",
            self.PICOTEST_M3510A: "M3510A",
        }[self]

    @property
    def supports_burst(self) -> bool:
        return self is self.KEYSIGHT_3458A

    @property
    def manufacturer(self) -> str:
        return {
            self.KEYSIGHT_3458A: "Keysight",
            self.KEYSIGHT_34465A: "Keysight",
            self.KEYSIGHT_34470A: "Keysight",
            self.FLUKE_8588A: "Fluke",
            self.FLUKE_8508A: "Fluke",
            self.FLUKE_8846A: "Fluke",
            self.KEITHLEY_DMM7510: "Keithley",
            self.ROHDE_SCHWARZ_HMC8012: "Rohde & Schwarz",
            self.RIGOL_DM3068: "Rigol",
            self.SIGLENT_SDM3065X: "Siglent",
            self.GW_INSTEK_GDM9061: "GW Instek",
            self.HIOKI_DM7276: "Hioki",
            self.YOKOGAWA_DM7560: "Yokogawa",
            self.PICOTEST_M3510A: "Picotest",
        }[self]

    @property
    def uses_hpib_commands(self) -> bool:
        """Return whether this model uses the legacy 3458A HP-IB command set."""
        return self is self.KEYSIGHT_3458A

    @property
    def uses_scpi_commands(self) -> bool:
        """Return whether this model is handled by a SCPI profile."""
        return self not in {
            self.KEYSIGHT_3458A,
            self.FLUKE_8508A,
        }

    @property
    def requires_gpib(self) -> bool:
        """Return whether the selected driver requires an IEEE-488 resource."""
        return self in {
            self.KEYSIGHT_3458A,
            self.FLUKE_8508A,
        }

    @property
    def supports_autozero_control(self) -> bool:
        """Return whether the platform can safely command Autozero."""
        return self not in {
            self.FLUKE_8588A,
            self.FLUKE_8508A,
        }

    @property
    def nplc_bounds(self) -> tuple[float, float]:
        """Return validated NPLC limits for the platform control."""
        if self is self.FLUKE_8588A:
            return (0.0, 600.0)
        if self is self.FLUKE_8508A:
            # The 8508A accepts resolution/FAST commands rather than NPLC.
            # This range covers its documented 5.5- to 8.5-digit integration
            # choices; the driver maps the requested value to the closest mode.
            return (0.0, 1024.0)
        return (0.0, 1000.0)

    @property
    def supported_functions(self) -> tuple[MeasurementFunction, ...]:
        """Measurement functions exposed by this model profile."""
        if self is self.KEYSIGHT_3458A:
            return (
                MeasurementFunction.DC_VOLTAGE,
                MeasurementFunction.AC_VOLTAGE,
                MeasurementFunction.AC_DC_VOLTAGE,
                MeasurementFunction.RESISTANCE_2W,
                MeasurementFunction.RESISTANCE_4W,
                MeasurementFunction.DC_CURRENT,
                MeasurementFunction.AC_CURRENT,
                MeasurementFunction.AC_DC_CURRENT,
                MeasurementFunction.FREQUENCY,
                MeasurementFunction.PERIOD,
            )
        if self is self.HIOKI_DM7276:
            return (MeasurementFunction.DC_VOLTAGE,)
        if self is self.FLUKE_8508A:
            return (
                MeasurementFunction.DC_VOLTAGE,
                MeasurementFunction.AC_VOLTAGE,
                MeasurementFunction.RESISTANCE_2W,
                MeasurementFunction.RESISTANCE_4W,
                MeasurementFunction.DC_CURRENT,
                MeasurementFunction.AC_CURRENT,
            )
        return (
            MeasurementFunction.DC_VOLTAGE,
            MeasurementFunction.AC_VOLTAGE,
            MeasurementFunction.RESISTANCE_2W,
            MeasurementFunction.RESISTANCE_4W,
            MeasurementFunction.DC_CURRENT,
            MeasurementFunction.AC_CURRENT,
            MeasurementFunction.FREQUENCY,
            MeasurementFunction.PERIOD,
        )


@dataclass(slots=True)
class Measurement:
    elapsed_s: float
    value: float
    unit: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    internal_temperature_c: float | None = None


@dataclass
class SessionData:
    elapsed_s: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    timestamps: array = field(default_factory=lambda: array("d"))
    unit: str = "V"
    source: str = "演示模式"
    temperatures_c: list[float] = field(default_factory=list)
    channel: str = ""
    instrument_model: str = ""
    resource: str = ""

    def append(self, measurement: Measurement) -> None:
        self.elapsed_s.append(float(measurement.elapsed_s))
        self.values.append(float(measurement.value))
        self.timestamps.append(float(measurement.timestamp.timestamp()))
        self.unit = measurement.unit
        self.temperatures_c.append(
            float(measurement.internal_temperature_c)
            if measurement.internal_temperature_c is not None
            else np.nan
        )

    def clear(self) -> None:
        self.elapsed_s.clear()
        self.values.clear()
        self.timestamps.clear()
        self.temperatures_c.clear()

    def replace(
        self,
        elapsed_s: np.ndarray,
        values: np.ndarray,
        unit: str = "V",
        source: str = "CSV",
    ) -> None:
        self.elapsed_s = np.asarray(elapsed_s, dtype=float).tolist()
        self.values = np.asarray(values, dtype=float).tolist()
        original_times = np.asarray(self.elapsed_s, dtype=float)
        if original_times.size and original_times[0] > 1_000_000_000:
            self.timestamps = array("d", (float(t) for t in original_times))
        else:
            start = datetime.now(timezone.utc)
            self.timestamps = array(
                "d",
                (
                    (
                        start + timedelta(seconds=float(t - original_times[0]))
                    ).timestamp()
                    for t in original_times
                )
                if original_times.size
                else (),
            )
        if self.elapsed_s:
            first = self.elapsed_s[0]
            self.elapsed_s = [float(t - first) for t in self.elapsed_s]
        self.unit = unit
        self.source = source
        self.temperatures_c = [np.nan] * len(self.values)

    @property
    def x(self) -> np.ndarray:
        return np.asarray(self.elapsed_s, dtype=float)

    @property
    def y(self) -> np.ndarray:
        return np.asarray(self.values, dtype=float)

    @property
    def temperature(self) -> np.ndarray:
        return np.asarray(self.temperatures_c, dtype=float)

    @property
    def wall_clock_x(self) -> np.ndarray:
        """Return epoch seconds for the real acquisition timestamps.

        Imported or legacy sessions may not have a timestamp for every point.
        In that case a stable wall-clock axis is reconstructed from the first
        timestamp and the recorded elapsed time instead of falling back to a
        misleading zero-based axis.
        """
        if not self.values:
            return np.asarray([], dtype=float)
        if len(self.timestamps) == len(self.values):
            return np.asarray(self.timestamps, dtype=float).copy()
        start = (
            float(self.timestamps[0])
            if self.timestamps
            else datetime.now(timezone.utc).timestamp()
        )
        elapsed = self.x
        if elapsed.size:
            elapsed = elapsed - elapsed[0]
        return start + elapsed

    def __len__(self) -> int:
        return len(self.values)
