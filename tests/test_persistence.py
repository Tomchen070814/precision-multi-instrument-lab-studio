from pathlib import Path

import pytest

from hp3458a_studio.models import Measurement
from hp3458a_studio.persistence import DurableSessionWriter, list_recovery_files


@pytest.mark.parametrize("failed_suffix", [".partial.csv", ".json.tmp"])
def test_finalize_can_retry_failed_rename_without_losing_capture(
    tmp_path, monkeypatch, failed_suffix
):
    writer = DurableSessionWriter(
        channel="C",
        instrument_model="3458A",
        resource="GPIB0::23::INSTR",
        root=tmp_path,
    )
    writer.append(Measurement(0.0, 10.0, "V"))
    replace = Path.replace
    failed = False

    def fail_once(path, target):
        nonlocal failed
        if str(path).endswith(failed_suffix) and not failed:
            failed = True
            raise OSError("temporary file lock")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_once)
    with pytest.raises(OSError, match="temporary file lock"):
        writer.finalize("completed")
    assert writer.path.exists()
    assert "10" in writer.path.read_text(encoding="utf-8")
    if failed_suffix == ".partial.csv":
        assert len(list_recovery_files(tmp_path)) == 1
    with pytest.raises(RuntimeError, match="closed"):
        writer.append(Measurement(1.0, 11.0, "V"))
    final = writer.finalize("completed")
    assert final.exists()
    assert writer.metadata_path.exists()
    assert list_recovery_files(tmp_path) == []
    assert writer.finalize("completed") == final


def test_initial_sync_failure_closes_file_handle(tmp_path, monkeypatch):
    handles = []
    open_file = Path.open

    def track_open(path, *args, **kwargs):
        handle = open_file(path, *args, **kwargs)
        handles.append(handle)
        return handle

    def failed_sync(self):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "open", track_open)
    monkeypatch.setattr(DurableSessionWriter, "_sync", failed_sync)
    with pytest.raises(OSError, match="disk unavailable"):
        DurableSessionWriter(
            channel="A",
            instrument_model="3458A",
            resource="GPIB0::21::INSTR",
            root=tmp_path,
        )
    assert handles and all(handle.closed for handle in handles)
