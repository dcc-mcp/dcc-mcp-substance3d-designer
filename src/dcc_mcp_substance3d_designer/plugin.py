"""Designer plugin lifecycle entry points."""

from __future__ import annotations

from typing import Optional

from dcc_mcp_substance3d_designer.dispatcher import DesignerQtDispatcher
from dcc_mcp_substance3d_designer.server import start_server, stop_server

_dispatcher: Optional[DesignerQtDispatcher] = None


def initializeSDPlugin() -> None:
    """Start MCP when Designer loads this plugin."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = DesignerQtDispatcher()
        _dispatcher.install()
    start_server(_dispatcher)


def uninitializeSDPlugin() -> None:
    """Stop MCP and detach the Qt timer when Designer unloads this plugin."""
    global _dispatcher
    stop_server()
    if _dispatcher is not None:
        _dispatcher.uninstall()
        _dispatcher = None
