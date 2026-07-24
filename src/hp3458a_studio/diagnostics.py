from __future__ import annotations

import html
import json
import logging
import logging.handlers
import os
import platform
import sys
import tempfile
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

LOGGER_NAME = "hp3458a_studio"
LOG_FILE_NAME = "application.log"
REPORT_SCHEMA_VERSION = 1
_log_directory: Path | None = None


def configure_logging(data_directory: str | Path) -> Path:
    """Configure one persistent, rotating UTF-8 log for the whole application."""
    global _log_directory

    requested = Path(data_directory)
    try:
        requested.mkdir(parents=True, exist_ok=True)
        target_directory = requested
    except OSError:
        target_directory = (
            Path(tempfile.gettempdir()) / "Precision-Multi-Instrument-Lab-Studio"
        )
        target_directory.mkdir(parents=True, exist_ok=True)
    _log_directory = target_directory
    log_path = target_directory / LOG_FILE_NAME

    root_logger = logging.getLogger()
    for handler in tuple(root_logger.handlers):
        if getattr(handler, "_hp3458a_persistent", False):
            existing_path = Path(getattr(handler, "baseFilename", ""))
            if existing_path == log_path:
                return log_path
            root_logger.removeHandler(handler)
            handler.close()

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler._hp3458a_persistent = True  # type: ignore[attr-defined]
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
            "%(threadName)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(handler)
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    # VISA backends can emit every low-level transfer at DEBUG. Keep persistent
    # logs diagnostic without letting long acquisitions consume the disk.
    logging.getLogger("pyvisa").setLevel(logging.WARNING)
    logging.captureWarnings(True)
    logging.getLogger(LOGGER_NAME).info(
        "Persistent logging initialized | file=%s",
        LOG_FILE_NAME,
    )
    return log_path


def log_directory() -> Path:
    """Return the configured state directory, with a safe temporary fallback."""
    if _log_directory is not None:
        return _log_directory
    fallback = Path(tempfile.gettempdir()) / "Precision-Multi-Instrument-Lab-Studio"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in (
        "hp3458a-studio",
        "PySide6",
        "pyqtgraph",
        "numpy",
        "scipy",
        "PyVISA",
    ):
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = "not installed"
    return versions


def system_snapshot(app_version: str) -> dict[str, Any]:
    """Collect useful environment facts without user names or home paths."""
    return {
        "app_version": app_version,
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_architecture": platform.architecture()[0],
        "packaged_executable": bool(getattr(sys, "frozen", False)),
        "package_versions": _package_versions(),
    }


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return str(value)


def _html_report(payload: Mapping[str, Any]) -> str:
    title = "Precision Multi-Instrument Lab Studio — Diagnostic Report"
    sections = [
        ("System", payload.get("system", {})),
        ("Application", payload.get("application", {})),
        ("Channels", payload.get("channels", {})),
        ("Current UI events", payload.get("current_events", "")),
        ("Recent persistent log", payload.get("recent_log_tail", "")),
    ]
    rendered_sections = []
    for name, content in sections:
        rendered = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False, indent=2)
        )
        rendered_sections.append(
            f"<section><h2>{html.escape(name)}</h2><pre>"
            f"{html.escape(rendered or '(none)')}"
            "</pre></section>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;margin:36px;"
        "color:#18212b;background:#f7f9fb}"
        "h1{font-size:24px;margin-bottom:4px}h2{font-size:15px;"
        "letter-spacing:.04em;text-transform:uppercase;color:#51606f}"
        "p{color:#667583}section{background:#fff;border:1px solid #dfe5eb;"
        "border-radius:10px;padding:18px 20px;margin:14px 0}"
        "pre{white-space:pre-wrap;word-break:break-word;font:12px/1.55 "
        "Consolas,monospace;margin:0;color:#24303c}"
        "</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>Generated {html.escape(str(payload.get('generated_at_utc', '')))}</p>"
        + "".join(rendered_sections)
        + "</body></html>"
    )


def _tail_text(path: Path, max_bytes: int = 96_000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        payload = handle.read()
    return payload.decode("utf-8", errors="replace")


def create_diagnostic_report(
    output_path: str | Path,
    *,
    app_version: str,
    language: str,
    event_log: str,
    channels: Mapping[str, Mapping[str, Any]],
    application: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> Path:
    """Create one portable ZIP with structured state, UI events and log history."""
    output = Path(output_path)
    if output.suffix.lower() != ".zip":
        output = output.with_suffix(".zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = generated_at or datetime.now(timezone.utc)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "system": system_snapshot(app_version),
        "application": {
            "language": language,
            **_json_ready(application or {}),
        },
        "channels": _json_ready(channels),
        "current_events": event_log or "",
        "recent_log_tail": _tail_text(log_directory() / LOG_FILE_NAME),
    }

    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                "diagnostic.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            archive.writestr("diagnostic.html", _html_report(payload))
            archive.writestr("events.txt", event_log or "(no UI events)\n")
            archive.writestr(
                "README.txt",
                "Open diagnostic.html for the summary. application.log contains "
                "persistent runtime events and errors. No measurement samples "
                "are included in this report.\n\n"
                "打开 diagnostic.html 查看摘要；application.log 包含跨重启"
                "保留的运行事件与错误。本报告不包含测量样本数据。\n",
            )
            state_directory = log_directory()
            for log_path in sorted(state_directory.glob(f"{LOG_FILE_NAME}*")):
                if log_path.is_file():
                    archive.write(log_path, f"logs/{log_path.name}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    logging.getLogger(LOGGER_NAME).info(
        "Diagnostic report exported | file=%s",
        output.name,
    )
    return output
