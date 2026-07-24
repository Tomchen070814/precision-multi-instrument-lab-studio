import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from hp3458a_studio.diagnostics import (
    configure_logging,
    create_diagnostic_report,
)


def test_diagnostic_report_contains_state_events_and_persistent_log(
    tmp_path: Path,
):
    log_directory = tmp_path / "state"
    configure_logging(log_directory)
    logging.getLogger("hp3458a_studio.test").error("simulated VISA timeout")
    for handler in logging.getLogger().handlers:
        handler.flush()

    output = create_diagnostic_report(
        tmp_path / "report.zip",
        app_version="0.test",
        language="zh",
        event_log="12:00:00  A 错误：timeout",
        channels={
            "A": {
                "enabled": True,
                "resource": "GPIB0::21::INSTR",
                "samples_acquired": 12,
                "last_error": "timeout",
            }
        },
        application={"active_sync_selection": ["A", "C"]},
        generated_at=datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc),
    )

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {
            "README.txt",
            "diagnostic.html",
            "diagnostic.json",
            "events.txt",
            "logs/application.log",
        }.issubset(names)
        payload = json.loads(archive.read("diagnostic.json"))
        assert payload["system"]["app_version"] == "0.test"
        assert payload["application"]["active_sync_selection"] == ["A", "C"]
        assert payload["channels"]["A"]["resource"] == "GPIB0::21::INSTR"
        assert "A 错误" in archive.read("events.txt").decode("utf-8")
        assert "simulated VISA timeout" in archive.read("logs/application.log").decode(
            "utf-8"
        )
        assert "simulated VISA timeout" in archive.read("diagnostic.html").decode(
            "utf-8"
        )


def test_diagnostic_report_never_includes_measurement_samples(tmp_path: Path):
    configure_logging(tmp_path / "state")
    output = create_diagnostic_report(
        tmp_path / "report",
        app_version="0.test",
        language="en",
        event_log="",
        channels={"A": {"samples_acquired": 20000}},
    )

    with zipfile.ZipFile(output) as archive:
        assert output.suffix == ".zip"
        assert not any(
            name.endswith((".csv", ".xlsx", ".npy")) for name in archive.namelist()
        )
