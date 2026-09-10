import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import render_process as renderer
from dcc_mcp_substance3d_designer._install_process import observe_process_identity


def test_renderer_cleanup_runs_on_timeout(monkeypatch):
    events = []

    def wait(**kwargs):
        raise subprocess.TimeoutExpired("sbsrender", 2)

    process = SimpleNamespace(wait=wait)
    owner = object()
    monkeypatch.setattr(renderer, "_start_owned_process", lambda *args, **kwargs: (process, owner))
    monkeypatch.setattr(renderer, "_cleanup_owned_process", lambda p, o, **kwargs: events.append((p, o)) or True)
    with pytest.raises(subprocess.TimeoutExpired):
        renderer.run_renderer(["sbsrender"], timeout=2)
    assert events == [(process, owner)]


@pytest.mark.skipif(os.name != "nt", reason="Real Windows Job tree integration")
def test_windows_renderer_timeout_removes_owned_descendant(tmp_path):
    marker = tmp_path / "child.pid"
    child = (
        "import os,time,pathlib; pathlib.Path(" + repr(str(marker)) + ").write_text(str(os.getpid())); time.sleep(60)"
    )
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(60)"
    with pytest.raises(subprocess.TimeoutExpired):
        renderer.run_renderer([sys.executable, "-c", parent], timeout=4)
    assert marker.is_file(), "Child must have started for the cleanup assertion to be meaningful"
    assert observe_process_identity(int(marker.read_text())) is None
