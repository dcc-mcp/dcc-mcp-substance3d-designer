"""Official Designer plugin activation for the receipted startup script."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def activate_plugin(plugin_path: str) -> None:
    import sd
    from sd.api.sdplugin import SDPluginStatus

    path = Path(plugin_path).resolve(strict=True)
    manager = sd.getContext().getSDApplication().getPluginMgr()
    available = manager.getPlugins()
    plugins = (
        []
        if available is None
        else (
            [available.getItem(index) for index in range(available.getSize())]
            if callable(getattr(available, "getSize", None))
            else list(available)
        )
    )
    owned = [
        item
        for item in plugins
        if item.getName() == path.stem
        and os.path.normcase(str(Path(item.getDirectory()).resolve())) == os.path.normcase(str(path.parent))
    ]
    if len(owned) > 1:
        raise RuntimeError("Designer adapter plugin discovery is ambiguous")
    if owned and owned[0].getStatus() == SDPluginStatus.Loaded:
        return
    # loadPlugin takes a native plugin name without the Python file extension.
    bytecode_policy = sys.dont_write_bytecode
    try:
        # Native loading imports the receipted module; cache files are not owned artifacts.
        sys.dont_write_bytecode = True
        plugin = manager.loadPlugin(path.stem, str(path.parent))
    finally:
        sys.dont_write_bytecode = bytecode_policy
    if plugin is None or plugin.getStatus() != SDPluginStatus.Loaded:
        detail = "No plugin returned" if plugin is None else plugin.getLastErrorMessage()
        raise RuntimeError(f"Designer adapter plugin activation failed: {detail}")
    if os.path.normcase(str(Path(plugin.getDirectory()).resolve())) != os.path.normcase(str(path.parent)):
        raise RuntimeError("Designer activated a plugin outside the receipted directory")


def run_startup(plugin_path: str) -> None:
    """Activate the adapter, then preserve the caller's explicit startup script."""
    try:
        activate_plugin(plugin_path)
    finally:
        user_script = os.environ.get("DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT")
        if user_script:
            runpy.run_path(user_script, run_name="__main__")
