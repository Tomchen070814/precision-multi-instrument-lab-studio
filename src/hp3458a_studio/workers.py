from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable

import numpy as np
from PySide6 import QtCore

try:
    import pyvisa
except ImportError:  # pragma: no cover - connection diagnostics explain this
    pyvisa = None

from .connection_diagnostics import (
    ConnectionPreflightError,
    classify_connection_error,
    inspect_visa_environment,
)
from .drivers import (
    AcquisitionConfig,
    InstrumentDriver,
    InstrumentError,
    MeasurementFunction,
    discover_visa_resources,
)
from .models import InstrumentModel

logger = logging.getLogger(__name__)


def _retryable_transport_error(error: Exception) -> bool:
    """Recognize transport failures even after a driver adds its context."""
    retryable_codes = (
        {
            pyvisa.constants.StatusCode.error_timeout,
            pyvisa.constants.StatusCode.error_connection_lost,
            pyvisa.constants.StatusCode.error_io,
            pyvisa.constants.StatusCode.error_no_listeners,
            pyvisa.constants.StatusCode.error_resource_not_found,
            pyvisa.constants.StatusCode.error_invalid_object,
        }
        if pyvisa is not None
        else set()
    )
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        if (
            pyvisa is not None
            and isinstance(current, pyvisa.errors.VisaIOError)
            and current.error_code in retryable_codes
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _validate_reading(reading) -> None:
    if (
        not math.isfinite(float(reading.value))
        or abs(float(reading.value)) >= 9e36
        or not math.isfinite(float(reading.elapsed_s))
        or float(reading.elapsed_s) < 0
        or not math.isfinite(reading.timestamp.timestamp())
    ):
        raise InstrumentError("Invalid/overflow measurement; sample was not saved")


class PrecisionAcquisitionWorker(QtCore.QThread):
    identity_ready = QtCore.Signal(object)
    armed = QtCore.Signal()
    measurement_ready = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    connection_issue = QtCore.Signal(object)
    stopped = QtCore.Signal()
    recovering = QtCore.Signal(int, float, str)
    recovered = QtCore.Signal()

    def __init__(
        self,
        driver: InstrumentDriver,
        config: AcquisitionConfig,
        temperature_interval_s: float = 15.0,
        start_gate: threading.Event | None = None,
        preflight: bool = False,
        reconnect_delays_s: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0),
    ):
        super().__init__()
        self.driver = driver
        self.config = config
        self.temperature_interval_s = temperature_interval_s
        self.start_gate = start_gate
        self.preflight = preflight
        self._stop_event = threading.Event()
        self.completed_target = False
        self.samples_acquired = 0
        if any(not math.isfinite(delay) or delay < 0 for delay in reconnect_delays_s):
            raise ValueError("Reconnect delays must be finite and nonnegative")
        self.reconnect_delays_s = tuple(reconnect_delays_s)
        self.reconnect_attempts = 0
        self._consecutive_reconnects = 0
        self._ever_connected = False
        self._capture_started_at: float | None = None
        self._recovery_pending = False

    def request_stop(self) -> None:
        self._stop_event.set()
        try:
            self.driver.cancel_pending_io()
        except Exception:
            logger.exception("Precision acquisition I/O cancellation failed")

    def _connect_and_configure(self) -> None:
        if self._stop_event.is_set():
            return
        identity = self.driver.connect()
        self._ever_connected = True
        if self._stop_event.is_set():
            return
        self.identity_ready.emit(identity)
        self.driver.configure(self.config)
        if self._capture_started_at is not None:
            # Driver.connect() resets its clock. Reconnection belongs to the
            # same capture, including the elapsed time spent disconnected.
            self.driver.started_at = self._capture_started_at

    def _recover(self, error: Exception) -> bool:
        while not self._stop_event.is_set():
            if not _retryable_transport_error(error):
                raise error
            if self._consecutive_reconnects >= len(self.reconnect_delays_s):
                raise InstrumentError(
                    "Automatic reconnect exhausted after "
                    f"{self._consecutive_reconnects} attempts: {error}"
                ) from error
            # Close only this instrument's session. Closing before disconnect
            # also avoids reset commands on a broken 3458A holding the bus.
            try:
                self.driver.cancel_pending_io()
            except Exception:
                logger.exception("Failed to close disconnected instrument session")
            try:
                self.driver.disconnect()
            except Exception:
                logger.exception("Failed to release disconnected instrument session")
            delay = self.reconnect_delays_s[self._consecutive_reconnects]
            self._consecutive_reconnects += 1
            self.reconnect_attempts += 1
            self._recovery_pending = True
            self.recovering.emit(self._consecutive_reconnects, delay, str(error))
            logger.warning(
                "Instrument reconnect pending | attempt=%s | delay=%s | error=%s",
                self._consecutive_reconnects,
                delay,
                error,
            )
            if self._stop_event.wait(delay):
                return False
            try:
                self._connect_and_configure()
            except Exception as next_error:  # noqa: BLE001 - classified below
                error = next_error
            else:
                return not self._stop_event.is_set()
        return False

    def run(self) -> None:
        try:
            if self._stop_event.is_set():
                return
            if self.preflight:
                model = getattr(
                    self.driver,
                    "instrument_model",
                    InstrumentModel.KEYSIGHT_3458A,
                )
                resource = str(getattr(self.driver, "resource_name", ""))
                if resource and not resource.upper().startswith("SIM::"):
                    diagnostic = inspect_visa_environment(
                        resource,
                        model,
                    )
                    if diagnostic.blocking:
                        raise ConnectionPreflightError(diagnostic)
            if self._stop_event.is_set():
                return
            try:
                self._connect_and_configure()
            except Exception as exc:  # noqa: BLE001 - only transport errors retry
                if not self._recover(exc):
                    return
            if self._stop_event.is_set():
                return
            if self.start_gate is not None:
                self.armed.emit()
                while not self.start_gate.wait(0.05):
                    if self._stop_event.is_set():
                        return
            # Elapsed time begins at the acquisition release point, not while
            # VISA connection/configuration is still in progress.
            self._capture_started_at = time.monotonic()
            self.driver.started_at = self._capture_started_at
            next_sample = time.monotonic()
            next_temperature = 0.0
            while not self._stop_event.is_set():
                now = time.monotonic()
                include_temperature = now >= next_temperature
                try:
                    reading = self.driver.read_single(
                        include_temperature=include_temperature
                    )
                except Exception as exc:  # noqa: BLE001 - only transport errors retry
                    if not self._recover(exc):
                        return
                    next_sample = time.monotonic()
                    next_temperature = 0.0
                    continue
                if self._stop_event.is_set():
                    return
                _validate_reading(reading)
                reading.elapsed_s = time.monotonic() - self._capture_started_at
                self._consecutive_reconnects = 0
                if self._recovery_pending:
                    self._recovery_pending = False
                    self.recovered.emit()
                if include_temperature:
                    next_temperature = time.monotonic() + self.temperature_interval_s
                self.measurement_ready.emit(reading)
                self.samples_acquired += 1
                if (
                    self.config.max_samples is not None
                    and self.samples_acquired >= self.config.max_samples
                ):
                    self.completed_target = True
                    break
                next_sample += self.config.sample_interval_s
                remaining = next_sample - time.monotonic()
                if remaining > 0:
                    self._stop_event.wait(remaining)
                else:
                    next_sample = time.monotonic()
        except ConnectionPreflightError as exc:
            logger.error(
                "Connection preflight blocked acquisition | code=%s | resource=%s",
                exc.diagnostic.code.value,
                exc.diagnostic.resource,
            )
            self.connection_issue.emit(exc.diagnostic)
        except Exception as exc:
            if self._stop_event.is_set():
                logger.info("Precision acquisition worker stopped during pending I/O")
            elif not self._ever_connected:
                model = getattr(
                    self.driver,
                    "instrument_model",
                    InstrumentModel.KEYSIGHT_3458A,
                )
                resource = str(getattr(self.driver, "resource_name", ""))
                logger.exception("Instrument connection failed")
                self.connection_issue.emit(
                    classify_connection_error(exc, resource, model)
                )
            else:
                logger.exception("Precision acquisition worker failed")
                self.failed.emit(str(exc))
        finally:
            try:
                self.driver.disconnect()
            except Exception:
                logger.exception("Precision acquisition driver cleanup failed")
            finally:
                self.stopped.emit()


class BurstAcquisitionWorker(QtCore.QThread):
    identity_ready = QtCore.Signal(object)
    armed = QtCore.Signal()
    result_ready = QtCore.Signal(object, object)
    failed = QtCore.Signal(str)
    connection_issue = QtCore.Signal(object)
    stopped = QtCore.Signal()

    def __init__(
        self,
        driver: InstrumentDriver,
        count: int,
        interval_s: float,
        aperture_s: float,
        function: MeasurementFunction,
        measurement_range: str,
        start_gate: threading.Event | None = None,
        preflight: bool = False,
    ):
        super().__init__()
        self.driver = driver
        self.count = count
        self.interval_s = interval_s
        self.aperture_s = aperture_s
        self.function = function
        self.measurement_range = measurement_range
        self.start_gate = start_gate
        self.preflight = preflight
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()
        try:
            self.driver.cancel_pending_io()
        except Exception:
            logger.exception("Burst acquisition I/O cancellation failed")

    def run(self) -> None:
        connection_complete = False
        try:
            if self._stop_event.is_set():
                return
            if self.preflight:
                model = getattr(
                    self.driver,
                    "instrument_model",
                    InstrumentModel.KEYSIGHT_3458A,
                )
                resource = str(getattr(self.driver, "resource_name", ""))
                if resource and not resource.upper().startswith("SIM::"):
                    diagnostic = inspect_visa_environment(
                        resource,
                        model,
                    )
                    if diagnostic.blocking:
                        raise ConnectionPreflightError(diagnostic)
            if self._stop_event.is_set():
                return
            identity = self.driver.connect()
            connection_complete = True
            if self._stop_event.is_set():
                return
            self.identity_ready.emit(identity)
            if self.start_gate is not None:
                self.armed.emit()
                while not self.start_gate.wait(0.05):
                    if self._stop_event.is_set():
                        return
            if self._stop_event.is_set():
                return
            x, y = self.driver.acquire_burst(
                count=self.count,
                interval_s=self.interval_s,
                aperture_s=self.aperture_s,
                function=self.function,
                measurement_range=self.measurement_range,
            )
            if self._stop_event.is_set():
                return
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            if (
                x.ndim != 1
                or y.ndim != 1
                or x.size != self.count
                or y.size != self.count
                or not np.all(np.isfinite(x))
                or not np.all(np.isfinite(y))
                or np.any(x < 0)
                or np.any(np.abs(y) >= 9e36)
            ):
                raise InstrumentError(
                    "Invalid/overflow burst measurements; batch was not saved"
                )
            self.result_ready.emit(x, y)
        except ConnectionPreflightError as exc:
            logger.error(
                "Connection preflight blocked burst | code=%s | resource=%s",
                exc.diagnostic.code.value,
                exc.diagnostic.resource,
            )
            self.connection_issue.emit(exc.diagnostic)
        except Exception as exc:
            if self._stop_event.is_set():
                logger.info("Burst acquisition worker stopped during pending I/O")
            elif not connection_complete:
                model = getattr(
                    self.driver,
                    "instrument_model",
                    InstrumentModel.KEYSIGHT_3458A,
                )
                resource = str(getattr(self.driver, "resource_name", ""))
                logger.exception("Burst instrument connection failed")
                self.connection_issue.emit(
                    classify_connection_error(exc, resource, model)
                )
            else:
                logger.exception("Burst acquisition worker failed")
                self.failed.emit(str(exc))
        finally:
            try:
                self.driver.disconnect()
            except Exception:
                logger.exception("Burst acquisition driver cleanup failed")
            finally:
                self.stopped.emit()


class ConnectionCheckWorker(QtCore.QThread):
    """Run VISA/GPIB enumeration away from the Qt event loop."""

    result_ready = QtCore.Signal(object)

    def __init__(
        self,
        resource: str,
        model: InstrumentModel,
        parent=None,
    ):
        super().__init__(parent)
        self.resource = resource
        self.model = model

    def run(self) -> None:
        try:
            result = inspect_visa_environment(self.resource, self.model)
        except Exception as exc:  # pragma: no cover - final containment
            logger.exception("Connection self-check worker failed")
            result = classify_connection_error(
                exc,
                self.resource,
                self.model,
            )
        self.result_ready.emit(result)


class VisaDiscoveryWorker(QtCore.QThread):
    """Enumerate VISA resources without blocking painting or input."""

    result_ready = QtCore.Signal(object)

    def __init__(
        self,
        discovery: Callable[[], list[str]] = discover_visa_resources,
        parent=None,
    ):
        super().__init__(parent)
        self.discovery = discovery

    def run(self) -> None:
        self.result_ready.emit(self.discovery())
