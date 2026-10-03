"""Own and terminate the external SAT process tree without using the DCC as Python."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from ._install_process import _cleanup_owned_process, _run_bounded_command_in_root, _start_owned_process
from .graph_authoring import GraphAuthoringError


def run_renderer(command: list[str], *, timeout: float = 600):
    if not 1 <= timeout <= 600:
        raise GraphAuthoringError("Renderer timeout must be 1..600 seconds", "INVALID_RENDER_TIMEOUT")
    deadline = time.monotonic() + timeout
    reserve = min(2.0, timeout * 0.25)
    process, owner = _start_owned_process(command, env=None, cwd=None, deadline=deadline)
    try:
        code = process.wait(timeout=max(0.0, deadline - reserve - time.monotonic()))
    finally:
        # Windows Job ownership is established before the suspended SAT process
        # starts. No unowned PID is killed, including after timeout or interruption.
        if not _cleanup_owned_process(process, owner, deadline=deadline):
            raise GraphAuthoringError("Could not verify renderer process-tree cleanup", "RENDER_CLEANUP_FAILED")
    return SimpleNamespace(returncode=code)


def run_artifact_command(command: list[str], log: Path, *, timeout: int = 300) -> None:
    """Capture bounded CLI logs using the existing owned process-tree supervisor."""
    if type(timeout) is not int or not 1 <= timeout <= 600:
        raise GraphAuthoringError("Artifact timeout must be 1..600 seconds", "INVALID_RENDER_TIMEOUT")
    with tempfile.TemporaryDirectory(prefix="designer-artifact-process-") as temporary:
        result = _run_bounded_command_in_root(command, Path(temporary), deadline=time.monotonic() + timeout)
    text = str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))
    log.write_text(text, encoding="utf-8")
    if not result.get("success") or "[ERROR]" in text:
        raise GraphAuthoringError(
            "Official CLI failed, timed out or could not verify cleanup", "OFFLINE_PROCESS_FAILED"
        )
