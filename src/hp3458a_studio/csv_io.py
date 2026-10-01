from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .models import SessionData

TIME_HINTS = ("time", "timestamp", "date", "elapsed", "second", "时间", "秒")
VALUE_HINTS = (
    "value",
    "reading",
    "measurement",
    "voltage",
    "current",
    "resistance",
    "dmm",
    "值",
    "读数",
    "电压",
    "电流",
    "电阻",
)
UNIT_PATTERN = re.compile(r"(?:\(|\[)\s*([^)\]]+)\s*(?:\)|\])")


def _timestamp_iso(session: SessionData, index: int) -> str:
    if index >= len(session.timestamps):
        return ""
    return datetime.fromtimestamp(
        float(session.timestamps[index]),
        tz=timezone.utc,
    ).isoformat()


@dataclass(frozen=True)
class ImportedData:
    elapsed_s: np.ndarray
    values: np.ndarray
    x_column: str
    y_column: str
    unit: str
    timestamps: np.ndarray | None = None
    temperatures_c: np.ndarray | None = None


def _numeric(values: list[str]) -> tuple[np.ndarray, float]:
    output = np.full(len(values), np.nan, dtype=float)
    valid = 0
    for index, value in enumerate(values):
        text = value.strip()
        if not text:
            continue
        try:
            output[index] = float(text)
            valid += 1
        except ValueError:
            try:
                output[index] = datetime.fromisoformat(
                    text.replace("Z", "+00:00")
                ).timestamp()
                valid += 1
            except ValueError:
                pass
    return output, valid / max(1, len(values))


def _score_header(name: str, hints: tuple[str, ...]) -> int:
    lowered = name.lower()
    return max(
        (4 if hint == lowered else 2 for hint in hints if hint in lowered), default=0
    )


def _measurement_channel(name: str) -> str | None:
    match = re.match(r"^reading_([A-Za-z0-9]+)(?:\s|$)", name, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _time_channel(name: str) -> str | None:
    if name.lower() == "timestamp_iso":
        return None
    match = re.fullmatch(
        r"(?:timestamp_([A-Za-z0-9]+)|elapsed_([A-Za-z0-9]+)_s)",
        name,
        re.IGNORECASE,
    )
    return (match.group(1) or match.group(2)).upper() if match else None


def _is_timestamp_column(name: str, column: list[str]) -> bool:
    lowered = name.lower()
    if "elapsed" in lowered:
        return False
    if "timestamp" in lowered or "date" in lowered or "时间戳" in name:
        return True
    # Generic "time" columns can contain ISO dates rather than elapsed seconds.
    return any(re.match(r"^\d{4}-\d{2}-\d{2}[T ]", value.strip()) for value in column)


def read_measurement_csv(
    path: str | Path, *, channel: str | None = None
) -> ImportedData:
    csv_path = Path(path)
    sample = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not sample.strip():
        raise ValueError("CSV 文件为空")
    try:
        dialect = csv.Sniffer().sniff(sample[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(sample), dialect))
    if len(rows) < 2:
        raise ValueError("CSV 至少需要标题行和一行数据")
    width = max(len(row) for row in rows)
    header = [
        (
            rows[0][i].strip()
            if i < len(rows[0]) and rows[0][i].strip()
            else f"Column {i + 1}"
        )
        for i in range(width)
    ]
    columns = [
        [row[i] if i < len(row) else "" for row in rows[1:]] for i in range(width)
    ]
    converted = [_numeric(column) for column in columns]
    numeric_indices = [i for i, (_, ratio) in enumerate(converted) if ratio >= 0.6]
    if not numeric_indices:
        raise ValueError("未找到可用的数值列")
    requested_channel = channel.upper() if channel else None
    matching_values = [
        i
        for i in range(width)
        if requested_channel is not None
        and _measurement_channel(header[i]) == requested_channel
        and np.any(np.isfinite(converted[i][0]))
    ]
    exported_values = [
        i
        for i in range(width)
        if _measurement_channel(header[i]) is not None
        and np.any(np.isfinite(converted[i][0]))
    ]
    value_candidates = (
        matching_values
        or exported_values
        or [i for i in numeric_indices if _score_header(header[i], VALUE_HINTS) > 0]
    )
    if value_candidates:
        value_index = (
            value_candidates[0]
            if matching_values or exported_values
            else max(
                value_candidates,
                key=lambda i: (
                    _score_header(header[i], VALUE_HINTS),
                    converted[i][1],
                    -i,
                ),
            )
        )
        value_channel = _measurement_channel(header[value_index])
        time_candidates = [
            i
            for i in range(width)
            if i != value_index
            and _score_header(header[i], TIME_HINTS) > 0
            and np.any(np.isfinite(converted[i][0]))
            and (
                _time_channel(header[i]) == value_channel
                if value_channel is not None
                else _time_channel(header[i]) is None
            )
        ]
        # Exported elapsed seconds retain burst timing below wall-clock precision.
        time_index = max(
            time_candidates,
            key=lambda i: (
                "elapsed" in header[i].lower(),
                _score_header(header[i], TIME_HINTS),
                converted[i][1],
                -i,
            ),
            default=-1,
        )
        if time_index < 0 and value_channel is None:
            time_index = next(
                (
                    i
                    for i in numeric_indices
                    if i != value_index
                    and _score_header(header[i], VALUE_HINTS) == 0
                    and "temperature" not in header[i].lower()
                    and "温度" not in header[i]
                ),
                -1,
            )
    else:
        # Retain the conventional first-X/last-Y fallback for unlabelled tables.
        time_index = numeric_indices[0] if len(numeric_indices) > 1 else -1
        value_index = numeric_indices[-1]
        value_channel = None
    values = converted[value_index][0]
    if time_index >= 0:
        elapsed = converted[time_index][0]
    else:
        elapsed = np.arange(values.size, dtype=float)
    mask = np.isfinite(elapsed) & np.isfinite(values)
    elapsed = elapsed[mask]
    values = values[mask]
    if values.size == 0:
        raise ValueError("所选数据列没有成对的有效数值")
    timestamp_candidates = [
        i
        for i in range(width)
        if _is_timestamp_column(header[i], columns[i])
        and (
            _time_channel(header[i]) == value_channel
            if value_channel is not None
            else _time_channel(header[i]) is None
        )
    ]
    timestamps = None
    for index in timestamp_candidates:
        candidate = converted[index][0][mask].copy()
        valid_timestamps = np.flatnonzero(np.isfinite(candidate))
        if valid_timestamps.size:
            anchor = int(valid_timestamps[0])
            missing = ~np.isfinite(candidate)
            candidate[missing] = candidate[anchor] + (
                elapsed[missing] - elapsed[anchor]
            )
            timestamps = candidate
            break
    temperature_name = (
        f"temperature_{value_channel}_c" if value_channel else "internal_temperature_c"
    )
    temperature_index = next(
        (
            i
            for i, name in enumerate(header)
            if name.lower() == temperature_name.lower()
        ),
        None,
    )
    temperatures = (
        converted[temperature_index][0][mask] if temperature_index is not None else None
    )
    elapsed = elapsed - elapsed[0]
    unit_match = UNIT_PATTERN.search(header[value_index])
    unit = unit_match.group(1).strip() if unit_match else "V"
    if unit_match is None:
        unit_index = next(
            (i for i, name in enumerate(header) if name.lower() == "unit"), None
        )
        if unit_index is not None:
            units = {
                columns[unit_index][i].strip()
                for i in np.flatnonzero(mask)
                if columns[unit_index][i].strip()
            }
            if len(units) > 1:
                raise ValueError("CSV 读数列包含多种单位，无法作为同一会话导入")
            if units:
                unit = units.pop()
    return ImportedData(
        elapsed_s=elapsed,
        values=values,
        x_column=header[time_index] if time_index >= 0 else "样本序号",
        y_column=header[value_index],
        unit=unit,
        timestamps=timestamps,
        temperatures_c=temperatures,
    )


def write_session_csv(path: str | Path, session: SessionData) -> None:
    output_path = Path(path)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp_iso",
                "elapsed_s",
                f"reading ({session.unit})",
                "internal_temperature_c",
            ]
        )
        for index, (elapsed, value) in enumerate(
            zip(session.elapsed_s, session.values)
        ):
            timestamp = _timestamp_iso(session, index)
            temperature = (
                session.temperatures_c[index]
                if index < len(session.temperatures_c)
                else np.nan
            )
            writer.writerow(
                [
                    timestamp,
                    f"{elapsed:.17g}",
                    f"{value:.17g}",
                    "" if not np.isfinite(temperature) else f"{temperature:.17g}",
                ]
            )


def write_dual_session_csv(
    path: str | Path,
    session_a: SessionData,
    session_b: SessionData,
) -> None:
    """Export two independently timed sessions without inventing alignment."""
    output_path = Path(path)
    row_count = max(len(session_a), len(session_b))
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp_A",
                "elapsed_A_s",
                f"reading_A ({session_a.unit})",
                "temperature_A_c",
                "timestamp_B",
                "elapsed_B_s",
                f"reading_B ({session_b.unit})",
                "temperature_B_c",
            ]
        )
        for index in range(row_count):
            row: list[str] = []
            for session in (session_a, session_b):
                if index >= len(session):
                    row.extend(["", "", "", ""])
                    continue
                timestamp = _timestamp_iso(session, index)
                temperature = (
                    session.temperatures_c[index]
                    if index < len(session.temperatures_c)
                    else np.nan
                )
                row.extend(
                    [
                        timestamp,
                        f"{session.elapsed_s[index]:.17g}",
                        f"{session.values[index]:.17g}",
                        "" if not np.isfinite(temperature) else f"{temperature:.17g}",
                    ]
                )
            writer.writerow(row)


def write_multi_session_csv(
    path: str | Path,
    sessions: dict[str, SessionData],
) -> None:
    """Export independently timed A/B/C sessions without inventing alignment."""
    ordered = [(key, sessions[key]) for key in sorted(sessions)]
    output_path = Path(path)
    row_count = max((len(session) for _key, session in ordered), default=0)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        header: list[str] = []
        for key, session in ordered:
            header.extend(
                [
                    f"timestamp_{key}",
                    f"elapsed_{key}_s",
                    f"reading_{key} ({session.unit})",
                    f"temperature_{key}_c",
                ]
            )
        writer.writerow(header)
        for index in range(row_count):
            row: list[str] = []
            for _key, session in ordered:
                if index >= len(session):
                    row.extend(["", "", "", ""])
                    continue
                timestamp = _timestamp_iso(session, index)
                temperature = (
                    session.temperatures_c[index]
                    if index < len(session.temperatures_c)
                    else np.nan
                )
                row.extend(
                    [
                        timestamp,
                        f"{session.elapsed_s[index]:.17g}",
                        f"{session.values[index]:.17g}",
                        "" if not np.isfinite(temperature) else f"{temperature:.17g}",
                    ]
                )
            writer.writerow(row)
