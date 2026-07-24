from __future__ import annotations

import csv
import json
import os
import re
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .models import Measurement


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
        self._count = 0
        self._handle = self.partial_path.open(
            "x",
            newline="",
            encoding="utf-8",
        )
        self._writer = csv.writer(self._handle)
        self._writer.writerow(self.HEADER)
        self._sync()

    @property
    def count(self) -> int:
        return self._count

    @property
    def path(self) -> Path:
        return self.final_path if self._closed else self.partial_path

    def _sync(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def append(self, measurement: Measurement) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("The durable capture is already closed")
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

    def append_many(self, measurements: Iterable[Measurement]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("The durable capture is already closed")
            for measurement in measurements:
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
            if self._closed:
                return self.final_path
            self._sync()
            self._handle.close()
            self._closed = True
            self.partial_path.replace(self.final_path)
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
                "durability": "flush+fsync per received sample/batch",
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
            return self.final_path


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
