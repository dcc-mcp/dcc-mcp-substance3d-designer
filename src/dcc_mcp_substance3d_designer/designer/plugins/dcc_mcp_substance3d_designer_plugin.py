"""Designer discovers this module from ``SBS_DESIGNER_PYTHON_PATH``."""

from dcc_mcp_core import capture_bootstrap_errors

from dcc_mcp_substance3d_designer.__version__ import __version__

_CAPTURE = {
    "dcc_name": "substance3d_designer",
    "adapter_version": __version__,
    "min_core_version": "0.20.8",
}

with capture_bootstrap_errors(phase="import", **_CAPTURE):
    from dcc_mcp_substance3d_designer.plugin import initializeSDPlugin as _initialize
    from dcc_mcp_substance3d_designer.plugin import uninitializeSDPlugin as _uninitialize


def initializeSDPlugin():
    with capture_bootstrap_errors(phase="startup", **_CAPTURE):
        return _initialize()


def uninitializeSDPlugin():
    with capture_bootstrap_errors(phase="shutdown", **_CAPTURE):
        return _uninitialize()


__all__ = ["initializeSDPlugin", "uninitializeSDPlugin"]
