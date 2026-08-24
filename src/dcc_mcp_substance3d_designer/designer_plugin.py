"""Load this file from Substance 3D Designer's Plugin Manager."""

from dcc_mcp_substance3d_designer.designer.plugins.dcc_mcp_substance3d_designer_plugin import (
    initializeSDPlugin,
    uninitializeSDPlugin,
)

__all__ = ["initializeSDPlugin", "uninitializeSDPlugin"]
