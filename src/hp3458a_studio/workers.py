from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from PySide6 import QtCore

from .connection_diagnostics import (
    ConnectionPreflightError,
    classify_connection_error,
    inspect_visa_environment,
)
from .drivers import (
    AcquisitionConfig,
    InstrumentDriver,
    MeasurementFunction,
    discover_visa_resources,
)
from .models import InstrumentModel

logger = logging.getLogger(__name__)


class PrecisionAcquisitionWorker(QtCore.QThread):
    identity_ready = QtCore.Signal(object)
    armed = QtCore.Signal()
    measurement_ready = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    connection_issue = QtCore.Signal(object)
    stopped = QtCore.Signal()

    def __init__(
        self,
        driver: InstrumentDriver,
        config: AcquisitionConfig,
        temperature_interval_s: float = 15.0,
        start_gate: threading.Event | None = None,
        preflight: bool = False,
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

    def request_stop(self) -> None:
        self._stop_event.set()
        self.driver.cancel_pending_io()

    def run(self) -> None:
        connection_complete = False
        try:
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
            identity = self.driver.connect()
            connection_complete = True
            self.identity_ready.emit(identity)
            self.driver.configure(self.config)
            if self.start_gate is not None:
                self.armed.emit()
                while not self.start_gate.wait(0.05):
                    if self._stop_event.is_set():
                        return
            # Elapsed time begins at the acquisition release point, not while
            # VISA connection/configuration is still in progress.
            self.driver.started_at = time.monotonic()
            next_sample = time.monotonic()
            next_temperature = 0.0
            while not self._stop_event.is_set():
                now = time.monotonic()
                include_temperature = now >= next_temperature
                reading = self.driver.read_single(
                    include_temperature=include_temperature
                )
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
            elif not connection_complete:
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
        self.driver.cancel_pending_io()

    def run(self) -> None:
        connection_complete = False
        try:
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
            identity = self.driver.connect()
            connection_complete = True
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
            self.result_ready.emit(x, y)
        except ConnectionPreflightError as exc:
            logger.error(
                "Connection preflight blocked burst | code=%s | resource=%s",
                exc.diagnostic.code.value,
                exc.diagnostic.resource,
            )
            self.connection_issue.emit(exc.diagnostic)
        except TypeError:
            if not self._stop_event.is_set():
                try:
                    x, y = self.driver.acquire_burst(
                        self.count,
                        self.interval_s,
                        self.aperture_s,
                    )
                    self.result_ready.emit(x, y)
                except Exception as exc:
                    if self._stop_event.is_set():
                        logger.info(
                            "Burst acquisition fallback stopped during pending I/O"
                        )
                    else:
                        logger.exception("Burst acquisition fallback failed")
                        self.failed.emit(str(exc))
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
