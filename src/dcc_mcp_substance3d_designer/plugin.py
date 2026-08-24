"""Designer plugin lifecycle entry points."""

from __future__ import annotations

import logging
from typing import Optional

from dcc_mcp_substance3d_designer.dispatcher import DesignerQtDispatcher
from dcc_mcp_substance3d_designer.menu import add_menu, remove_menu
from dcc_mcp_substance3d_designer.server import get_server, start_server, stop_server

logger = logging.getLogger(__name__)
_dispatcher: Optional[DesignerQtDispatcher] = None
_startup_phase = "stopped"
_startup_failure: Optional[dict[str, str]] = None


def get_lifecycle_status() -> dict[str, object]:
    """Return a redacted snapshot of the embedded adapter lifecycle."""
    server = get_server()
    dispatcher_installed = bool(_dispatcher is not None and _dispatcher.is_installed)
    server_running = bool(server is not None and server.is_running)
    instance_id = getattr(server, "instance_id", None) if server_running else None
    return {
        "phase": _startup_phase,
        "healthy": _startup_phase == "ready" and dispatcher_installed and server_running and bool(instance_id),
        "dispatcher_installed": dispatcher_installed,
        "server_running": server_running,
        "instance_id": str(instance_id) if instance_id else None,
        "failure": dict(_startup_failure) if _startup_failure else None,
    }


def initializeSDPlugin() -> None:
    """Start MCP when Designer loads this plugin."""
    global _dispatcher, _startup_failure, _startup_phase
    dispatcher_created = _dispatcher is None
    if _dispatcher is None:
        _dispatcher = DesignerQtDispatcher()
        _dispatcher.install()
    if not dispatcher_created and _startup_phase in {"scheduled", "starting", "ready", "failed"}:
        return
    dispatcher = _dispatcher
    _startup_phase = "scheduled"
    _startup_failure = None

    def start_plugin() -> None:
        global _startup_failure, _startup_phase
        stage = "server_start"
        _startup_phase = "starting"
        try:
            start_server(dispatcher)
            stage = "menu_registration"
            add_menu()
            _startup_phase = "ready"
        except Exception as exc:
            _startup_phase = "failed"
            _startup_failure = {"stage": stage, "kind": type(exc).__name__}
            logger.exception("Failed to start the DCC MCP Designer adapter")

    dispatcher.schedule_startup(start_plugin)


def uninitializeSDPlugin() -> None:
    """Stop MCP and detach the Qt timer when Designer unloads this plugin."""
    global _dispatcher, _startup_failure, _startup_phase
    _startup_phase = "stopping"
    remove_menu()
    stop_server()
    if _dispatcher is not None:
        _dispatcher.uninstall()
        _dispatcher = None
    _startup_phase = "stopped"
    _startup_failure = None
