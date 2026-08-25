"""Embedded Substance 3D Designer MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from dcc_mcp_core import DccServerOptions, HostExecutionBridge
from dcc_mcp_core.server_base import DccServerBase

from dcc_mcp_substance3d_designer.__version__ import __version__

DEFAULT_PORT = 0
SERVER_NAME = "dcc-mcp-substance3d-designer"
_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_server: Optional["SubstanceDesignerMcpServer"] = None


class SubstanceDesignerMcpServer(DccServerBase):
    """DCC-MCP server hosted by a running Substance 3D Designer process."""

    def __init__(
        self,
        host_dispatcher: object,
        port: Optional[int] = None,
        *,
        enable_gateway_failover: bool = True,
    ) -> None:
        try:
            import sd  # Lazy import: provided by Designer.

            dcc_version = str(sd.getContext().getSDApplication().getVersion())
        except Exception:
            dcc_version = None
        options = DccServerOptions.from_env(
            "substance3d_designer",
            _SKILLS_DIR,
            port=port,
            server_name=SERVER_NAME,
            server_version=__version__,
            adapter_version=__version__,
            dcc_version=dcc_version,
            execution_bridge=HostExecutionBridge(dispatcher=host_dispatcher),
            enable_file_logging=True,
            enable_telemetry=True,
            enable_gateway_failover=enable_gateway_failover,
        )
        super().__init__(options=options)

    def register_builtin_actions(
        self,
        extra_skill_paths: Optional[list[str]] = None,
        include_bundled: bool = True,
        minimal_mode: Optional[Any] = None,
    ) -> None:
        """Register Core actions and keep the typed readiness probe loaded."""
        super().register_builtin_actions(
            extra_skill_paths=extra_skill_paths,
            include_bundled=include_bundled,
            minimal_mode=minimal_mode,
        )
        if not self.load_skill("designer-diagnostics"):
            raise RuntimeError("Designer diagnostics skill could not be loaded")

    def _version_string(self) -> str:
        try:
            import sd  # Lazy import: provided by Designer.

            return str(sd.getContext().getSDApplication().getVersion())
        except Exception:
            return "Substance 3D Designer"


def start_server(
    host_dispatcher: object,
    port: Optional[int] = None,
    *,
    enable_gateway_failover: bool = True,
) -> SubstanceDesignerMcpServer:
    """Start the singleton server after the host Qt dispatcher is installed."""
    global _server
    if _server is not None and _server.is_running:
        return _server
    _server = SubstanceDesignerMcpServer(
        host_dispatcher,
        port,
        enable_gateway_failover=enable_gateway_failover,
    )
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
