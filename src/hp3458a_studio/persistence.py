from __future__ import annotations

import csv
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np

from .models import Measurement

logger = logging.getLogger(__name__)


def default_autosave_root() -> Path:
    """Return a user-visible, stable folder for crash-resilient captures."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "Precision Multi-Instrument Lab Studio" / "autosave"


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-")[:64] or "instrument"


def new_run_id() -> str:
    return (
        datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        + "_"
        + uuid.uuid4().hex[:8]
    )


@dataclass(frozen=True)
class RecoveryFile:
    path: Path
    size_bytes: int
    modified_at: datetime


class DurableSessionWriter:
    """Append-only measurement journal that survives abrupt process loss.

    Every row is flushed through Python and synchronized to the filesystem
    before ``append`` returns. This intentionally favors data integrity over
    maximum throughput. 3458A high-speed bursts are committed as one durable
    batch once the instrument transfers them to the computer.
    """

    HEADER = (
        "timestamp_iso",
        "elapsed_s",
        "reading",
        "unit",
        "internal_temperature_c",
        "channel",
        "instrument_model",
        "resource",
    )

    def __init__(
        self,
        *,
        channel: str,
        instrument_model: str,
        resource: str,
        run_id: str | None = None,
        root: str | Path | None = None,
    ):
        self.channel = channel
        self.instrument_model = instrument_model
        self.resource = resource
        self.run_id = run_id or new_run_id()
        self.root = Path(root) if root is not None else default_autosave_root()
        day_folder = self.root / datetime.now().astimezone().strftime("%Y-%m-%d")
        day_folder.mkdir(parents=True, exist_ok=True)
        stem = "_".join(
            (
                self.run_id,
                _safe_component(channel),
                _safe_component(instrument_model),
            )
        )
        self.partial_path = day_folder / f"{stem}.partial.csv"
        self.final_path = day_folder / f"{stem}.csv"
        self.metadata_path = day_folder / f"{stem}.json"
        self._lock = threading.RLock()
        self._closed = False
        self._data_finalized = False
        self._finalized = False
        self._count = 0
        self.durability = "flush+fsync per received sample/batch"
        self._handle = self.partial_path.open(
            "x",
            newline="",
            encoding="utf-8",
        )
        self._writer = csv.writer(self._handle)
        try:
            self._writer.writerow(self.HEADER)
            self._sync()
        except Exception:
            self._handle.close()
            raise

    @property
    def count(self) -> int:
        return self._count

    @property
    def path(self) -> Path:
        return self.final_path if self._data_finalized else self.partial_path

    def _sync(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def append(self, measurement: Measurement) -> None:
        self.append_many((measurement,))

    def append_many(self, measurements: Iterable[Measurement]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("The durable capture is already closed")
            for measurement in measurements:
                _validate_measurement(measurement)
                self._writer.writerow(
                    (
                        measurement.timestamp.isoformat(),
                        f"{measurement.elapsed_s:.12g}",
                        f"{measurement.value:.17g}",
                        measurement.unit,
                        (
                            ""
                            if measurement.internal_temperature_c is None
                            or not np.isfinite(measurement.internal_temperature_c)
                            else f"{measurement.internal_temperature_c:.12g}"
                        ),
                        self.channel,
                        self.instrument_model,
                        self.resource,
                    )
                )
                self._count += 1
            self._sync()

    def finalize(self, status: str, error: str = "") -> Path:
        with self._lock:
            if self._finalized:
                return self.final_path
            if not self._closed:
                self._sync()
                self._handle.close()
                self._closed = True
            if not self._data_finalized:
                self.partial_path.replace(self.final_path)
                self._data_finalized = True
            metadata = {
                "run_id": self.run_id,
                "channel": self.channel,
                "instrument_model": self.instrument_model,
                "resource": self.resource,
                "status": status,
                "samples": self._count,
                "completed_at": datetime.now().astimezone().isoformat(),
                "data_file": self.final_path.name,
                "error": error,
                "durability": self.durability,
            }
            temporary = self.metadata_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with temporary.open("r+", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.metadata_path)
            self._finalized = True
            return self.final_path

    def close_unfinalized(self) -> None:
        """Release a failed journal while retaining its recovery file."""
        with self._lock:
            try:
                self._handle.close()
            finally:
                self._closed = True


def _validate_measurement(measurement: Measurement) -> None:
    if not math.isfinite(measurement.value) or abs(measurement.value) >= 9e36:
        raise ValueError("Non-finite or overloaded instrument reading cannot be saved")
    if not math.isfinite(measurement.elapsed_s):
        raise ValueError("Non-finite acquisition time cannot be saved")
    if not math.isfinite(measurement.timestamp.timestamp()):
        raise ValueError("Non-finite measurement timestamp cannot be saved")


class PersistenceBackpressureError(RuntimeError):
    """The bounded journal cannot accept more samples without losing data."""


class BackgroundSessionWriter:
    """Bounded, non-blocking submission with filesystem work on one thread.

    ``append`` acknowledges queue acceptance, not a completed fsync. Normally
    batches are synchronized within ``flush_interval_s``; slow or unavailable
    storage can extend that window. Finalization drains every accepted row.
    A full queue or background failure is explicit and never discards a row
    silently. The failed journal remains a .partial.csv recovery file.
    """

    def __init__(
        self,
        writer: DurableSessionWriter,
        *,
        queue_capacity: int = 200_000,
        batch_size: int = 256,
        flush_interval_s: float = 0.2,
    ):
        if queue_capacity < 1 or batch_size < 1:
            raise ValueError("Queue capacity and batch size must be positive")
        if not math.isfinite(flush_interval_s) or flush_interval_s <= 0:
            raise ValueError("Flush interval must be finite and positive")
        self.writer = writer
        self.queue_capacity = queue_capacity
        self.batch_size = min(batch_size, queue_capacity)
        self.flush_interval_s = flush_interval_s
        self.writer.durability = (
            f"background batch flush+fsync; max_batch_rows={self.batch_size}; "
            f"normal_flush_interval_s={flush_interval_s:g}; "
            f"max_pending_rows={queue_capacity}"
        )
        self._condition = threading.Condition()
        self._queue: deque[Measurement] = deque()
        self._accepted = 0
        self._committed = 0
        self._accepting = True
        self._finished = False
        self._error: Exception | None = None
        self._write_failed = False
        self._result: Path | None = None
        self._status = "stopped"
        self._status_error = ""
        self._thread = self._new_thread()
        self._thread.start()

    def _new_thread(self) -> threading.Thread:
        return threading.Thread(
            target=self._run,
            name=f"Journal-{self.writer.channel}-{self.writer.run_id}",
            daemon=True,
        )

    @property
    def partial_path(self) -> Path:
        return self.writer.partial_path

    @property
    def path(self) -> Path:
        return self.writer.path

    @property
    def final_path(self) -> Path:
        return self.writer.final_path

    @property
    def metadata_path(self) -> Path:
        return self.writer.metadata_path

    @property
    def count(self) -> int:
        with self._condition:
            return self._accepted

    @property
    def committed_count(self) -> int:
        with self._condition:
            return self._committed

    @property
    def pending_count(self) -> int:
        with self._condition:
            return self._accepted - self._committed

    @property
    def error(self) -> Exception | None:
        with self._condition:
            return self._error

    @property
    def finished(self) -> bool:
        with self._condition:
            return self._finished

    @property
    def write_failed(self) -> bool:
        with self._condition:
            return self._write_failed

    @property
    def result(self) -> Path | None:
        with self._condition:
            return self._result

    def append(self, measurement: Measurement) -> None:
        self.append_many((measurement,))

    def append_many(self, measurements: Iterable[Measurement]) -> None:
        snapshots = []
        for measurement in measurements:
            _validate_measurement(measurement)
            snapshots.append(replace(measurement))
            if len(snapshots) > self.queue_capacity:
                raise PersistenceBackpressureError(
                    f"Capture batch exceeds bounded journal capacity ({self.queue_capacity})"
                )
        with self._condition:
            if self._error is not None:
                raise RuntimeError(f"Background durable capture failed: {self._error}")
            if not self._accepting:
                raise RuntimeError("The durable capture is already closed")
            pending = self._accepted - self._committed
            if pending + len(snapshots) > self.queue_capacity:
                raise PersistenceBackpressureError(
                    f"Durable capture queue full ({pending}/{self.queue_capacity}); "
                    "acquisition must stop until storage catches up"
                )
            self._queue.extend(snapshots)
            self._accepted += len(snapshots)
            self._condition.notify_all()

    def request_finalize(self, status: str, error: str = "") -> None:
        with self._condition:
            if self._finished:
                if self._result is not None or self._write_failed:
                    return
                # A temporary rename/metadata failure can be retried without
                # replaying samples or recreating an already renamed CSV.
                self._finished = False
                self._error = None
                self._status = status
                self._status_error = error
                self._thread = self._new_thread()
                self._thread.start()
                return
            if self._accepting:
                self._status = status
                self._status_error = error
                self._accepting = False
                self._condition.notify_all()

    def finalize(self, status: str, error: str = "") -> Path:
        """Blocking drain for non-GUI callers; GUI uses request_finalize."""
        self.request_finalize(status, error)
        with self._condition:
            self._condition.wait_for(lambda: self._finished)
            if self._error is not None:
                raise self._error
            assert self._result is not None
            return self._result

    def _run(self) -> None:
        writing_batch = False
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: bool(self._queue) or not self._accepting
                    )
                    if not self._queue:
                        break
                    deadline = time.monotonic() + self.flush_interval_s
                    while self._accepting and len(self._queue) < self.batch_size:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(remaining)
                    batch = [
                        self._queue.popleft()
                        for _ in range(min(self.batch_size, len(self._queue)))
                    ]
                writing_batch = True
                self.writer.append_many(batch)
                writing_batch = False
                with self._condition:
                    self._committed += len(batch)
                    self._condition.notify_all()
            result = self.writer.finalize(self._status, self._status_error)
            with self._condition:
                self._result = result
        except Exception as exc:
            logger.exception(
                "Background journal failed | channel=%s", self.writer.channel
            )
            if writing_batch:
                try:
                    self.writer.close_unfinalized()
                except Exception:
                    logger.exception(
                        "Failed journal handle could not close | channel=%s",
                        self.writer.channel,
                    )
            with self._condition:
                self._write_failed = writing_batch
                self._error = exc
                self._accepting = False
        finally:
            with self._condition:
                self._finished = True
                self._condition.notify_all()


def list_recovery_files(
    root: str | Path | None = None,
) -> list[RecoveryFile]:
    autosave_root = Path(root) if root is not None else default_autosave_root()
    if not autosave_root.exists():
        return []
    output: list[RecoveryFile] = []
    for path in autosave_root.rglob("*.partial.csv"):
        try:
            stat = path.stat()
        except OSError:
            continue
        output.append(
            RecoveryFile(
                path=path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
            )
        )
    return sorted(output, key=lambda item: item.modified_at, reverse=True)
