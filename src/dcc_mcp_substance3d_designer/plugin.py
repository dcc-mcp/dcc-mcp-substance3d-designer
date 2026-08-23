"""Designer plugin lifecycle entry points."""

from __future__ import annotations

import logging
from typing import Optional

from dcc_mcp_substance3d_designer.dispatcher import DesignerQtDispatcher
from dcc_mcp_substance3d_designer.menu import add_menu, remove_menu
from dcc_mcp_substance3d_designer.server import start_server, stop_server

logger = logging.getLogger(__name__)
_dispatcher: Optional[DesignerQtDispatcher] = None


def initializeSDPlugin() -> None:
    """Start MCP when Designer loads this plugin."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = DesignerQtDispatcher()
        _dispatcher.install()
    dispatcher = _dispatcher

    def start_plugin() -> None:
        try:
            start_server(dispatcher)
            add_menu()
        except Exception:
            logger.exception("Failed to start the DCC MCP Designer adapter")

    dispatcher.schedule_startup(start_plugin)


def uninitializeSDPlugin() -> None:
    """Stop MCP and detach the Qt timer when Designer unloads this plugin."""
    global _dispatcher
    remove_menu()
    stop_server()
    if _dispatcher is not None:
        _dispatcher.uninstall()
        _dispatcher = None
