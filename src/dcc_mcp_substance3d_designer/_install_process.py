"""Owned process-tree probes and runtime identity observations."""

from __future__ import annotations

import ctypes
import ipaddress
import json
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_MAX_PROBE_OUTPUT_BYTES = 256 * 1024
_MIN_PROBE_TIMEOUT_SECONDS = 0.1
_MAX_PROBE_TIMEOUT_SECONDS = 30.0
_MAX_POSIX_PROCESS_ID_DIGITS = 20
_MAX_PROCESS_CLEANUP_RESERVE_SECONDS = 2.0
_MIN_PROCESS_CLEANUP_RESERVE_SECONDS = 0.05
_POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)
_PROC_PIDTBSDINFO = 3
_DARWIN_PROCESS_STATUS_ZOMBIE = 5


def _deadline_expired(deadline: float) -> bool:
    return not math.isfinite(deadline) or time.monotonic() >= deadline


def _deadline_remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


class _DarwinProcBsdInfo(ctypes.Structure):
    """Darwin ``proc_bsdinfo`` from libproc.h (PROC_PIDTBSDINFO)."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _read_darwin_bsd_identity(pid: int, proc_pidinfo) -> Optional[Dict[str, Any]]:
    """Read a PID-reuse-safe kernel creation timestamp from ``proc_pidinfo``."""
    info = _DarwinProcBsdInfo()
    size = ctypes.sizeof(info)
    try:
        returned = int(proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), size))
    except (OSError, TypeError, ValueError):
        return None
    seconds = int(info.pbi_start_tvsec)
    microseconds = int(info.pbi_start_tvusec)
    parent_pid = int(info.pbi_ppid)
    if (
        returned != size
        or int(info.pbi_pid) != pid
        or int(info.pbi_status) == _DARWIN_PROCESS_STATUS_ZOMBIE
        or parent_pid <= 0
        or seconds <= 0
        or not 0 <= microseconds < 1_000_000
    ):
        return None
    return {
        "parent_pid": parent_pid,
        "start_identity": "darwin-proc-bsdinfo:{}:{:06d}".format(seconds, microseconds),
    }


def _list_posix_process_group_members(
    pgid: int,
    *,
    sid: Optional[int] = None,
    deadline: float,
) -> Optional[set[int]]:
    """Return the owned process-group/session snapshot or fail closed."""
    if pgid <= 0 or (sid is not None and sid <= 0) or _deadline_expired(deadline):
        return None
    remaining = _deadline_remaining(deadline)
    if remaining <= 0.0:
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
    if _deadline_expired(deadline):
        return None
    if completed.returncode != 0 or len(completed.stdout) > _MAX_PROBE_OUTPUT_BYTES:
        return None
    members = set()
    for line in completed.stdout.splitlines():
        if _deadline_expired(deadline):
            return None
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 3 or not all(
            len(field) <= _MAX_POSIX_PROCESS_ID_DIGITS and field.isascii() and field.isdecimal() for field in fields
        ):
            return None
        try:
            process_pid, process_group, process_session = (int(field) for field in fields)
        except (ValueError, OverflowError):
            return None
        if _deadline_expired(deadline):
            return None
        if process_group == pgid or (sid is not None and process_session == sid):
            members.add(process_pid)
    return members if not _deadline_expired(deadline) else None


class _ProcessTreeOwner:
    def terminate(self, *, deadline: Optional[float] = None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None

    def wait_empty(self, deadline: float) -> bool:
        return not _deadline_expired(deadline)


class _PosixProcessTreeOwner(_ProcessTreeOwner):
    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self._leader_pid = int(process.pid)
        try:
            self._pgid = int(os.getpgid(self._leader_pid))
            self._sid = int(os.getsid(self._leader_pid))
        except OSError as exc:
            raise OSError("owned session leader identity is unavailable") from exc
        self._leader_identity = observe_process_identity(self._leader_pid)
        if self._pgid != self._leader_pid or self._sid != self._leader_pid or self._leader_identity is None:
            raise OSError("owned process is not an identity-bound session leader")

    def _leader_matches(self) -> bool:
        if self._process.poll() is not None:
            return False
        try:
            current_pgid = int(os.getpgid(self._leader_pid))
            current_sid = int(os.getsid(self._leader_pid))
        except OSError:
            return False
        current_identity = observe_process_identity(self._leader_pid)
        if current_identity is None:
            return False
        return (
            current_pgid == self._pgid
            and current_sid == self._sid
            and all(
                current_identity.get(field) == self._leader_identity.get(field) for field in ("pid", "start_identity")
            )
        )

    @staticmethod
    def _same_process_identity(expected: Dict[str, Any], current: Optional[Dict[str, Any]]) -> bool:
        return current is not None and all(
            current.get(field) == expected.get(field) for field in ("pid", "start_identity")
        )

    def terminate(self, *, deadline: Optional[float] = None) -> None:
        if deadline is None:
            deadline = time.monotonic() + 3.0
        if _deadline_expired(deadline):
            raise OSError("owned session cleanup deadline expired")
        if self._process.poll() is not None:
            return
        while True:
            if _deadline_expired(deadline) or not self._leader_matches():
                raise OSError("owned session leader identity changed before cleanup")
            members = _list_posix_process_group_members(self._pgid, sid=self._sid, deadline=deadline)
            if members is None or self._leader_pid not in members or _deadline_expired(deadline):
                raise OSError("owned session membership is unavailable")
            descendants = sorted(members - {self._leader_pid}, reverse=True)
            if not descendants:
                if not self._leader_matches() or _deadline_expired(deadline):
                    raise OSError("owned session leader identity changed before cleanup")
                os.kill(self._leader_pid, _POSIX_SIGKILL)
                return
            for pid in descendants:
                if _deadline_expired(deadline) or not self._leader_matches():
                    raise OSError("owned session leader identity changed before cleanup")
                expected = observe_process_identity(pid)
                if _deadline_expired(deadline):
                    raise OSError("owned session cleanup deadline expired")
                if expected is None:
                    continue
                try:
                    current_sid = int(os.getsid(pid))
                except ProcessLookupError:
                    continue
                except OSError as exc:
                    raise OSError("owned session member identity is unavailable") from exc
                current = observe_process_identity(pid)
                if _deadline_expired(deadline):
                    raise OSError("owned session cleanup deadline expired")
                if current is None:
                    continue
                if current_sid != self._sid or not self._same_process_identity(expected, current):
                    raise OSError("owned session member identity changed before cleanup")
                try:
                    os.kill(pid, _POSIX_SIGKILL)
                except ProcessLookupError:
                    pass
            time.sleep(min(0.01, _deadline_remaining(deadline)))

    def wait_empty(self, deadline: float) -> bool:
        if _deadline_expired(deadline):
            return False
        try:
            self._process.wait(timeout=_deadline_remaining(deadline))
        except (OSError, subprocess.TimeoutExpired):
            return False
        if _deadline_expired(deadline):
            return False
        while True:
            if _deadline_expired(deadline):
                return False
            members = _list_posix_process_group_members(self._pgid, sid=self._sid, deadline=deadline)
            if _deadline_expired(deadline):
                return False
            if members is None:
                return False
            if not members:
                return True
            time.sleep(min(0.01, _deadline_remaining(deadline)))


class _WindowsProcessTreeOwner(_ProcessTreeOwner):
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _THREAD_SUSPEND_RESUME = 0x0002
    _TH32CS_SNAPTHREAD = 0x00000004

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class _BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        self._handle = handle
        self._accounting_type = _BasicAccountingInformation
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            self._kernel32.CloseHandle(handle)
            self._handle = None
            raise OSError(error, "SetInformationJobObject failed")

    def assign(self, process: subprocess.Popen) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def terminate(self, *, deadline: Optional[float] = None) -> None:
        if deadline is not None and _deadline_expired(deadline):
            raise OSError("owned Job cleanup deadline expired")
        if self._handle and not self._kernel32.TerminateJobObject(self._handle, 1):
            raise OSError(self._ctypes.get_last_error(), "TerminateJobObject failed")

    def wait_empty(self, deadline: float) -> bool:
        while self._handle:
            if _deadline_expired(deadline):
                return False
            accounting = self._accounting_type()
            if not self._kernel32.QueryInformationJobObject(
                self._handle,
                self._JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                self._ctypes.byref(accounting),
                self._ctypes.sizeof(accounting),
                None,
            ):
                return False
            if _deadline_expired(deadline):
                return False
            if accounting.ActiveProcesses == 0:
                return True
            time.sleep(min(0.01, _deadline_remaining(deadline)))
        return not _deadline_expired(deadline)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _resume_windows_process(process: subprocess.Popen) -> None:
    import ctypes
    from ctypes import wintypes

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(_WindowsProcessTreeOwner._TH32CS_SNAPTHREAD, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    resumed = False
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while present:
            if entry.th32OwnerProcessID == process.pid:
                thread = kernel32.OpenThread(_WindowsProcessTreeOwner._THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread:
                    try:
                        if kernel32.ResumeThread(thread) != 0xFFFFFFFF:
                            resumed = True
                    finally:
                        kernel32.CloseHandle(thread)
            present = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    if not resumed:
        raise OSError("No suspended supervisor thread could be resumed")


def _start_owned_process(
    command: Sequence[str],
    *,
    env: Optional[Dict[str, str]],
    cwd: Optional[Path],
    deadline: Optional[float] = None,
):
    if deadline is not None and _deadline_expired(deadline):
        raise TimeoutError("probe deadline expired before launch")
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": env,
        "cwd": None if cwd is None else str(cwd),
    }
    if os.name == "posix":
        if deadline is not None and _deadline_expired(deadline):
            raise TimeoutError("probe deadline expired before launch")
        process = subprocess.Popen(list(command), start_new_session=True, **kwargs)
        owner = None
        try:
            owner = _PosixProcessTreeOwner(process)
            if deadline is not None and _deadline_expired(deadline):
                raise TimeoutError("probe deadline expired during launch")
            return process, owner
        except BaseException:
            if owner is not None:
                if deadline is not None:
                    _cleanup_owned_process(process, owner, deadline=deadline)
                else:
                    _cleanup_owned_process(process, owner)
                raise
            try:
                if process.poll() is None and os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                if process.poll() is None:
                    process.kill()
            wait_timeout = 3.0 if deadline is None else _deadline_remaining(deadline)
            try:
                process.wait(timeout=wait_timeout)
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise
    if os.name == "nt":
        if deadline is not None and _deadline_expired(deadline):
            raise TimeoutError("probe deadline expired before Job creation")
        owner = _WindowsProcessTreeOwner()
        process = None
        try:
            if deadline is not None and _deadline_expired(deadline):
                raise TimeoutError("probe deadline expired before launch")
            process = subprocess.Popen(
                list(command), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x00000004, **kwargs
            )
            if deadline is not None and _deadline_expired(deadline):
                raise TimeoutError("probe deadline expired during launch")
            owner.assign(process)
            if deadline is not None and _deadline_expired(deadline):
                raise TimeoutError("probe deadline expired while assigning Job")
            _resume_windows_process(process)
            if deadline is not None and _deadline_expired(deadline):
                raise TimeoutError("probe deadline expired while resuming process")
            return process, owner
        except BaseException:
            try:
                owner.terminate(deadline=deadline)
            except OSError:
                pass
            if process is not None:
                if process.poll() is None:
                    process.kill()
                wait_timeout = 3.0 if deadline is None else _deadline_remaining(deadline)
                try:
                    process.wait(timeout=wait_timeout)
                except subprocess.TimeoutExpired:
                    pass
            owner.close()
            raise
    if deadline is not None and _deadline_expired(deadline):
        raise TimeoutError("probe deadline expired before launch")
    process = subprocess.Popen(list(command), **kwargs)
    if deadline is not None and _deadline_expired(deadline):
        try:
            process.kill()
            process.wait(timeout=_deadline_remaining(deadline))
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise TimeoutError("probe deadline expired during launch")
    return process, _ProcessTreeOwner()


def _read_supervisor_status(path: Path, *, deadline: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if deadline is not None and _deadline_expired(deadline):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    if deadline is not None and _deadline_expired(deadline):
        return None
    return payload if isinstance(payload, dict) else None


class _SupervisedProcess:
    """Popen-compatible child view whose durable supervisor remains the tree leader."""

    def __init__(self, supervisor: subprocess.Popen, status_path: Path, pid: int, supervisor_pid: int) -> None:
        self._supervisor = supervisor
        self._status_path = status_path
        self.pid = pid
        self.supervisor_pid = supervisor_pid

    def poll(self) -> Optional[int]:
        status = _read_supervisor_status(self._status_path)
        if status is not None and status.get("state") == "completed":
            return int(status.get("returncode", -1))
        if status is not None and status.get("state") == "launch_failed":
            return 127
        supervisor_result = self._supervisor.poll()
        return None if supervisor_result is None else int(supervisor_result)

    def wait(self, timeout: Optional[float] = None) -> int:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("owned supervised process", timeout)
            time.sleep(0.01)

    def kill(self) -> None:
        if self._supervisor.poll() is None:
            self._supervisor.kill()


def _start_owned_supervised_process(
    command: Sequence[str],
    *,
    env: Optional[Dict[str, str]],
    cwd: Optional[Path],
    root: Path,
):
    """Start a command below a durable Job/session leader and return its child identity."""
    root.mkdir(parents=True, exist_ok=False)
    status_path = root / "status.json"
    ready_path = root / "ready.json"
    stdout_path = root / "stdout.bin"
    stderr_path = root / "stderr.bin"
    supervisor_script = Path(__file__).with_name("_probe_supervisor.py").resolve(strict=True)
    supervisor_command = [
        sys.executable,
        str(supervisor_script),
        str(status_path),
        str(stdout_path),
        str(stderr_path),
        str(ready_path),
        "--",
        *list(command),
    ]
    supervisor = None
    owner = None
    try:
        supervisor, owner = _start_owned_process(supervisor_command, env=env, cwd=cwd)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            ready = _read_supervisor_status(ready_path)
            status = _read_supervisor_status(status_path)
            for record in (ready, status):
                if record is None:
                    continue
                state = record.get("state")
                child_pid = record.get("pid")
                supervisor_pid = record.get("supervisor_pid")
                if (
                    state in {"running", "completed"}
                    and isinstance(child_pid, int)
                    and child_pid > 0
                    and isinstance(supervisor_pid, int)
                    and supervisor_pid > 0
                ):
                    return _SupervisedProcess(supervisor, status_path, child_pid, supervisor_pid), owner
                if state == "launch_failed":
                    raise OSError("owned command launch failed")
            if supervisor.poll() is not None:
                raise OSError("owned supervisor exited before readiness")
            time.sleep(0.01)
        raise OSError("owned command readiness timed out")
    except BaseException:
        if supervisor is not None and owner is not None:
            _cleanup_owned_process(supervisor, owner)
        raise


def _cleanup_owned_process(
    process: Any,
    owner: _ProcessTreeOwner,
    *,
    deadline: Optional[float] = None,
) -> bool:
    if deadline is None:
        deadline = time.monotonic() + 3.0
    clean = True
    expired = _deadline_expired(deadline)
    try:
        owner.terminate(deadline=deadline)
    except (NotImplementedError, OSError):
        clean = False
        if process.poll() is None:
            process.kill()
    if _deadline_expired(deadline):
        clean = False
    try:
        process.wait(timeout=_deadline_remaining(deadline))
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=_deadline_remaining(deadline))
        except (OSError, subprocess.TimeoutExpired):
            clean = False
    if _deadline_expired(deadline):
        clean = False
    try:
        if not owner.wait_empty(deadline):
            clean = False
    finally:
        owner.close()
    return clean and not expired and not _deadline_expired(deadline)


def _remove_probe_directory(
    root: Path,
    timeout: float = 3.0,
    *,
    deadline: Optional[float] = None,
) -> bool:
    if deadline is None:
        budget = float(timeout)
        if not math.isfinite(budget) or budget < 0.0:
            return False
        deadline = time.monotonic() + budget
    while True:
        expired_before_cleanup = _deadline_expired(deadline)
        try:
            shutil.rmtree(root)
            return not expired_before_cleanup and not _deadline_expired(deadline)
        except FileNotFoundError:
            return not expired_before_cleanup and not _deadline_expired(deadline)
        except OSError:
            if expired_before_cleanup or _deadline_expired(deadline):
                return False
            time.sleep(min(0.02, _deadline_remaining(deadline)))


def _run_bounded_command_in_root(
    command: Sequence[str],
    root: Path,
    *,
    deadline: float,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> Dict[str, Any]:
    timeout_result = {"success": False, "reason": "probe timed out", "truncated": False}
    if _deadline_expired(deadline):
        return timeout_result
    initial_remaining = _deadline_remaining(deadline)
    cleanup_reserve = min(
        _MAX_PROCESS_CLEANUP_RESERVE_SECONDS,
        max(_MIN_PROCESS_CLEANUP_RESERVE_SECONDS, initial_remaining * 0.25),
    )
    operation_cutoff = deadline - cleanup_reserve
    if time.monotonic() >= operation_cutoff:
        return timeout_result
    status_path = root / "status.json"
    stdout_path = root / "stdout.bin"
    stderr_path = root / "stderr.bin"
    if _deadline_expired(deadline):
        return timeout_result
    supervisor_script = Path(__file__).with_name("_probe_supervisor.py").resolve(strict=True)
    if _deadline_expired(deadline):
        return timeout_result
    supervisor = [
        sys.executable,
        str(supervisor_script),
        str(status_path),
        str(stdout_path),
        str(stderr_path),
        "--",
        *list(command),
    ]
    if _deadline_expired(deadline) or time.monotonic() >= operation_cutoff:
        return timeout_result
    try:
        process, owner = _start_owned_process(supervisor, env=env, cwd=cwd, deadline=deadline)
    except TimeoutError:
        return timeout_result
    except OSError as exc:
        if _deadline_expired(deadline):
            return timeout_result
        return {"success": False, "reason": "launch failed: " + exc.__class__.__name__}
    record = None
    reason = None
    cleanup_ok = True
    timed_out = False
    try:
        while not _deadline_expired(deadline) and time.monotonic() < operation_cutoff:
            oversized = False
            for path in (stdout_path, stderr_path):
                if _deadline_expired(deadline):
                    timed_out = True
                    break
                try:
                    size = path.stat().st_size
                except FileNotFoundError:
                    size = 0
                except OSError:
                    reason = "probe output inspection failed"
                    break
                if _deadline_expired(deadline):
                    timed_out = True
                    break
                if size > _MAX_PROBE_OUTPUT_BYTES:
                    oversized = True
                    break
            if timed_out or reason is not None:
                break
            if oversized:
                reason = "probe output exceeded limit"
                break
            if _deadline_expired(deadline):
                timed_out = True
                break
            status_present = status_path.is_file()
            if _deadline_expired(deadline):
                timed_out = True
                break
            if status_present:
                record = _read_supervisor_status(status_path, deadline=deadline)
                if _deadline_expired(deadline):
                    timed_out = True
                    record = None
                    break
                if record is None:
                    reason = "probe returned invalid status"
                break
            if _deadline_expired(deadline):
                timed_out = True
                break
            supervisor_result = process.poll()
            if _deadline_expired(deadline):
                timed_out = True
                break
            if supervisor_result is not None:
                reason = "probe supervisor exited unexpectedly"
                break
            time.sleep(min(0.02, _deadline_remaining(deadline)))
        else:
            timed_out = True
    finally:
        cleanup_ok = _cleanup_owned_process(process, owner, deadline=deadline)
        if _deadline_expired(deadline):
            timed_out = True
    if timed_out:
        return timeout_result
    stdout = b""
    stderr = b""
    for path, stream_name in ((stdout_path, "stdout"), (stderr_path, "stderr")):
        if _deadline_expired(deadline):
            return timeout_result
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            payload = b""
        except OSError:
            return {"success": False, "reason": "probe output read failed", "truncated": False}
        if _deadline_expired(deadline):
            return timeout_result
        if stream_name == "stdout":
            stdout = payload
        else:
            stderr = payload
    truncated = len(stdout) > _MAX_PROBE_OUTPUT_BYTES or len(stderr) > _MAX_PROBE_OUTPUT_BYTES
    if not cleanup_ok:
        return {"success": False, "reason": "probe cleanup failed", "truncated": truncated}
    if record is None:
        return {"success": False, "reason": reason or "probe failed", "truncated": truncated}
    returncode = int(record.get("returncode", -1))
    result = {
        "success": record.get("state") == "completed" and returncode == 0 and not truncated,
        "returncode": returncode,
        "reason": None if record.get("state") == "completed" else "probe launch failed",
        "stdout": stdout[:_MAX_PROBE_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr": stderr[:_MAX_PROBE_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "truncated": truncated,
    }
    if _deadline_expired(deadline):
        return timeout_result
    return result


def run_bounded_command(
    command: Sequence[str],
    *,
    timeout: float = 20.0,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
    private_cwd: bool = False,
) -> Dict[str, Any]:
    """Run metadata probes under an owned process tree and bounded deadline."""
    try:
        budget = float(timeout)
    except (TypeError, ValueError, OverflowError):
        budget = float("nan")
    if (
        isinstance(timeout, bool)
        or not math.isfinite(budget)
        or not _MIN_PROBE_TIMEOUT_SECONDS <= budget <= _MAX_PROBE_TIMEOUT_SECONDS
    ):
        return {"success": False, "reason": "invalid probe timeout", "truncated": False}
    started = time.monotonic()
    deadline = started + budget
    if not math.isfinite(started) or not math.isfinite(deadline) or _deadline_expired(deadline):
        return {"success": False, "reason": "probe timed out", "truncated": False}
    root = Path(tempfile.mkdtemp(prefix="dcc-mcp-designer-probe-"))
    if _deadline_expired(deadline):
        _remove_probe_directory(root, deadline=deadline)
        return {"success": False, "reason": "probe timed out", "truncated": False}
    try:
        result = _run_bounded_command_in_root(
            command,
            root,
            deadline=deadline,
            env=env,
            cwd=root if private_cwd else cwd,
        )
    except BaseException:
        _remove_probe_directory(root, deadline=deadline)
        raise
    cleanup_ok = _remove_probe_directory(root, deadline=deadline)
    if _deadline_expired(deadline):
        return {"success": False, "reason": "probe timed out", "truncated": bool(result.get("truncated"))}
    if not cleanup_ok:
        return {"success": False, "reason": "probe cleanup failed", "truncated": bool(result.get("truncated"))}
    return result


def observe_process_identity(pid: int) -> Optional[Dict[str, Any]]:
    """Observe executable and start identity independently from registry/probe claims."""
    if pid <= 0:
        return None
    if sys.platform == "win32":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

        class _ProcessBasicInformation(ctypes.Structure):
            _fields_ = [
                ("Reserved1", ctypes.c_void_p),
                ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2),
                ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p),
            ]

        ntdll.NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        ntdll.NtQueryInformationProcess.restype = wintypes.LONG
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32_768)
            length = wintypes.DWORD(len(buffer))
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return None
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            basic = _ProcessBasicInformation()
            returned = wintypes.ULONG()
            parent_pid = None
            if (
                ntdll.NtQueryInformationProcess(
                    handle,
                    0,
                    ctypes.byref(basic),
                    ctypes.sizeof(basic),
                    ctypes.byref(returned),
                )
                == 0
            ):
                parent_pid = int(basic.InheritedFromUniqueProcessId or 0) or None
            started = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            return {
                "pid": pid,
                "parent_pid": parent_pid,
                "executable": str(Path(buffer.value).resolve()),
                "start_identity": "windows-filetime:" + str(started),
            }
        finally:
            kernel32.CloseHandle(handle)
    if sys.platform == "darwin":
        buffer = ctypes.create_string_buffer(4096)
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            libproc.proc_pidpath.restype = ctypes.c_int
            libproc.proc_pidinfo.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            libproc.proc_pidinfo.restype = ctypes.c_int
            length = int(libproc.proc_pidpath(pid, buffer, len(buffer)))
        except (OSError, AttributeError):
            return None
        if length <= 0:
            return None
        bsd_identity = _read_darwin_bsd_identity(pid, libproc.proc_pidinfo)
        if bsd_identity is None:
            return None
        try:
            executable = str(Path(buffer.value.decode("utf-8", errors="strict")).resolve())
        except (UnicodeError, ValueError):
            return None
        return {
            "pid": pid,
            "parent_pid": bsd_identity["parent_pid"],
            "executable": executable,
            "start_identity": bsd_identity["start_identity"],
        }
    try:
        executable = Path("/proc/{}/exe".format(pid)).resolve(strict=True)
        stat = Path("/proc/{}/stat".format(pid)).read_text(encoding="utf-8")
        closing = stat.rfind(") ")
        fields = stat[closing + 2 :].split()
        parent_pid = int(fields[1])
        start_ticks = fields[19]
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (IndexError, OSError, ValueError):
        return None
    return {
        "pid": pid,
        "parent_pid": parent_pid,
        "executable": str(executable),
        "start_identity": "linux:{}:{}".format(boot_id, start_ticks),
    }


def observe_listener_identity(mcp_url: str) -> Optional[Dict[str, Any]]:
    """Observe one exact loopback listener process without trusting registry PID claims."""
    parsed = urllib.parse.urlparse(mcp_url)
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = False
    if parsed.scheme != "http" or parsed.port is None or not loopback:
        return None
    port = int(parsed.port)
    owner_pids = set()
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _TcpRowOwnerPid(ctypes.Structure):
            _fields_ = [
                ("state", wintypes.DWORD),
                ("local_addr", wintypes.DWORD),
                ("local_port", wintypes.DWORD),
                ("remote_addr", wintypes.DWORD),
                ("remote_port", wintypes.DWORD),
                ("owning_pid", wintypes.DWORD),
            ]

        iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
        size = wintypes.ULONG(0)
        result = iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if result not in (0, 122):
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if iphlpapi.GetExtendedTcpTable(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0) != 0:
            return None
        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        offset = ctypes.sizeof(wintypes.DWORD)
        rows = ctypes.cast(ctypes.addressof(buffer) + offset, ctypes.POINTER(_TcpRowOwnerPid))
        owner_pids = {
            int(rows[index].owning_pid)
            for index in range(count)
            if int(rows[index].state) == 2 and socket.ntohs(int(rows[index].local_port) & 0xFFFF) == port
        }
    elif sys.platform == "darwin":
        result = run_bounded_command(["lsof", "-nP", "-F", "p", "-iTCP:{}".format(port), "-sTCP:LISTEN"], timeout=3.0)
        if result.get("success"):
            owner_pids = {
                int(line[1:])
                for line in str(result.get("stdout") or "").splitlines()
                if line.startswith("p") and line[1:].isdigit()
            }
    else:
        inodes = set()
        for table_path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
            try:
                rows = table_path.read_text(encoding="ascii").splitlines()[1:]
            except OSError:
                continue
            for row in rows:
                columns = row.split()
                if len(columns) > 9 and int(columns[1].split(":")[1], 16) == port and columns[3] == "0A":
                    inodes.add(columns[9])
        if inodes:
            try:
                process_roots = tuple(path for path in Path("/proc").iterdir() if path.name.isdigit())
            except OSError:
                process_roots = ()
            sockets = {"socket:[{}]".format(inode) for inode in inodes}
            for process_root in process_roots:
                try:
                    if any(path.readlink().as_posix() in sockets for path in (process_root / "fd").iterdir()):
                        owner_pids.add(int(process_root.name))
                except OSError:
                    continue
    if len(owner_pids) != 1:
        return None
    identity = observe_process_identity(owner_pids.pop())
    if identity is None:
        return None
    return {**identity, "listener_port": port}


__all__ = ["observe_listener_identity", "observe_process_identity", "run_bounded_command"]
