"""Fail-closed Designer receipt, bootstrap, registry, and typed-tool verification."""

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
from typing import Any, Dict, Mapping, Sequence, Tuple

from dcc_mcp_core import probe_sidecar_tool, query_runtime_state

from dcc_mcp_substance3d_designer._install_io import hash_file, load_json
from dcc_mcp_substance3d_designer._install_model import (
    DCC_TYPE,
    READINESS_TOOL,
    InstallContext,
    LifecycleFailure,
)
from dcc_mcp_substance3d_designer._install_preflight import query_python


def _launcher_command(ctx: InstallContext) -> Sequence[str]:
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(ctx.launcher_path)]
    return [str(ctx.launcher_path)]


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
    request_id = "designer-install-probe-" + uuid.uuid4().hex
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
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
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        return {"success": False, "status": "probe_unreachable", "message": str(exc)}
    if not isinstance(payload, dict):
        return {
            "success": False,
            "status": "probe_bad_response",
            "message": "Probe returned no JSON-RPC result.",
        }
    if payload.get("error"):
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        return {"success": False, "status": "probe_failed", "message": str(message)}
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("isError") is True:
        return {
            "success": False,
            "status": "probe_failed",
            "message": "Designer probe reported an error.",
        }
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return {
            "success": False,
            "status": "probe_bad_response",
            "message": "Probe returned no structured result.",
        }
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
        polled = _streamable_call(
            mcp_url,
            "jobs_get_status",
            {"job_id": job_id, "include_result": True},
            remaining,
        )
        if not polled.get("success"):
            return polled
        envelope = polled["result"]
        terminal = envelope.get("status")
        if terminal == "completed":
            return {"success": True, "status": "probe_ok", "result": envelope.get("result")}
        if terminal in {"failed", "cancelled", "interrupted"}:
            return {
                "success": False,
                "status": f"probe_{terminal}",
                "message": str(envelope.get("error") or f"Designer probe {terminal}."),
            }
        time.sleep(min(0.05, remaining))
    return {
        "success": False,
        "status": "probe_timeout",
        "message": "Designer probe did not reach a terminal state.",
    }


def _probe_runtime_tool(mcp_url: str, timeout_secs: float) -> Dict[str, Any]:
    parsed = urllib.parse.urlparse(mcp_url)
    hostname = parsed.hostname or ""
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname.lower() == "localhost"
    if parsed.scheme != "http" or not is_loopback:
        return {
            "success": False,
            "status": "probe_unsafe_url",
            "message": "Designer readiness probes require a loopback HTTP registry URL.",
        }
    probe = probe_sidecar_tool(mcp_url, READINESS_TOOL, timeout_secs=timeout_secs)
    if probe.get("status") == "probe_http_error" and probe.get("http_status") == 406:
        return _probe_streamable_tool(mcp_url, timeout_secs)
    return probe


def verify(ctx: InstallContext, environ: Mapping[str, str]) -> Tuple[Dict[str, Any], Sequence[Dict[str, Any]]]:
    if not ctx.receipt_path.is_file():
        return (
            {
                "directly_usable": False,
                "failure_stage": "receipt",
                "failure_reason": "No Designer install receipt exists.",
            },
            [],
        )
    receipt = load_json(ctx.receipt_path)
    for item in receipt.get("files", []):
        path = Path(str(item.get("path", "")))
        if not path.is_file() or hash_file(path) != item.get("sha256"):
            return (
                {
                    "directly_usable": False,
                    "failure_stage": "artifact",
                    "failure_reason": f"Receipted Designer artifact is missing or changed: {path}",
                },
                [],
            )
    try:
        query_python(ctx.python_path)
    except LifecycleFailure as exc:
        return (
            {"directly_usable": False, "failure_stage": "import", "failure_reason": str(exc)},
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
                "failure_reason": f"Designer captured a startup error in {recent_logs[-1]}",
            },
            [],
        )
    runtime_state = query_runtime_state(environ.get("DCC_MCP_REGISTRY_DIR"), dcc_type=DCC_TYPE, include_dead=False)
    entries = [entry for entry in runtime_state.get("entries", []) if entry.get("mcp_url")]
    failure_reason = "No live Designer adapter is registered."
    if len(entries) == 1:
        timeout = max(0.1, float(environ.get("DCC_MCP_INSTALL_VERIFY_TIMEOUT", "2.0")))
        probe = _probe_runtime_tool(str(entries[0]["mcp_url"]), timeout)
        if probe.get("success"):
            return (
                {
                    "directly_usable": True,
                    "failure_stage": None,
                    "failure_reason": None,
                    "probe_tool": READINESS_TOOL,
                },
                [],
            )
        failure_reason = str(probe.get("message") or probe.get("reason") or "Designer readiness probe failed.")
    elif len(entries) > 1:
        failure_reason = "Multiple live Designer adapters are registered; select one target instance."
    return (
        {
            "directly_usable": False,
            "failure_stage": "readiness",
            "failure_reason": failure_reason,
            "probe_tool": READINESS_TOOL,
        },
        [
            {
                "id": "launch_designer",
                "description": "Launch Designer through the receipted adapter launcher.",
                "command": list(_launcher_command(ctx)),
                "why": "Designer reads its plugin and Python paths only when the host process starts.",
            }
        ],
    )


__all__ = ["verify"]
