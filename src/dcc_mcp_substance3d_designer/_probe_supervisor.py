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

_MAX_PROCESS_ID_DIGITS = 20
_MAX_SNAPSHOT_BYTES = 256 * 1024
_PARENT_DEATH_CLEANUP_SECONDS = 3.0
_POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)


def _write_status(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(str(temporary), str(path))


def _read_linux_process_identity(pid: int) -> Optional[dict]:
    try:
        stat = Path("/proc/{}/stat".format(pid)).read_text(encoding="utf-8")
        closing = stat.rfind(") ")
        fields = stat[closing + 2 :].split()
        return {
            "pid": pid,
            "pgid": int(fields[2]),
            "sid": int(fields[3]),
            "start_identity": fields[19],
        }
    except (IndexError, OSError, ValueError):
        return None


def _owned_session_members(pgid: int, sid: int, deadline: float) -> Optional[dict]:
    remaining = deadline - time.monotonic()
    if pgid <= 0 or sid <= 0 or remaining <= 0.0:
        return None
    try:
        completed = subprocess.run(
            ["/bin/ps", "-ax", "-o", "pid=", "-o", "pgid=", "-o", "sess="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            text=True,
            encoding="ascii",
            errors="strict",
            timeout=remaining,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if time.monotonic() >= deadline or completed.returncode != 0 or len(completed.stdout) > _MAX_SNAPSHOT_BYTES:
        return None
    members = {}
    for line in completed.stdout.splitlines():
        if time.monotonic() >= deadline:
            return None
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 3 or not all(
            len(field) <= _MAX_PROCESS_ID_DIGITS and field.isascii() and field.isdecimal() for field in fields
        ):
            return None
        try:
            pid, process_group, process_session = (int(field) for field in fields)
        except (ValueError, OverflowError):
            return None
        if time.monotonic() >= deadline:
            return None
        if process_group == pgid or process_session == sid:
            if sys.platform == "linux":
                identity = _read_linux_process_identity(pid)
                if identity is None:
                    continue
                if identity["pgid"] != process_group or identity["sid"] != process_session:
                    return None
                members[pid] = identity
            else:
                members[pid] = process_group
    return members if time.monotonic() < deadline else None


def _terminate_owned_session(leader_pid: int, leader_pgid: int, child: Optional[subprocess.Popen]) -> bool:
    deadline = time.monotonic() + _PARENT_DEATH_CLEANUP_SECONDS
    try:
        leader_matches = os.getpid() == leader_pid and os.getpgrp() == leader_pgid and os.getsid(0) == leader_pid
    except OSError:
        return False
    if not leader_matches:
        return False
    members = _owned_session_members(leader_pgid, leader_pid, deadline)
    if members is None:
        return False
    if child is not None:
        child.poll()
    if sys.platform == "linux":
        pidfd_open = getattr(os, "pidfd_open", None)
        pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
        if pidfd_open is None or pidfd_send_signal is None:
            return False
        leader_identity = members.get(leader_pid)
        if not isinstance(leader_identity, dict) or leader_identity.get("pgid") != leader_pgid:
            return False
        tokens = []
        try:
            ordered_pids = sorted((pid for pid in members if pid != leader_pid), reverse=True) + [leader_pid]
            for pid in ordered_pids:
                if time.monotonic() >= deadline:
                    return False
                if pid == leader_pid:
                    if os.getpid() != leader_pid or os.getpgrp() != leader_pgid or os.getsid(0) != leader_pid:
                        return False
                elif not isinstance(members[pid], dict):
                    return False
                try:
                    token = int(pidfd_open(pid, 0))
                except ProcessLookupError:
                    continue
                except OSError:
                    return False
                current = _read_linux_process_identity(pid)
                expected = members[pid]
                if (
                    current is None
                    or current.get("pid") != expected.get("pid")
                    or current.get("sid") != leader_pid
                    or current.get("start_identity") != expected.get("start_identity")
                ):
                    try:
                        os.close(token)
                    except OSError:
                        pass
                    continue
                tokens.append((pid, token))
            for _pid, token in tokens:
                if time.monotonic() >= deadline:
                    return False
                try:
                    pidfd_send_signal(token, _POSIX_SIGKILL, None, 0)
                except ProcessLookupError:
                    continue
                except OSError:
                    return False
            return False
        finally:
            for _pid, token in reversed(tokens):
                try:
                    os.close(token)
                except OSError:
                    pass
    if members.get(leader_pid) != leader_pgid:
        return False
    changed_groups = sorted(
        {process_group for pid, process_group in members.items() if pid != leader_pid and process_group != leader_pgid},
        reverse=True,
    )
    if changed_groups:
        return False
    if time.monotonic() >= deadline:
        return False
    try:
        if os.getpid() != leader_pid or os.getpgrp() != leader_pgid or os.getsid(0) != leader_pid:
            return False
        os.killpg(leader_pgid, _POSIX_SIGKILL)
    except OSError:
        return False
    return False


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
                    _terminate_owned_session(leader_pid, leader_pgid, child)
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
