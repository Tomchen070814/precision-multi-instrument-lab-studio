from __future__ import annotations

import csv
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


def read_measurement_csv(path: str | Path) -> ImportedData:
    csv_path = Path(path)
    sample = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not sample.strip():
        raise ValueError("CSV 文件为空")
    try:
        dialect = csv.Sniffer().sniff(sample[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(sample.splitlines(), dialect))
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
    time_index = max(
        numeric_indices,
        key=lambda i: (_score_header(header[i], TIME_HINTS), converted[i][1], -i),
    )
    value_candidates = [i for i in numeric_indices if i != time_index]
    if not value_candidates:
        value_candidates = numeric_indices
        time_index = -1
    value_index = max(
        value_candidates,
        key=lambda i: (_score_header(header[i], VALUE_HINTS), converted[i][1], i),
    )
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
    elapsed = elapsed - elapsed[0]
    unit_match = UNIT_PATTERN.search(header[value_index])
    unit = unit_match.group(1).strip() if unit_match else "V"
    return ImportedData(
        elapsed_s=elapsed,
        values=values,
        x_column=header[time_index] if time_index >= 0 else "样本序号",
        y_column=header[value_index],
        unit=unit,
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
                    f"{elapsed:.9f}",
                    f"{value:.12g}",
                    "" if not np.isfinite(temperature) else f"{temperature:.6f}",
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
                        f"{session.elapsed_s[index]:.9f}",
                        f"{session.values[index]:.12g}",
                        "" if not np.isfinite(temperature) else f"{temperature:.6f}",
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
                        f"{session.elapsed_s[index]:.9f}",
                        f"{session.values[index]:.12g}",
                        "" if not np.isfinite(temperature) else f"{temperature:.6f}",
                    ]
                )
            writer.writerow(row)
