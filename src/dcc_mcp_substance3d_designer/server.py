"""Embedded Substance 3D Designer MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from dcc_mcp_core import DccServerOptions, HostExecutionBridge
from dcc_mcp_core.server_base import DccServerBase

from dcc_mcp_substance3d_designer.__version__ import __version__

DEFAULT_PORT = 0
SERVER_NAME = "dcc-mcp-substance3d-designer"
_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_server: Optional["SubstanceDesignerMcpServer"] = None


class SubstanceDesignerMcpServer(DccServerBase):
    """DCC-MCP server hosted by a running Substance 3D Designer process."""

    def __init__(self, host_dispatcher: object, port: Optional[int] = None) -> None:
        options = DccServerOptions.from_env(
            "substance3d_designer",
            _SKILLS_DIR,
            port=port,
            server_name=SERVER_NAME,
            server_version=__version__,
            execution_bridge=HostExecutionBridge(dispatcher=host_dispatcher),
            enable_file_logging=True,
            enable_telemetry=True,
        )
        super().__init__(options=options)

    def _version_string(self) -> str:
        try:
            import sd  # Lazy import: provided by Designer.

            return str(sd.getContext().getSDApplication().getVersion())
        except Exception:
            return "Substance 3D Designer"


def start_server(host_dispatcher: object, port: Optional[int] = None) -> SubstanceDesignerMcpServer:
    """Start the singleton server after the host Qt dispatcher is installed."""
    global _server
    if _server is not None and _server.is_running:
        return _server
    _server = SubstanceDesignerMcpServer(host_dispatcher, port)
    _server.register_builtin_actions()
    _server.start()
    return _server


def stop_server() -> None:
    global _server
    if _server is not None:
        _server.stop()
        _server = None


def get_server() -> Optional[SubstanceDesignerMcpServer]:
    return _server
