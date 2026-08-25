"""Private process-group supervisor for bounded installer metadata probes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional


def _write_status(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(str(temporary), str(path))


def main(argv: Optional[List[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) >= 6 and arguments[4] == "--":
        ready_path = Path(arguments[3])
        command = arguments[5:]
    elif len(arguments) >= 5 and arguments[3] == "--":
        ready_path = None
        command = arguments[4:]
    else:
        return 64
    status_path = Path(arguments[0])
    stdout_path = Path(arguments[1])
    stderr_path = Path(arguments[2])
    parent_pid = os.getppid()
    leader_pid = os.getpid()
    leader_pgid = os.getpgrp() if os.name == "posix" else None
    if os.name == "posix" and (leader_pgid != leader_pid or os.getsid(0) != leader_pid):
        _write_status(status_path, {"state": "launch_failed", "error_type": "ProcessGroupOwnershipError"})
        return 70
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        child = None
        completed = False
        try:
            child = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                close_fds=True,
            )
        except OSError as exc:
            _write_status(status_path, {"state": "launch_failed", "error_type": exc.__class__.__name__})
        else:
            if ready_path is not None:
                _write_status(
                    ready_path,
                    {"state": "running", "pid": child.pid, "supervisor_pid": os.getpid()},
                )
        while True:
            if os.getppid() != parent_pid:
                if os.name == "posix":
                    if os.getpid() != leader_pid or os.getpgrp() != leader_pgid or os.getsid(0) != leader_pid:
                        return 70
                    os.killpg(leader_pgid, signal.SIGKILL)
                return 70
            if child is not None and not completed:
                returncode = child.poll()
                if returncode is not None:
                    completed = True
                    stdout_file.flush()
                    stderr_file.flush()
                    _write_status(
                        status_path,
                        {
                            "state": "completed",
                            "pid": child.pid,
                            "supervisor_pid": os.getpid(),
                            "returncode": int(returncode),
                        },
                    )
            time.sleep(0.02)


if __name__ == "__main__":
    raise SystemExit(main())
