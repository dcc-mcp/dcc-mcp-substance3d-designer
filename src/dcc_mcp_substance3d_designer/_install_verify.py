"""Fail-closed Designer receipt, runtime, endpoint, and typed-probe verification."""

from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from dcc_mcp_core.deployment import probe_sidecar_tool, query_runtime_state

from dcc_mcp_substance3d_designer.__version__ import __version__
from dcc_mcp_substance3d_designer._install_model import (
    DCC_TYPE,
    MIN_CORE_VERSION,
    READINESS_TOOL,
    InstallContext,
    LifecycleFailure,
)
from dcc_mcp_substance3d_designer._install_preflight import query_python, version_tuple
from dcc_mcp_substance3d_designer._install_process import observe_listener_identity as _observe_listener_identity
from dcc_mcp_substance3d_designer._install_process import observe_process_identity as _observe_process_identity
from dcc_mcp_substance3d_designer._install_receipt import load_and_validate_receipt


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _launcher_command(ctx: InstallContext) -> Sequence[str]:
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ctx.launcher_path)]
    return [str(ctx.launcher_path)]


def _readiness_next_steps(ctx: InstallContext) -> Sequence[Dict[str, Any]]:
    return [
        {
            "id": "launch_designer",
            "description": "Launch Designer through the receipted adapter launcher.",
            "command": list(_launcher_command(ctx)),
            "why": "Designer reads its plugin and Python paths only when the host process starts.",
        },
        {
            "id": "verify_install",
            "description": "Verify the installed adapter after Designer finishes starting.",
            "command": [
                "dcc-mcp-substance3d-designer",
                "verify",
                "--dcc-path",
                str(ctx.host_path),
                "--python",
                str(ctx.python_path),
                "--json",
            ],
            "why": "Direct usability requires a fresh identity-bound Designer main-thread ping.",
        },
    ]


def _parse_streamable_response(body: str) -> Any:
    candidate = body.strip()
    if candidate.startswith("event:") or "\ndata:" in candidate:
        data_lines = [line.removeprefix("data:").strip() for line in candidate.splitlines() if line.startswith("data:")]
        candidate = data_lines[-1] if data_lines else ""
    try:
        return json.loads(candidate)
    except ValueError:
        return None


def _streamable_call(mcp_url: str, tool_name: str, arguments: Mapping[str, Any], timeout_secs: float) -> Dict[str, Any]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "designer-install-probe-" + uuid.uuid4().hex,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": dict(arguments)},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        mcp_url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, timeout_secs)) as response:
            payload = _parse_streamable_response(response.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError, urllib.error.HTTPError):
        return {"success": False, "status": "probe_unreachable", "message": "Designer ping was unreachable."}
    if not isinstance(payload, dict):
        return {"success": False, "status": "probe_bad_response", "message": "Designer ping returned no result."}
    if payload.get("error"):
        return {"success": False, "status": "probe_failed", "message": "Designer ping returned an error."}
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return {"success": False, "status": "probe_failed", "message": "Designer ping reported an error."}
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return {"success": False, "status": "probe_bad_response", "message": "Designer ping had no structured result."}
    return {"success": True, "status": "probe_response", "result": structured}


def _probe_streamable_tool(mcp_url: str, timeout_secs: float) -> Dict[str, Any]:
    deadline = time.monotonic() + max(0.1, timeout_secs)
    called = _streamable_call(mcp_url, READINESS_TOOL, {}, timeout_secs)
    if not called.get("success"):
        return called
    result = called["result"]
    job_id = result.get("job_id")
    status = result.get("status")
    if not job_id or status not in {"pending", "running"}:
        return {"success": True, "status": "probe_ok", "result": result}
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        polled = _streamable_call(mcp_url, "jobs_get_status", {"job_id": job_id, "include_result": True}, remaining)
        if not polled.get("success"):
            return polled
        envelope = polled["result"]
        terminal = envelope.get("status")
        if terminal == "completed":
            return {"success": True, "status": "probe_ok", "result": envelope.get("result")}
        if terminal in {"failed", "cancelled", "interrupted"}:
            return {"success": False, "status": "probe_failed", "message": "Designer ping did not complete."}
        time.sleep(min(0.05, remaining))
    return {"success": False, "status": "probe_timeout", "message": "Designer ping timed out."}


def _probe_runtime_tool(mcp_url: str, timeout_secs: float) -> Dict[str, Any]:
    budget = max(0.1, min(float(timeout_secs), 30.0))
    deadline = time.monotonic() + budget
    parsed = urllib.parse.urlparse(mcp_url)
    hostname = parsed.hostname or ""
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = False
    if (
        parsed.scheme != "http"
        or not loopback
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or parsed.path.rstrip("/") != "/mcp"
    ):
        return {
            "success": False,
            "status": "probe_unsafe_url",
            "message": "Designer readiness requires an exact loopback HTTP MCP URL.",
        }
    probe = probe_sidecar_tool(mcp_url, READINESS_TOOL, timeout_secs=budget)
    if probe.get("status") == "probe_http_error" and probe.get("http_status") == 406:
        remaining = deadline - time.monotonic()
        if remaining < 0.1:
            return {"success": False, "status": "probe_timeout", "message": "Designer ping timed out."}
        return _probe_streamable_tool(mcp_url, remaining)
    return probe


def _probe_context(probe: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    result = probe.get("result")
    if not isinstance(result, dict):
        return None
    structured = result.get("structuredContent") or result.get("structured_content") or result
    if not isinstance(structured, dict) or structured.get("success") is not True:
        return None
    context = structured.get("context")
    return context if isinstance(context, dict) else None


def _identity_failure(reason: str) -> Tuple[Dict[str, Any], Sequence[Dict[str, Any]]]:
    return (
        {
            "directly_usable": False,
            "failure_stage": "readiness_identity",
            "failure_reason": reason,
            "probe_tool": READINESS_TOOL,
        },
        [],
    )


def _listener_belongs_to_runtime(listener: Optional[Mapping[str, Any]], host_pid: int, ctx: InstallContext) -> bool:
    if listener is None:
        return False
    try:
        owner_pid = int(listener.get("pid") or 0)
        parent_pid = int(listener.get("parent_pid") or 0)
        executable = Path(str(listener.get("executable") or ""))
        start_identity = str(listener.get("start_identity") or "")
    except (TypeError, ValueError):
        return False
    if not start_identity:
        return False
    if owner_pid == host_pid:
        return _same_path(executable, ctx.host_path)
    return (
        parent_pid == host_pid and ctx.server_binary_path is not None and _same_path(executable, ctx.server_binary_path)
    )


def _critical_entry(entry: Mapping[str, Any]) -> Optional[Tuple[str, str, str, str, int, str]]:
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        return None
    try:
        pid = int(metadata.get("dcc_pid") or entry.get("parent_pid") or entry.get("runtime_pid"))
    except (TypeError, ValueError):
        return None
    versions = entry.get("versions") if isinstance(entry.get("versions"), dict) else {}
    published_adapter_version = entry.get("adapter_version") or versions.get("adapter") or versions.get("server")
    identity = (
        str(entry.get("instance_id") or ""),
        str(entry.get("dcc_type") or ""),
        str(published_adapter_version or ""),
        str(entry.get("mcp_url") or ""),
        pid,
        str(metadata.get("dcc_version") or entry.get("version") or ""),
    )
    return identity if identity[0] and identity[3] and pid > 0 else None


def _live_entries(environ: Mapping[str, str]) -> Sequence[Mapping[str, Any]]:
    state = query_runtime_state(environ.get("DCC_MCP_REGISTRY_DIR"), dcc_type=DCC_TYPE, include_dead=False)
    entries = state.get("entries", [])
    return tuple(entry for entry in entries if isinstance(entry, dict) and entry.get("mcp_url"))


def verify(ctx: InstallContext, environ: Mapping[str, str]) -> Tuple[Dict[str, Any], Sequence[Dict[str, Any]]]:
    if not ctx.receipt_path.is_file():
        return (
            {"directly_usable": False, "failure_stage": "receipt", "failure_reason": "No Designer receipt exists."},
            [],
        )
    try:
        receipt = load_and_validate_receipt(ctx)
    except LifecycleFailure:
        return (
            {
                "directly_usable": False,
                "failure_stage": "receipt",
                "failure_reason": "Designer receipt or payload ownership is invalid.",
            },
            [],
        )
    try:
        query_python(ctx.python_path)
    except LifecycleFailure:
        return (
            {
                "directly_usable": False,
                "failure_stage": "import",
                "failure_reason": "Target interpreter provenance could not be revalidated.",
            },
            [],
        )
    installed_at = float(receipt.get("installed_at_epoch", 0.0))
    recent_logs = (
        [path for path in ctx.bootstrap_log_dir.glob("*.host-errors.log") if path.stat().st_mtime >= installed_at]
        if ctx.bootstrap_log_dir.is_dir()
        else []
    )
    if recent_logs:
        return (
            {
                "directly_usable": False,
                "failure_stage": "bootstrap",
                "failure_reason": "Designer captured a post-install startup error.",
            },
            [],
        )
    try:
        requested_timeout = float(environ.get("DCC_MCP_INSTALL_VERIFY_TIMEOUT", "2.0"))
    except (TypeError, ValueError):
        requested_timeout = 2.0
    deadline = time.monotonic() + max(0.1, min(requested_timeout, 30.0))
    entries = _live_entries(environ)
    if len(entries) != 1:
        reason = (
            "No live Designer adapter is registered."
            if not entries
            else "Multiple live Designer adapters are registered; stop all but the target instance."
        )
        return (
            {
                "directly_usable": False,
                "failure_stage": "readiness",
                "failure_reason": reason,
                "probe_tool": READINESS_TOOL,
            },
            _readiness_next_steps(ctx),
        )
    entry = entries[0]
    critical = _critical_entry(entry)
    if critical is None:
        return _identity_failure("Designer runtime identity metadata is unavailable.")
    instance_id, dcc_type, adapter_version, mcp_url, pid, dcc_version = critical
    if dcc_type != DCC_TYPE or adapter_version != __version__ or dcc_version != ctx.host_version:
        return _identity_failure("Designer registry identity does not match this install.")
    before = _observe_process_identity(pid)
    if before is None or not _same_path(Path(str(before.get("executable") or "")), ctx.host_path):
        return _identity_failure("Designer runtime executable identity does not match --dcc-path.")
    listener_before = _observe_listener_identity(mcp_url)
    if not _listener_belongs_to_runtime(listener_before, pid, ctx):
        return _identity_failure("Designer registry endpoint is not bound to the selected runtime tree.")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return _identity_failure("Designer identity verification exceeded its deadline.")
    probe = _probe_runtime_tool(mcp_url, remaining)
    if not probe.get("success"):
        return (
            {
                "directly_usable": False,
                "failure_stage": "readiness",
                "failure_reason": "Designer main-thread ping did not succeed.",
                "probe_tool": READINESS_TOOL,
            },
            _readiness_next_steps(ctx),
        )
    context = _probe_context(probe)
    after_entries = _live_entries(environ)
    after = _observe_process_identity(pid)
    listener_after = _observe_listener_identity(mcp_url)
    if (
        context is None
        or len(after_entries) != 1
        or _critical_entry(after_entries[0]) != critical
        or after is None
        or before.get("start_identity") != after.get("start_identity")
        or not _same_path(Path(str(after.get("executable") or "")), ctx.host_path)
        or listener_after != listener_before
        or not _listener_belongs_to_runtime(listener_after, pid, ctx)
    ):
        return _identity_failure("Designer runtime identity changed during verification.")
    expected_adapter = None if ctx.adapter_module_path is None else str(ctx.adapter_module_path)
    expected_core = None if ctx.core_module_path is None else str(ctx.core_module_path)
    core_version = version_tuple(context.get("core_version"))
    core_floor = version_tuple(MIN_CORE_VERSION)
    if (
        context.get("host_dispatch_ready") is not True
        or context.get("host") != DCC_TYPE
        or context.get("host_pid") != pid
        or context.get("instance_id") != instance_id
        or context.get("mcp_url") != mcp_url
        or context.get("version") != ctx.host_version
        or context.get("adapter_version") != __version__
        or core_version is None
        or core_floor is None
        or core_version < core_floor
        or context.get("process_start_identity") != before.get("start_identity")
        or not _same_path(Path(str(context.get("host_executable") or "")), ctx.host_path)
        or (
            expected_adapter is not None
            and not _same_path(Path(str(context.get("adapter_module_path") or "")), Path(expected_adapter))
        )
        or (
            expected_core is not None
            and not _same_path(Path(str(context.get("core_module_path") or "")), Path(expected_core))
        )
        or not _same_path(Path(str(context.get("bootstrap_module_path") or "")), ctx.plugin_path)
    ):
        return _identity_failure("Designer ping identity does not match the installed receipt.")
    return (
        {
            "directly_usable": True,
            "failure_stage": None,
            "failure_reason": None,
            "probe_tool": READINESS_TOOL,
        },
        [],
    )


__all__ = ["verify"]
