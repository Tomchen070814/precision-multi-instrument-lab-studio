from __future__ import annotations

import logging
import math
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

import numpy as np

from .models import InstrumentModel, Measurement, MeasurementFunction

logger = logging.getLogger(__name__)

try:
    import pyvisa
except ImportError:  # pragma: no cover - converted to a useful runtime error
    pyvisa = None


NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")

_GPIB_LOCKS_GUARD = threading.Lock()
_GPIB_LOCKS: dict[str, threading.RLock] = {}


def gpib_interface_name(resource_name: str) -> str:
    """Return the VISA interface portion, e.g. ``GPIB0``."""
    return resource_name.strip().upper().split("::", 1)[0]


def gpib_bus_lock(resource_name: str) -> threading.RLock:
    """Return the process-wide lock shared by instruments on one GPIB bus."""
    interface = gpib_interface_name(resource_name)
    with _GPIB_LOCKS_GUARD:
        return _GPIB_LOCKS.setdefault(interface, threading.RLock())


RANGES: dict[MeasurementFunction, list[tuple[str, str]]] = {
    MeasurementFunction.DC_VOLTAGE: [
        ("自动", "AUTO"),
        ("100 mV", "0.1"),
        ("1 V", "1"),
        ("10 V", "10"),
        ("100 V", "100"),
        ("1000 V", "1000"),
    ],
    MeasurementFunction.AC_VOLTAGE: [
        ("自动", "AUTO"),
        ("10 mV", "0.01"),
        ("100 mV", "0.1"),
        ("1 V", "1"),
        ("10 V", "10"),
        ("100 V", "100"),
        ("1000 V", "1000"),
    ],
    MeasurementFunction.AC_DC_VOLTAGE: [
        ("自动", "AUTO"),
        ("10 mV", "0.01"),
        ("100 mV", "0.1"),
        ("1 V", "1"),
        ("10 V", "10"),
        ("100 V", "100"),
        ("1000 V", "1000"),
    ],
    MeasurementFunction.RESISTANCE_2W: [
        ("自动", "AUTO"),
        ("10 Ω", "10"),
        ("100 Ω", "100"),
        ("1 kΩ", "1E3"),
        ("10 kΩ", "1E4"),
        ("100 kΩ", "1E5"),
        ("1 MΩ", "1E6"),
        ("10 MΩ", "1E7"),
        ("100 MΩ", "1E8"),
        ("1 GΩ", "1E9"),
    ],
    MeasurementFunction.RESISTANCE_4W: [
        ("自动", "AUTO"),
        ("10 Ω", "10"),
        ("100 Ω", "100"),
        ("1 kΩ", "1E3"),
        ("10 kΩ", "1E4"),
        ("100 kΩ", "1E5"),
        ("1 MΩ", "1E6"),
        ("10 MΩ", "1E7"),
        ("100 MΩ", "1E8"),
        ("1 GΩ", "1E9"),
    ],
    MeasurementFunction.DC_CURRENT: [
        ("自动", "AUTO"),
        ("100 nA", "0.1E-6"),
        ("1 µA", "1E-6"),
        ("10 µA", "10E-6"),
        ("100 µA", "100E-6"),
        ("1 mA", "1E-3"),
        ("10 mA", "10E-3"),
        ("100 mA", "100E-3"),
        ("1 A", "1"),
    ],
    MeasurementFunction.AC_CURRENT: [
        ("自动", "AUTO"),
        ("100 µA", "100E-6"),
        ("1 mA", "1E-3"),
        ("10 mA", "10E-3"),
        ("100 mA", "100E-3"),
        ("1 A", "1"),
    ],
    MeasurementFunction.AC_DC_CURRENT: [
        ("自动", "AUTO"),
        ("100 µA", "100E-6"),
        ("1 mA", "1E-3"),
        ("10 mA", "10E-3"),
        ("100 mA", "100E-3"),
        ("1 A", "1"),
    ],
    MeasurementFunction.FREQUENCY: [("自动", "AUTO")],
    MeasurementFunction.PERIOD: [("自动", "AUTO")],
    MeasurementFunction.DIGITIZE_DC: [
        ("10 mV", "0.01"),
        ("100 mV", "0.1"),
        ("1 V", "1"),
        ("10 V", "10"),
        ("100 V", "100"),
        ("1000 V", "1000"),
    ],
    MeasurementFunction.DIGITIZE_AC: [
        ("10 mV", "0.01"),
        ("100 mV", "0.1"),
        ("1 V", "1"),
        ("10 V", "10"),
        ("100 V", "100"),
        ("1000 V", "1000"),
    ],
}


class InstrumentError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstrumentIdentity:
    model: str
    resource: str
    firmware: str = ""
    options: str = ""
    line_frequency_hz: float = 50.0


@dataclass(frozen=True)
class AcquisitionConfig:
    function: MeasurementFunction = MeasurementFunction.DC_VOLTAGE
    measurement_range: str = "AUTO"
    nplc: float = 10.0
    digits: int = 8
    autozero: str = "ON"
    sample_interval_s: float = 1.0
    max_samples: int | None = None


class InstrumentDriver(ABC):
    name = "Instrument"

    def __init__(self, config: AcquisitionConfig | None = None):
        self.config = config or AcquisitionConfig()
        self.connected = False
        self.started_at = 0.0
        self.identity = InstrumentIdentity(self.name, "")

    @abstractmethod
    def connect(self) -> InstrumentIdentity: ...

    @abstractmethod
    def configure(self, config: AcquisitionConfig) -> None: ...

    @abstractmethod
    def read_single(self, include_temperature: bool = False) -> Measurement: ...

    def disconnect(self) -> None:
        self.connected = False

    def cancel_pending_io(self) -> None:
        """Best-effort cancellation hook used during application shutdown.

        Most drivers only need the worker stop event. VISA reads are different:
        a native driver call can remain blocked until its timeout expires, so a
        concrete driver may close the active session to release that call.
        """


class SimulatorDriver(InstrumentDriver):
    name = "DMM 数字孪生"

    def __init__(
        self,
        config: AcquisitionConfig | None = None,
        seed: int = 3458,
        resource_name: str = "SIM::3458A",
        instrument_model: InstrumentModel = InstrumentModel.KEYSIGHT_3458A,
    ):
        super().__init__(config)
        self._random = random.Random(seed)
        self.resource_name = resource_name
        self.instrument_model = instrument_model

    def connect(self) -> InstrumentIdentity:
        self.connected = True
        self.started_at = time.monotonic()
        model = (
            "HEWLETT-PACKARD,3458A (SIMULATOR)"
            if self.instrument_model is InstrumentModel.KEYSIGHT_3458A
            else (
                f"{self.instrument_model.manufacturer.upper()},"
                f"{self.instrument_model.short_name} (SIMULATOR)"
            )
        )
        self.identity = InstrumentIdentity(
            model=model,
            resource=self.resource_name,
            firmware=(
                "9.2,9.1"
                if self.instrument_model is InstrumentModel.KEYSIGHT_3458A
                else "SIM-1.0"
            ),
            options=(
                "1" if self.instrument_model is InstrumentModel.KEYSIGHT_3458A else ""
            ),
            line_frequency_hz=50.0,
        )
        return self.identity

    def configure(self, config: AcquisitionConfig) -> None:
        self.config = config

    def _base_value(self) -> float:
        return {
            MeasurementFunction.DC_VOLTAGE: 10.0,
            MeasurementFunction.AC_VOLTAGE: 1.0,
            MeasurementFunction.AC_DC_VOLTAGE: 1.0,
            MeasurementFunction.RESISTANCE_2W: 10_000.0,
            MeasurementFunction.RESISTANCE_4W: 10_000.0,
            MeasurementFunction.DC_CURRENT: 0.010,
            MeasurementFunction.AC_CURRENT: 0.010,
            MeasurementFunction.AC_DC_CURRENT: 0.010,
            MeasurementFunction.FREQUENCY: 10_000.0,
            MeasurementFunction.PERIOD: 0.0001,
            MeasurementFunction.DIGITIZE_DC: 1.0,
            MeasurementFunction.DIGITIZE_AC: 1.0,
        }[self.config.function]

    def read_single(self, include_temperature: bool = False) -> Measurement:
        if not self.connected:
            raise InstrumentError("演示仪表尚未连接")
        elapsed = time.monotonic() - self.started_at
        base = self._base_value()
        scale = abs(base) if base else 1.0
        nplc_noise = max(0.08, 1.0 / math.sqrt(max(self.config.nplc, 1e-4)))
        warmup = -5.5e-6 * scale * math.exp(-elapsed / 100.0)
        drift = 0.14e-6 * scale * elapsed / 3600.0
        hum = 0.65e-6 * scale * math.sin(2 * math.pi * 0.37 * elapsed)
        slow = 1.8e-6 * scale * math.sin(2 * math.pi * elapsed / 95.0)
        noise = self._random.gauss(0.0, 0.7e-6 * scale * nplc_noise)
        temperature = 23.0 + 0.55 * (1 - math.exp(-elapsed / 180.0))
        temperature += 0.08 * math.sin(2 * math.pi * elapsed / 240.0)
        return Measurement(
            elapsed_s=elapsed,
            value=base + warmup + drift + hum + slow + noise,
            unit=self.config.function.unit,
            timestamp=datetime.now(timezone.utc),
            internal_temperature_c=temperature if include_temperature else None,
        )

    def acquire_burst(
        self,
        count: int,
        interval_s: float,
        aperture_s: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        count = max(1, int(count))
        x = np.arange(count, dtype=float) * interval_s
        frequency = min(0.08 / max(interval_s, 1e-9), 1234.0)
        rng = np.random.default_rng(3458)
        y = self._base_value() + 0.015 * np.sin(2 * np.pi * frequency * x)
        y += rng.normal(0, max(2e-6, aperture_s * 0.01), count)
        return x, y


def parse_ascii_values(payload: str | bytes) -> np.ndarray:
    if isinstance(payload, bytes):
        payload = payload.decode("ascii", errors="ignore")
    values = [float(match.group(0)) for match in NUMBER_PATTERN.finditer(payload)]
    return np.asarray(values, dtype=float)


def discover_visa_resources(backend: str = "") -> list[str]:
    if pyvisa is None:
        return []
    try:
        manager = pyvisa.ResourceManager(backend or "")
        resources = list(manager.list_resources())
        manager.close()
        return resources
    except Exception:
        logger.exception("VISA resource discovery failed")
        return []


def is_gpib_instrument_resource(resource_name: str) -> bool:
    """Return True for VISA GPIB instrument resources usable by a 3458A."""
    normalized = resource_name.strip().upper()
    return normalized.startswith("GPIB") and normalized.endswith("::INSTR")


def gpib_instrument_resources(resources: list[str] | tuple[str, ...]) -> list[str]:
    """Filter a VISA resource list to GPIB instruments without changing order."""
    return [resource for resource in resources if is_gpib_instrument_resource(resource)]


def is_visa_instrument_resource(resource_name: str) -> bool:
    """Return whether a VISA resource can represent a supported DMM session."""
    normalized = resource_name.strip().upper()
    return normalized.endswith(("::INSTR", "::SOCKET"))


def visa_instrument_resources(
    resources: list[str] | tuple[str, ...],
) -> list[str]:
    """Filter resource discovery without excluding USB/LAN SCPI instruments."""
    return [resource for resource in resources if is_visa_instrument_resource(resource)]


def choose_gpib_assignments(
    resources: list[str] | tuple[str, ...],
    current_by_channel: dict[str, str],
    running_channels: set[str] | None = None,
) -> dict[str, str]:
    """Choose deterministic A/B/C addresses after a VISA scan.

    A fresh scan is authoritative when both channels are stopped, so stale
    selector values are not retained. Running channels keep their active
    address and stopped channels receive an available non-conflicting resource.
    """
    unique_resources = list(dict.fromkeys(resources))
    if not unique_resources:
        return dict(current_by_channel)

    running = running_channels or set()
    channels = tuple(current_by_channel)
    assignments: dict[str, str] = {}
    occupied: set[str] = set()
    for channel in channels:
        if channel in running:
            current = current_by_channel[channel]
            assignments[channel] = current
            occupied.add(current.strip().upper())

    stopped = [channel for channel in channels if channel not in running]
    if not running:
        for index, channel in enumerate(stopped):
            # Do not silently duplicate the final detected resource when a
            # reserved channel has no corresponding physical instrument.
            assignments[channel] = (
                unique_resources[index]
                if index < len(unique_resources)
                else current_by_channel[channel]
            )
        return assignments

    available_keys = {resource.strip().upper() for resource in unique_resources}
    for channel in stopped:
        current = current_by_channel[channel]
        current_key = current.strip().upper()
        if current_key in available_keys and current_key not in occupied:
            selected = current
        else:
            selected = next(
                (
                    resource
                    for resource in unique_resources
                    if resource.strip().upper() not in occupied
                ),
                current,
            )
        assignments[channel] = selected
        occupied.add(selected.strip().upper())
    return assignments


class Keysight3458ADriver(InstrumentDriver):
    name = "Keysight 3458A"

    def __init__(
        self,
        resource_name: str = "GPIB0::22::INSTR",
        config: AcquisitionConfig | None = None,
        visa_backend: str = "",
    ):
        super().__init__(config)
        self.resource_name = resource_name
        self.visa_backend = visa_backend
        self._manager = None
        self._instrument = None
        self._last_temperature = np.nan
        self._bus_lock = gpib_bus_lock(resource_name)

    def _require_instrument(self):
        if self._instrument is None:
            raise InstrumentError("3458A 尚未连接")
        return self._instrument

    def _query(self, command: str) -> str:
        instrument = self._require_instrument()
        try:
            # A query must remain atomic on a shared GPIB bus: another
            # instrument may not insert a transfer between its write and read.
            with self._bus_lock:
                instrument.write(command)
                return str(instrument.read()).strip()
        except Exception as exc:
            raise InstrumentError(f"执行 {command!r} 失败: {exc}") from exc

    def connect(self) -> InstrumentIdentity:
        if not is_gpib_instrument_resource(self.resource_name):
            raise InstrumentError(
                "3458A 只支持 GPIB 通信，不能使用 "
                f"{self.resource_name!r}。通过 USB-GPIB 转换器连接后，应在 "
                "NI MAX 或 Keysight Connection Expert 中选择类似 "
                "'GPIB0::22::INSTR' 的仪表资源；不要选择 USB0 资源。"
            )
        if pyvisa is None:
            raise InstrumentError("缺少 PyVISA，无法使用 GPIB")
        try:
            # All instruments behind one GPIB-USB controller share a serial
            # command bus.  VISA sessions are independent, but the underlying
            # interface is not; serialize connection setup and identification.
            with self._bus_lock:
                self._manager = pyvisa.ResourceManager(self.visa_backend or "")
                self._instrument = self._manager.open_resource(self.resource_name)
                self._instrument.timeout = 15_000
                self._instrument.write_termination = "\n"
                self._instrument.read_termination = "\n"
                try:
                    self._instrument.clear()
                except Exception as exc:  # noqa: BLE001 - vendor VISA errors vary
                    # Some mixed NI/Keysight VISA installations reject SDC
                    # (viClear) even though normal GPIB reads and writes work.
                    # ID? below is the authoritative connection check.
                    logger.warning(
                        "VISA clear rejected; continuing with ID? | "
                        "resource=%s | error=%s",
                        self.resource_name,
                        exc,
                    )
                self._instrument.write("END ALWAYS")
                model = self._query("ID?")
                if "3458" not in model.upper():
                    raise InstrumentError(
                        f"{self.resource_name} 返回 {model!r}，不像 3458A"
                    )
                firmware = self._query("REV?")
                options = self._query("OPT?")
                line_text = self._query("LINE?")
            line_values = parse_ascii_values(line_text)
            line_frequency = float(line_values[0]) if line_values.size else 50.0
            self.identity = InstrumentIdentity(
                model=model,
                resource=self.resource_name,
                firmware=firmware,
                options=options,
                line_frequency_hz=line_frequency,
            )
            self.connected = True
            self.started_at = time.monotonic()
            logger.info(
                "Instrument connected | resource=%s | model=%s",
                self.resource_name,
                self.identity.model,
            )
            return self.identity
        except InstrumentError:
            self.disconnect()
            raise
        except Exception as exc:
            self.disconnect()
            error_text = str(exc)
            if "VI_ERROR_NCIC" in error_text or "-1073807264" in error_text:
                raise InstrumentError(
                    f"GPIB 接口没有取得总线控制权，无法连接 {self.resource_name}。"
                    "请关闭其他占用仪表的软件，并在 NI MAX 或 Keysight "
                    "Connection Expert 中确认 GPIB 接口已启用 System Controller，"
                    "然后重新扫描。"
                ) from exc
            if "VI_ERROR_NLISTENERS" in error_text or "-1073807265" in error_text:
                raise InstrumentError(
                    f"{self.resource_name} 没有响应。请在 NI MAX 中确认该地址"
                    "仍可扫描到，并用 Interactive Control 向它发送 ID?；"
                    "同时关闭 NI MAX、Connection Expert 或其他正在占用"
                    "仪表通信的窗口后重试。"
                ) from exc
            raise InstrumentError(
                f"无法通过 VISA 连接 {self.resource_name}: {exc}"
            ) from exc

    def configure(self, config: AcquisitionConfig) -> None:
        instrument = self._require_instrument()
        if config.function in (
            MeasurementFunction.DIGITIZE_DC,
            MeasurementFunction.DIGITIZE_AC,
        ):
            raise InstrumentError("高速采样请使用突发采集")
        autozero = config.autozero.upper()
        if autozero not in {"ON", "OFF", "ONCE"}:
            raise InstrumentError("Autozero 必须是 ON、OFF 或 ONCE")
        command = ";".join(
            [
                "PRESET NORM",
                "END ALWAYS",
                "OFORMAT ASCII",
                f"{config.function.command} {config.measurement_range}",
                f"NPLC {config.nplc:.9g}",
                f"NDIG {int(config.digits)}",
                f"AZERO {autozero}",
            ]
        )
        try:
            with self._bus_lock:
                instrument.timeout = max(
                    15_000,
                    int(
                        (config.nplc / max(self.identity.line_frequency_hz, 1.0) + 8)
                        * 1000
                    ),
                )
                instrument.write(command)
                error_values = parse_ascii_values(self._query("ERR?"))
            if error_values.size and int(error_values[0]) != 0:
                raise InstrumentError(f"3458A 配置错误，ERR={int(error_values[0])}")
            logger.info(
                "Instrument configured | resource=%s | function=%s | "
                "range=%s | nplc=%s | digits=%s | autozero=%s",
                self.resource_name,
                config.function.command,
                config.measurement_range,
                config.nplc,
                config.digits,
                config.autozero,
            )
        except InstrumentError:
            raise
        except Exception as exc:
            raise InstrumentError(f"配置 3458A 失败: {exc}") from exc
        self.config = config

    def read_temperature(self) -> float:
        values = parse_ascii_values(self._query("TEMP?"))
        if not values.size:
            raise InstrumentError("TEMP? 未返回温度")
        self._last_temperature = float(values[0])
        return self._last_temperature

    def read_single(self, include_temperature: bool = False) -> Measurement:
        instrument = self._require_instrument()
        try:
            # Trigger writes are deliberately short and independently locked,
            # allowing A and B to start their integrations close together.
            with self._bus_lock:
                instrument.write("TRIG SGL")
            with self._bus_lock:
                values = parse_ascii_values(instrument.read())
            if not values.size:
                raise InstrumentError("3458A 未返回有效读数")
            temperature = self.read_temperature() if include_temperature else None
            return Measurement(
                elapsed_s=time.monotonic() - self.started_at,
                value=float(values[0]),
                unit=self.config.function.unit,
                timestamp=datetime.now(timezone.utc),
                internal_temperature_c=temperature,
            )
        except InstrumentError:
            raise
        except Exception as exc:
            raise InstrumentError(f"读取 3458A 失败: {exc}") from exc

    def acquire_burst(
        self,
        count: int,
        interval_s: float,
        aperture_s: float,
        function: MeasurementFunction = MeasurementFunction.DIGITIZE_DC,
        measurement_range: str = "10",
    ) -> tuple[np.ndarray, np.ndarray]:
        instrument = self._require_instrument()
        count = int(count)
        if not 1 <= count <= 148_000:
            raise InstrumentError("突发样本数必须在 1 到 148000 之间")
        if interval_s < 1e-5:
            raise InstrumentError("当前稳定传输模式的采样间隔不得小于 10 µs")
        if not 5e-7 <= aperture_s <= 1.0:
            raise InstrumentError("孔径时间必须在 500 ns 到 1 s 之间")
        if interval_s < aperture_s:
            raise InstrumentError("采样间隔不能小于孔径时间")
        if function not in (
            MeasurementFunction.DIGITIZE_DC,
            MeasurementFunction.DIGITIZE_AC,
        ):
            raise InstrumentError("突发采集功能必须选择 DSDC 或 DSAC")
        estimated_ms = int((count * interval_s + 12.0) * 1000)
        try:
            with self._bus_lock:
                instrument.timeout = max(30_000, estimated_ms)
            commands = [
                "PRESET FAST",
                "END ON",
                "OFORMAT ASCII",
                "MFORMAT SREAL",
                "MEM FIFO",
                "TARM HOLD",
                "TRIG HOLD",
                f"{function.command} {measurement_range}",
                f"APER {aperture_s:.9g}",
                f"NRDGS {count},TIMER",
                f"TIMER {interval_s:.9g}",
                "TRIG AUTO",
                "TARM SGL",
            ]
            with self._bus_lock:
                instrument.write(";".join(commands))
            time.sleep(min(count * interval_s + 0.25, 10.0))
            available_values = parse_ascii_values(self._query("MCOUNT?"))
            available = int(available_values[0]) if available_values.size else 0
            if available < count:
                deadline = time.monotonic() + max(10.0, count * interval_s + 2.0)
                while available < count and time.monotonic() < deadline:
                    time.sleep(0.05)
                    available_values = parse_ascii_values(self._query("MCOUNT?"))
                    available = int(available_values[0]) if available_values.size else 0
            if available < count:
                raise InstrumentError(f"突发采集超时：仅获得 {available}/{count} 点")
            previous_termination = instrument.read_termination
            with self._bus_lock:
                instrument.read_termination = None
                try:
                    instrument.write(f"RMEM 1,{count},1")
                    payload = instrument.read_raw()
                finally:
                    instrument.read_termination = previous_termination
            values = parse_ascii_values(payload)
            if values.size < count:
                raise InstrumentError(
                    f"读取缓存不完整：期望 {count} 点，收到 {values.size} 点"
                )
            elapsed = np.arange(count, dtype=float) * interval_s
            return elapsed, values[:count]
        except InstrumentError:
            raise
        except Exception as exc:
            raise InstrumentError(f"3458A 突发采集失败: {exc}") from exc
        finally:
            try:
                with self._bus_lock:
                    instrument.write(
                        "MEM OFF;TRIG HOLD;TARM HOLD;END ALWAYS;OFORMAT ASCII"
                    )
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                logger.warning(
                    "Failed to restore 3458A after burst | resource=%s | error=%s",
                    self.resource_name,
                    exc,
                )

    def disconnect(self) -> None:
        instrument = self._instrument
        self._instrument = None
        try:
            if instrument is not None:
                with self._bus_lock:
                    if self.connected:
                        try:
                            instrument.write("TRIG HOLD;TARM HOLD;MEM OFF;DISP ON")
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "Instrument reset during disconnect failed | "
                                "resource=%s | error=%s",
                                self.resource_name,
                                exc,
                            )
                    try:
                        instrument.close()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Instrument close failed | resource=%s | error=%s",
                            self.resource_name,
                            exc,
                        )
        finally:
            if self._manager is not None:
                try:
                    self._manager.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "VISA manager close failed | resource=%s | error=%s",
                        self.resource_name,
                        exc,
                    )
            self._manager = None
            super().disconnect()

    def cancel_pending_io(self) -> None:
        """Close the VISA resource so an in-flight native read returns.

        This method deliberately does not acquire the GPIB bus lock: the worker
        may currently hold that lock while blocked inside ``read``. VISA session
        close is the cancellation mechanism during shutdown; normal cleanup is
        still completed by ``disconnect`` in the worker's ``finally`` block.
        """
        instrument = self._instrument
        self._instrument = None
        if instrument is None:
            return
        try:
            instrument.close()
            logger.info(
                "Pending VISA I/O cancelled | resource=%s",
                self.resource_name,
            )
        except Exception as exc:  # noqa: BLE001 - vendor VISA errors vary
            logger.warning(
                "Pending VISA I/O cancellation failed | resource=%s | error=%s",
                self.resource_name,
                exc,
            )


SCPI_FUNCTION_PATHS: dict[MeasurementFunction, str] = {
    MeasurementFunction.DC_VOLTAGE: "VOLT:DC",
    MeasurementFunction.AC_VOLTAGE: "VOLT:AC",
    MeasurementFunction.RESISTANCE_2W: "RES",
    MeasurementFunction.RESISTANCE_4W: "FRES",
    MeasurementFunction.DC_CURRENT: "CURR:DC",
    MeasurementFunction.AC_CURRENT: "CURR:AC",
    MeasurementFunction.FREQUENCY: "FREQ",
    MeasurementFunction.PERIOD: "PER",
}

SCPI_NPLC_FUNCTIONS: frozenset[MeasurementFunction] = frozenset(
    {
        MeasurementFunction.DC_VOLTAGE,
        MeasurementFunction.RESISTANCE_2W,
        MeasurementFunction.RESISTANCE_4W,
        MeasurementFunction.DC_CURRENT,
    }
)


@dataclass(frozen=True)
class ScpiDmmProfile:
    """Declarative command differences between SCPI-family instruments."""

    model: InstrumentModel
    idn_tokens: tuple[str, ...]
    selection_style: str = "configure"
    auto_in_configure: bool = False
    range_template: str | None = "SENS:{path}:RANG {range}"
    auto_range_template: str | None = "SENS:{path}:RANG:AUTO ON"
    nplc_template: str | None = "SENS:{path}:NPLC {nplc}"
    autozero_template: str | None = "SENS:{path}:ZERO:AUTO {autozero}"
    line_frequency_query: str | None = None
    error_query: str | None = "SYST:ERR?"
    read_query: str = "READ?"
    temperature_read_query: str | None = None
    temperature_query: str | None = None
    prepare_commands: tuple[str, ...] = ("*CLS", "ABOR")
    trigger_commands: tuple[str, ...] = (
        "TRIG:SOUR IMM",
        "SAMP:COUN 1",
    )


def _scpi_profile(
    model: InstrumentModel,
    *idn_tokens: str,
    **overrides,
) -> ScpiDmmProfile:
    return ScpiDmmProfile(
        model=model,
        idn_tokens=tuple(token.upper() for token in idn_tokens),
        **overrides,
    )


SCPI_DMM_PROFILES: dict[InstrumentModel, ScpiDmmProfile] = {
    InstrumentModel.KEYSIGHT_34465A: _scpi_profile(
        InstrumentModel.KEYSIGHT_34465A,
        "34465A",
        line_frequency_query="SYST:LFREQ?",
    ),
    InstrumentModel.KEYSIGHT_34470A: _scpi_profile(
        InstrumentModel.KEYSIGHT_34470A,
        "34470A",
        line_frequency_query="SYST:LFREQ?",
    ),
    InstrumentModel.FLUKE_8588A: _scpi_profile(
        InstrumentModel.FLUKE_8588A,
        "8588A",
        autozero_template=None,
        line_frequency_query="SYST:LFREQ?",
        error_query="SYST:ERR:NEXT?",
        temperature_query="SYST:TEMP?",
        trigger_commands=(
            "TRIG:RESET",
            "TRIG:SOUR IMM",
            "TRIG:COUN 1",
        ),
    ),
    InstrumentModel.FLUKE_8846A: _scpi_profile(
        InstrumentModel.FLUKE_8846A,
        "8846A",
        nplc_template="{path}:NPLC {nplc}",
        autozero_template="ZERO:AUTO {autozero}",
    ),
    InstrumentModel.KEITHLEY_DMM7510: _scpi_profile(
        InstrumentModel.KEITHLEY_DMM7510,
        "DMM7510",
        selection_style="sense",
        autozero_template="SENS:{path}:AZER {autozero}",
    ),
    InstrumentModel.ROHDE_SCHWARZ_HMC8012: _scpi_profile(
        InstrumentModel.ROHDE_SCHWARZ_HMC8012,
        "HMC8012",
        auto_in_configure=True,
        auto_range_template=None,
    ),
    InstrumentModel.RIGOL_DM3068: _scpi_profile(
        InstrumentModel.RIGOL_DM3068,
        "DM3068",
    ),
    InstrumentModel.SIGLENT_SDM3065X: _scpi_profile(
        InstrumentModel.SIGLENT_SDM3065X,
        "SDM3065X",
    ),
    InstrumentModel.GW_INSTEK_GDM9061: _scpi_profile(
        InstrumentModel.GW_INSTEK_GDM9061,
        "GDM-9061",
        "GDM9061",
    ),
    InstrumentModel.HIOKI_DM7276: _scpi_profile(
        InstrumentModel.HIOKI_DM7276,
        "DM7276",
        selection_style="sense_unquoted",
        temperature_read_query="READ? TEMP",
    ),
    InstrumentModel.YOKOGAWA_DM7560: _scpi_profile(
        InstrumentModel.YOKOGAWA_DM7560,
        "DM7560",
    ),
    InstrumentModel.PICOTEST_M3510A: _scpi_profile(
        InstrumentModel.PICOTEST_M3510A,
        "M3510A",
    ),
}


class ScpiDmmDriver(InstrumentDriver):
    """Profile-driven SCPI adapter over USB, LAN, serial or GPIB VISA."""

    _FUNCTION_PATHS: ClassVar[dict[MeasurementFunction, str]] = SCPI_FUNCTION_PATHS
    _NPLC_FUNCTIONS: ClassVar[frozenset[MeasurementFunction]] = SCPI_NPLC_FUNCTIONS

    def __init__(
        self,
        resource_name: str,
        instrument_model: InstrumentModel,
        config: AcquisitionConfig | None = None,
        visa_backend: str = "",
    ):
        if instrument_model not in SCPI_DMM_PROFILES:
            raise ValueError(f"{instrument_model.display_name} 没有 SCPI 设备配置")
        super().__init__(config)
        self.instrument_model = instrument_model
        self.profile = SCPI_DMM_PROFILES[instrument_model]
        self.name = instrument_model.display_name
        self.resource_name = resource_name
        self.visa_backend = visa_backend
        self._manager = None
        self._instrument = None
        self._resource_lock = gpib_bus_lock(resource_name)

    def _require_instrument(self):
        if self._instrument is None:
            raise InstrumentError(f"{self.name} 尚未连接")
        return self._instrument

    def _query(self, command: str) -> str:
        instrument = self._require_instrument()
        try:
            with self._resource_lock:
                instrument.write(command)
                return str(instrument.read()).strip()
        except Exception as exc:
            raise InstrumentError(f"执行 {command!r} 失败: {exc}") from exc

    def connect(self) -> InstrumentIdentity:
        if not is_visa_instrument_resource(self.resource_name):
            raise InstrumentError(f"{self.resource_name!r} 不是可用的 VISA 仪表资源")
        if pyvisa is None:
            raise InstrumentError(
                f"缺少 PyVISA，无法连接 {self.instrument_model.short_name}"
            )
        try:
            with self._resource_lock:
                self._manager = pyvisa.ResourceManager(self.visa_backend or "")
                self._instrument = self._manager.open_resource(self.resource_name)
                self._instrument.timeout = 15_000
                self._instrument.write_termination = "\n"
                self._instrument.read_termination = "\n"
                idn = self._query("*IDN?")
            normalized_idn = idn.upper()
            if not any(token in normalized_idn for token in self.profile.idn_tokens):
                expected = "/".join(self.profile.idn_tokens)
                raise InstrumentError(
                    f"{self.resource_name} 返回 {idn!r}；当前通道选择的是 "
                    f"{self.name}，身份应包含 {expected}"
                )
            fields = [field.strip() for field in idn.split(",")]
            firmware = fields[3] if len(fields) > 3 else ""
            line_frequency = 50.0
            if self.profile.line_frequency_query:
                try:
                    values = parse_ascii_values(
                        self._query(self.profile.line_frequency_query)
                    )
                    if values.size:
                        line_frequency = float(values[0])
                except InstrumentError:
                    logger.warning(
                        "Line-frequency query unavailable | model=%s | resource=%s",
                        self.name,
                        self.resource_name,
                    )
            self.identity = InstrumentIdentity(
                model=idn,
                resource=self.resource_name,
                firmware=firmware,
                line_frequency_hz=line_frequency,
            )
            self.connected = True
            self.started_at = time.monotonic()
            logger.info(
                "Instrument connected | profile=%s | resource=%s | idn=%s",
                self.instrument_model.value,
                self.resource_name,
                idn,
            )
            return self.identity
        except InstrumentError:
            self.disconnect()
            raise
        except Exception as exc:
            self.disconnect()
            raise InstrumentError(
                f"无法通过 VISA 连接 {self.resource_name}: {exc}"
            ) from exc

    def _selection_commands(
        self,
        config: AcquisitionConfig,
        path: str,
    ) -> list[str]:
        automatic = config.measurement_range.upper() == "AUTO"
        ranged_function = config.function not in {
            MeasurementFunction.FREQUENCY,
            MeasurementFunction.PERIOD,
        }
        if self.profile.selection_style.startswith("sense"):
            commands = [
                (
                    f"SENS:FUNC {path}"
                    if self.profile.selection_style == "sense_unquoted"
                    else f'SENS:FUNC "{path}"'
                )
            ]
            if ranged_function:
                template = (
                    self.profile.auto_range_template
                    if automatic
                    else self.profile.range_template
                )
                if template:
                    commands.append(
                        template.format(
                            path=path,
                            range=config.measurement_range,
                        )
                    )
            return commands
        range_suffix = ""
        if not automatic:
            range_suffix = f" {config.measurement_range}"
        elif self.profile.auto_in_configure and ranged_function:
            range_suffix = " AUTO"
        commands = [f"CONF:{path}{range_suffix}"]
        if automatic and ranged_function and self.profile.auto_range_template:
            commands.append(
                self.profile.auto_range_template.format(
                    path=path,
                    range=config.measurement_range,
                )
            )
        return commands

    def configure(self, config: AcquisitionConfig) -> None:
        if config.function not in self.instrument_model.supported_functions:
            raise InstrumentError(f"{self.name} 不支持 {config.function.value}")
        if config.function not in self._FUNCTION_PATHS:
            raise InstrumentError(
                f"{self.name} 当前 SCPI 配置未实现 {config.function.value}"
            )
        if config.autozero.upper() not in {"ON", "OFF", "ONCE"}:
            raise InstrumentError("Autozero 必须是 ON、OFF 或 ONCE")
        path = self._FUNCTION_PATHS[config.function]
        commands = list(self.profile.prepare_commands)
        commands.extend(self._selection_commands(config, path))
        commands.extend(self.profile.trigger_commands)
        if config.function in self._NPLC_FUNCTIONS:
            if self.profile.nplc_template:
                commands.append(
                    self.profile.nplc_template.format(
                        path=path,
                        nplc=f"{config.nplc:.9g}",
                    )
                )
            if self.profile.autozero_template:
                commands.append(
                    self.profile.autozero_template.format(
                        path=path,
                        autozero=config.autozero.upper(),
                    )
                )
        instrument = self._require_instrument()
        try:
            with self._resource_lock:
                instrument.timeout = max(
                    15_000,
                    int(
                        (config.nplc / max(self.identity.line_frequency_hz, 1.0) + 8)
                        * 1000
                    ),
                )
                for command in commands:
                    instrument.write(command)
            if self.profile.error_query:
                errors = self._query(self.profile.error_query)
                if errors and not errors.lstrip().startswith(("+0", "0")):
                    raise InstrumentError(f"{self.name} 配置错误：{errors}")
            self.config = config
            logger.info(
                "Instrument configured | profile=%s | resource=%s | "
                "function=%s | range=%s | nplc=%s",
                self.instrument_model.value,
                self.resource_name,
                config.function.command,
                config.measurement_range,
                config.nplc,
            )
        except InstrumentError:
            raise
        except Exception as exc:
            raise InstrumentError(f"配置 {self.name} 失败: {exc}") from exc

    def read_single(self, include_temperature: bool = False) -> Measurement:
        query = (
            self.profile.temperature_read_query
            if include_temperature and self.profile.temperature_read_query
            else self.profile.read_query
        )
        values = parse_ascii_values(self._query(query))
        if not values.size:
            raise InstrumentError(f"{self.name} 未返回有效读数")
        temperature = (
            float(values[1])
            if include_temperature
            and self.profile.temperature_read_query
            and values.size > 1
            else None
        )
        if (
            include_temperature
            and temperature is None
            and self.profile.temperature_query
        ):
            temperature_values = parse_ascii_values(
                self._query(self.profile.temperature_query)
            )
            if temperature_values.size:
                temperature = float(temperature_values[0])
        return Measurement(
            elapsed_s=time.monotonic() - self.started_at,
            value=float(values[0]),
            unit=self.config.function.unit,
            timestamp=datetime.now(timezone.utc),
            internal_temperature_c=temperature,
        )

    def disconnect(self) -> None:
        instrument = self._instrument
        self._instrument = None
        try:
            if instrument is not None:
                try:
                    instrument.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SCPI instrument close failed | profile=%s | "
                        "resource=%s | error=%s",
                        self.instrument_model.value,
                        self.resource_name,
                        exc,
                    )
        finally:
            if self._manager is not None:
                try:
                    self._manager.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SCPI VISA manager close failed | profile=%s | "
                        "resource=%s | error=%s",
                        self.instrument_model.value,
                        self.resource_name,
                        exc,
                    )
            self._manager = None
            super().disconnect()

    def cancel_pending_io(self) -> None:
        instrument = self._instrument
        self._instrument = None
        if instrument is None:
            return
        try:
            instrument.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SCPI pending I/O cancellation failed | profile=%s | "
                "resource=%s | error=%s",
                self.instrument_model.value,
                self.resource_name,
                exc,
            )


class Fluke8508ADriver(InstrumentDriver):
    """Native IEEE-488 adapter for the non-SCPI Fluke 8508A.

    The 8508A uses its own function messages (for example ``DCV ...`` and
    ``OHMS ...``) and the combined trigger/read query ``X?``. It must not be
    routed through the generic SCPI adapter.
    """

    name = "Fluke 8508A"

    _DC_INTEGRATION_PLC: ClassVar[dict[int, tuple[float, float]]] = {
        5: (0.165, 1.0),
        6: (1.0, 16.0),
        7: (64.0, 256.0),
        8: (256.0, 1024.0),
    }

    def __init__(
        self,
        resource_name: str,
        config: AcquisitionConfig | None = None,
        visa_backend: str = "",
    ):
        super().__init__(config)
        self.instrument_model = InstrumentModel.FLUKE_8508A
        self.resource_name = resource_name
        self.visa_backend = visa_backend
        self._manager = None
        self._instrument = None
        self._resource_lock = gpib_bus_lock(resource_name)

    def _require_instrument(self):
        if self._instrument is None:
            raise InstrumentError("Fluke 8508A 尚未连接")
        return self._instrument

    def _query(self, command: str) -> str:
        instrument = self._require_instrument()
        try:
            with self._resource_lock:
                instrument.write(command)
                return str(instrument.read()).strip()
        except Exception as exc:
            raise InstrumentError(f"执行 {command!r} 失败: {exc}") from exc

    def connect(self) -> InstrumentIdentity:
        if not is_gpib_instrument_resource(self.resource_name):
            raise InstrumentError("Fluke 8508A 只支持 IEEE-488/GPIB VISA 仪表资源")
        if pyvisa is None:
            raise InstrumentError("缺少 PyVISA，无法连接 Fluke 8508A")
        try:
            with self._resource_lock:
                self._manager = pyvisa.ResourceManager(self.visa_backend or "")
                self._instrument = self._manager.open_resource(self.resource_name)
                self._instrument.timeout = 30_000
                self._instrument.write_termination = "\n"
                self._instrument.read_termination = "\n"
                idn = self._query("*IDN?")
            normalized = idn.upper()
            if "8508A" not in normalized or "FLUKE" not in normalized:
                raise InstrumentError(
                    f"{self.resource_name} 返回 {idn!r}；当前通道选择的是 Fluke 8508A"
                )
            fields = [field.strip() for field in idn.split(",")]
            firmware = fields[3] if len(fields) > 3 else ""
            self.identity = InstrumentIdentity(
                model=idn,
                resource=self.resource_name,
                firmware=firmware,
                line_frequency_hz=50.0,
            )
            self.connected = True
            self.started_at = time.monotonic()
            logger.info(
                "Instrument connected | profile=fluke_8508a | resource=%s | idn=%s",
                self.resource_name,
                idn,
            )
            return self.identity
        except InstrumentError:
            self.disconnect()
            raise
        except Exception as exc:
            self.disconnect()
            raise InstrumentError(
                f"无法通过 GPIB 连接 {self.resource_name}: {exc}"
            ) from exc

    @classmethod
    def _fast_mode(cls, digits: int, requested_nplc: float) -> str:
        fast_plc, normal_plc = cls._DC_INTEGRATION_PLC[digits]
        return (
            "FAST_ON"
            if abs(requested_nplc - fast_plc) <= abs(requested_nplc - normal_plc)
            else "FAST_OFF"
        )

    @staticmethod
    def _range_token(config: AcquisitionConfig) -> str:
        return (
            "AUTO"
            if config.measurement_range.upper() == "AUTO"
            else config.measurement_range
        )

    def _function_command(self, config: AcquisitionConfig) -> str:
        function = config.function
        range_token = self._range_token(config)
        requested_digits = max(5, min(int(config.digits), 8))
        if function in {
            MeasurementFunction.AC_VOLTAGE,
            MeasurementFunction.AC_CURRENT,
        }:
            digits = min(requested_digits, 6)
        elif function is MeasurementFunction.DC_CURRENT:
            digits = min(requested_digits, 7)
        else:
            digits = requested_digits
        resolution = f"RESL{digits}"

        if function is MeasurementFunction.DC_VOLTAGE:
            fast = self._fast_mode(digits, config.nplc)
            return f"DCV {range_token},FILT_OFF,{resolution},{fast},TWO_WR"
        if function is MeasurementFunction.AC_VOLTAGE:
            return (
                f"ACV {range_token},FILT40HZ,ACCP,TFER_ON,{resolution},SPOT_OFF,TWO_WR"
            )
        if function in {
            MeasurementFunction.RESISTANCE_2W,
            MeasurementFunction.RESISTANCE_4W,
        }:
            fast = self._fast_mode(digits, config.nplc)
            wiring = (
                "FOUR_WR" if function is MeasurementFunction.RESISTANCE_4W else "TWO_WR"
            )
            return f"OHMS {range_token},FILT_OFF,{resolution},{fast},{wiring},LOI_OFF"
        if function is MeasurementFunction.DC_CURRENT:
            fast = self._fast_mode(digits, config.nplc)
            return f"DCI {range_token},FILT_OFF,{resolution},{fast}"
        if function is MeasurementFunction.AC_CURRENT:
            return f"ACI {range_token},FILT40HZ,ACCP,{resolution}"
        raise InstrumentError(f"Fluke 8508A 不支持 {config.function.value}")

    def configure(self, config: AcquisitionConfig) -> None:
        if config.function not in self.instrument_model.supported_functions:
            raise InstrumentError(f"Fluke 8508A 不支持 {config.function.value}")
        instrument = self._require_instrument()
        command = self._function_command(config)
        try:
            with self._resource_lock:
                instrument.timeout = max(
                    30_000,
                    int(
                        (config.nplc / max(self.identity.line_frequency_hz, 1.0) + 8)
                        * 1000
                    ),
                )
                for item in ("*CLS", command, "TRG_SRCE EXT"):
                    instrument.write(item)
            status_values = parse_ascii_values(self._query("*ESR?"))
            status = int(status_values[0]) if status_values.size else 0
            error_bits = status & 0x3C
            if error_bits:
                detail = ""
                if error_bits & 0x10:
                    values = parse_ascii_values(self._query("EXQ?"))
                    if values.size:
                        detail = f"；执行错误 {int(values[0])}"
                elif error_bits & 0x08:
                    values = parse_ascii_values(self._query("DDQ?"))
                    if values.size:
                        detail = f"；设备错误 {int(values[0])}"
                raise InstrumentError(f"Fluke 8508A 配置错误，ESR={status}{detail}")
            self.config = config
            logger.info(
                "Instrument configured | profile=fluke_8508a | "
                "resource=%s | function=%s | range=%s | "
                "requested_nplc=%s | command=%s",
                self.resource_name,
                config.function.command,
                config.measurement_range,
                config.nplc,
                command,
            )
        except InstrumentError:
            raise
        except Exception as exc:
            raise InstrumentError(f"配置 Fluke 8508A 失败: {exc}") from exc

    def read_single(self, include_temperature: bool = False) -> Measurement:
        del include_temperature
        values = parse_ascii_values(self._query("X?"))
        if not values.size:
            raise InstrumentError("Fluke 8508A 未返回有效读数")
        return Measurement(
            elapsed_s=time.monotonic() - self.started_at,
            value=float(values[0]),
            unit=self.config.function.unit,
            timestamp=datetime.now(timezone.utc),
        )

    def disconnect(self) -> None:
        instrument = self._instrument
        self._instrument = None
        try:
            if instrument is not None:
                try:
                    instrument.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "8508A instrument close failed | resource=%s | error=%s",
                        self.resource_name,
                        exc,
                    )
        finally:
            if self._manager is not None:
                try:
                    self._manager.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "8508A VISA manager close failed | resource=%s | error=%s",
                        self.resource_name,
                        exc,
                    )
            self._manager = None
            super().disconnect()

    def cancel_pending_io(self) -> None:
        instrument = self._instrument
        self._instrument = None
        if instrument is None:
            return
        try:
            instrument.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "8508A pending I/O cancellation failed | resource=%s | error=%s",
                self.resource_name,
                exc,
            )


class Keysight34470ADriver(ScpiDmmDriver):
    """Backward-compatible name for the Keysight 34470A profile."""

    def __init__(
        self,
        resource_name: str,
        config: AcquisitionConfig | None = None,
        visa_backend: str = "",
    ):
        super().__init__(
            resource_name,
            InstrumentModel.KEYSIGHT_34470A,
            config,
            visa_backend,
        )
