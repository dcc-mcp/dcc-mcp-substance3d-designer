"""Pure data contract for the Designer lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from dcc_mcp_core.deployment import INSTALL_EXIT_PREFLIGHT

DCC_TYPE = "substance3d_designer"
COMMAND = "dcc-mcp-substance3d-designer"
MIN_CORE_VERSION = "0.20.15"
MIN_DESIGNER_VERSION = (12, 1)
INSTALL_ROOT_ENV = "DCC_MCP_SUBSTANCE3D_DESIGNER_INSTALL_ROOT"
VERSION_ENV = "DCC_MCP_SUBSTANCE3D_DESIGNER_VERSION"
PYTHON_ENV = "DCC_MCP_INSTALL_PYTHON"
PLUGIN_NAME = "dcc_mcp_substance3d_designer_plugin.py"
READINESS_TOOL = "designer_diagnostics__ping"


@dataclass(frozen=True)
class InstallContext:
    host_path: Path
    host_version: str
    host_version_source: str
    embedded_python_version: str
    embedded_python_version_source: str
    python_path: Path
    python_version: str
    python_root: Path
    core_version: str
    install_root: Path
    receipt_path: Path
    launcher_path: Path
    payload_root: Path
    plugin_path: Path
    bootstrap_log_dir: Path
    state: str
    adapter_module_path: Optional[Path] = None
    core_module_path: Optional[Path] = None
    adapter_distribution_root: Optional[Path] = None
    core_distribution_root: Optional[Path] = None
    python_prefix: Optional[Path] = None
    server_module_path: Optional[Path] = None
    server_distribution_root: Optional[Path] = None
    server_binary_path: Optional[Path] = None


@dataclass(frozen=True)
class LifecycleOutcome:
    result: Dict[str, Any]
    exit_code: int


class LifecycleFailure(RuntimeError):
    def __init__(self, stage: str, message: str, exit_code: int = INSTALL_EXIT_PREFLIGHT) -> None:
        super().__init__(message)
        self.stage = stage
        self.exit_code = exit_code


__all__ = [
    "COMMAND",
    "DCC_TYPE",
    "INSTALL_ROOT_ENV",
    "InstallContext",
    "LifecycleFailure",
    "LifecycleOutcome",
    "MIN_CORE_VERSION",
    "MIN_DESIGNER_VERSION",
    "PLUGIN_NAME",
    "PYTHON_ENV",
    "READINESS_TOOL",
    "VERSION_ENV",
]
