"""Transient Windows file sharing must not forge success or extend deadlines."""

from pathlib import Path

import pytest

from dcc_mcp_substance3d_designer import _install_process, render_process
from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError


def test_status_sharing_violation_retries_the_same_atomic_receipt(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    status.write_text('{"state":"completed","returncode":0}', encoding="utf-8")
    original = Path.read_text
    reads = []

    def read(path, *args, **kwargs):
        reads.append(path)
        if len(reads) == 1:
            failure = PermissionError("temporarily held native status")
            failure.winerror = 32
            raise failure
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert _install_process._read_supervisor_status(status) == {"state": "completed", "returncode": 0}
    assert reads == [status, status]


@pytest.mark.parametrize("failure", [PermissionError("access denied"), ValueError("invalid JSON")])
def test_permanent_or_invalid_status_is_not_retried(tmp_path, monkeypatch, failure):
    reads = []

    def read(*args, **kwargs):
        reads.append(1)
        raise failure

    monkeypatch.setattr(Path, "read_text", read)
    assert _install_process._read_supervisor_status(tmp_path / "status.json") is None
    assert len(reads) == 1


def test_status_sharing_retry_respects_the_existing_absolute_deadline(tmp_path, monkeypatch):
    clock = [100.0]
    reads = []

    def read(*args, **kwargs):
        reads.append(1)
        failure = PermissionError("held status")
        failure.winerror = 33
        raise failure

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(_install_process.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(_install_process.time, "sleep", sleep)
    assert _install_process._read_supervisor_status(tmp_path / "status.json", deadline=100.05) is None
    assert clock[0] == 100.05
    assert len(reads) < 5


def test_artifact_cleanup_uses_the_native_deadline_and_keeps_diagnostics(tmp_path, monkeypatch):
    deadlines = []
    log = tmp_path / "native.log"

    def run(command, root, *, deadline):
        deadlines.append(deadline)
        (root / "stderr.bin").write_bytes(b"native warning")
        return {"success": True, "stdout": "complete", "stderr": "native warning"}

    def remove(root, *, deadline):
        deadlines.append(deadline)
        assert log.read_text() == "complete\nnative warning"
        (root / "stderr.bin").unlink()
        root.rmdir()
        return False

    monkeypatch.setattr(render_process, "_run_bounded_command_in_root", run)
    monkeypatch.setattr(render_process, "_remove_probe_directory", remove)
    with pytest.raises(GraphAuthoringError) as failure:
        render_process.run_artifact_command(["test-only-unexecuted"], log, timeout=5)
    assert failure.value.code == "OFFLINE_CLEANUP_FAILED"
    assert len(deadlines) == 2 and deadlines[0] == deadlines[1]


def test_completed_native_status_survives_one_sharing_violation(tmp_path, monkeypatch):
    original = Path.read_text
    status_reads = []

    def read(path, *args, **kwargs):
        if path.name == "status.json":
            status_reads.append(1)
            if len(status_reads) == 1:
                failure = PermissionError("held native receipt")
                failure.winerror = 32
                raise failure
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    import sys

    result = _install_process.run_bounded_command([sys.executable, "-c", "print('native-complete')"], timeout=5)
    assert result["success"] is True
    assert result["stdout"].strip() == "native-complete"
    assert len(status_reads) >= 2
