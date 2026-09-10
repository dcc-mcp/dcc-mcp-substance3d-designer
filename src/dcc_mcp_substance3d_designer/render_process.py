"""Own and terminate the external SAT process tree without using the DCC as Python."""

from __future__ import annotations

import time
from types import SimpleNamespace

from ._install_process import _cleanup_owned_process, _start_owned_process
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
