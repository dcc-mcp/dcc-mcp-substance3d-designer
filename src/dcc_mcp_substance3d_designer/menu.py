"""Unified DCC MCP menu for Substance 3D Designer.

Provides Copy Instance ID, Server Info, and About DCC MCP menu actions
registered in Designer's menu bar, aligned with the unified menu structure
from Maya (PIP-2799) and Houdini (PIP-2796).
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from dcc_mcp_substance3d_designer.__version__ import __version__
from dcc_mcp_substance3d_designer.server import get_server

# Track menu references for cleanup.
_menu_ref: Optional[object] = None
_menu_actions: list = []


# ── Qt binding helpers ──────────────────────────────────────────────────────


def _get_qt_binding():
    """Return the available Qt binding module (PySide6 preferred, then PySide2)."""
    for name in ("PySide6", "PySide2"):
        try:
            mod = __import__(name)
            return mod
        except ImportError:
            continue
    return None


# ── main window discovery ───────────────────────────────────────────────────


def _find_main_window():
    """Locate the Substance Designer main window via Qt."""
    qt = _get_qt_binding()
    if qt is None:
        return None

    app = qt.QtWidgets.QApplication.instance()
    if app is None:
        return None

    # Designer uses a standard QMainWindow.
    for widget in app.topLevelWidgets():
        try:
            if isinstance(widget, qt.QtWidgets.QMainWindow) and widget.isVisible():
                return widget
        except Exception:
            continue
    return None


# ── instance ID resolution ──────────────────────────────────────────────────


def _resolve_instance_id() -> Optional[str]:
    """Extract the DCC MCP instance UUID from the running server."""
    server = get_server()
    if server is None:
        return None

    instance_id = None
    # Try direct attribute on the server wrapper.
    for attr in ("instance_id", "_server", "_config"):
        val = getattr(server, attr, None)
        if isinstance(val, str):
            instance_id = val
            break
        if hasattr(val, "instance_id"):
            instance_id = getattr(val, "instance_id", None)
            if isinstance(instance_id, str):
                break
    return instance_id or None


def _server_mcp_url() -> Optional[str]:
    """Resolve the MCP URL from the running server."""
    server = get_server()
    if server is None:
        return None
    try:
        if hasattr(server, "mcp_url"):
            return server.mcp_url  # DccServerBase property
    except Exception:
        pass
    return None


def _server_port() -> Optional[int]:
    """Resolve the server port from the running server."""
    server = get_server()
    if server is None:
        return None
    # Try server.port (internal handle), then _server.port, then _config.
    for attr in ("port", "_server", "_config"):
        val = getattr(server, attr, None)
        if isinstance(val, int) and attr == "port":
            return val
        if hasattr(val, "port"):
            p = getattr(val, "port", None)
            if isinstance(p, int):
                return p
    return None


# ── Designer version ─────────────────────────────────────────────────────────


def _designer_version() -> str:
    """Return the Substance 3D Designer version string."""
    try:
        import sd  # Lazy import: provided by Designer.

        return str(sd.getContext().getSDApplication().getVersion())
    except Exception:
        return "unknown"


# ── clipboard ────────────────────────────────────────────────────────────────


def _set_clipboard_text(text: str) -> None:
    """Set the system clipboard text, trying PySide6 then PySide2."""
    for name in ("PySide6", "PySide2"):
        try:
            mod = __import__(name)
            app = mod.QtWidgets.QApplication.instance()
            if app is not None:
                clipboard = app.clipboard()
                if clipboard is not None:
                    clipboard.setText(text)
                    return
        except Exception:
            continue
    raise RuntimeError("Unable to access system clipboard (no PySide binding available)")


# ── menu actions ─────────────────────────────────────────────────────────────


def _copy_instance_id() -> None:
    """Copy the DCC MCP instance UUID to the system clipboard."""
    instance_id = _resolve_instance_id()
    if not instance_id:
        _show_warning("Instance ID not available. Is the server running?")
        return
    try:
        _set_clipboard_text(instance_id)
    except RuntimeError:
        _show_warning("Unable to access system clipboard (no PySide binding available)")
        return
    print(f"DCC MCP: Instance ID copied to clipboard: {instance_id}")  # noqa: T201
    try:
        _show_status_message(f"Instance ID copied: {instance_id}")
    except Exception:
        pass


def _show_server_info() -> None:
    """Show server status information dialog."""
    instance_id = _resolve_instance_id()
    mcp_url = _server_mcp_url()
    port = _server_port()
    designer_version = _designer_version()

    gateway_port_str = os.environ.get("DCC_MCP_GATEWAY_PORT", "")
    gateway_display = gateway_port_str if gateway_port_str else "disabled"

    core_version = "unknown"
    try:
        from dcc_mcp_core.server_base import _package_version  # noqa: PLC0415

        core_version = _package_version() or "unknown"
    except Exception:
        pass

    lines = [
        "DCC MCP — Server Info",
        "",
        f"Instance UUID: {instance_id or 'N/A'}",
        f"DCC: Substance 3D Designer {designer_version}",
        f"PID: {os.getpid()}",
        f"MCP URL: {mcp_url or 'N/A'}",
        f"Server Port: {port or 'N/A'}",
        f"Gateway Port: {gateway_display}",
        f"Core Version: {core_version}",
        f"Adapter Version: {__version__}",
        f"Python: {sys.version.split()[0]}",
    ]
    _show_info_dialog("DCC MCP — Server Info", "\n".join(lines))


def _show_about() -> None:
    """Show about dialog with version information."""
    designer_version = _designer_version()
    lines = [
        f"dcc-mcp-substance3d-designer v{__version__}",
        f"Substance 3D Designer {designer_version}",
        f"Python {sys.version.split()[0]}",
        "",
        "DCC MCP — AI-driven DCC automation.",
        "https://github.com/dcc-mcp/dcc-mcp-substance3d-designer",
    ]
    _show_info_dialog("About DCC MCP", "\n".join(lines))


# ── UI helpers ───────────────────────────────────────────────────────────────


def _show_info_dialog(title: str, message: str) -> None:
    """Display an info dialog, falling back to print."""
    qt = _get_qt_binding()
    if qt is not None:
        try:
            qt.QtWidgets.QMessageBox.information(None, title, message)
            return
        except Exception:
            pass
    print(f"{title}\n{message}")  # noqa: T201


def _show_warning(message: str) -> None:
    """Display a warning, falling back to print."""
    qt = _get_qt_binding()
    if qt is not None:
        try:
            qt.QtWidgets.QMessageBox.warning(None, "DCC MCP", message)
            return
        except Exception:
            pass
    print(f"DCC MCP: {message}")  # noqa: T201


def _show_status_message(message: str) -> None:
    """Show a transient status message."""
    # Substance Designer does not expose a status bar API.
    # Use print as the primary feedback channel.
    print(f"DCC MCP: {message}")  # noqa: T201


# ── menu registration / deregistration ───────────────────────────────────────


def add_menu() -> None:
    """Add the unified DCC MCP menu to Designer's menu bar."""
    global _menu_ref, _menu_actions

    qt = _get_qt_binding()
    if qt is None:
        return

    main_window = _find_main_window()
    if main_window is None:
        return

    menu_bar = main_window.menuBar()
    if menu_bar is None:
        return

    try:
        dcc_menu = menu_bar.addMenu("DCC MCP")

        copy_action = qt.QtWidgets.QAction("Copy Instance ID", main_window)
        copy_action.triggered.connect(_copy_instance_id)
        dcc_menu.addAction(copy_action)
        _menu_actions.append(copy_action)

        info_action = qt.QtWidgets.QAction("Server Info", main_window)
        info_action.triggered.connect(_show_server_info)
        dcc_menu.addAction(info_action)
        _menu_actions.append(info_action)

        dcc_menu.addSeparator()

        about_action = qt.QtWidgets.QAction("About DCC MCP", main_window)
        about_action.triggered.connect(_show_about)
        dcc_menu.addAction(about_action)
        _menu_actions.append(about_action)

        _menu_ref = dcc_menu
    except Exception:
        pass


def remove_menu() -> None:
    """Remove the DCC MCP menu from Designer's menu bar."""
    global _menu_ref, _menu_actions

    if _menu_ref is not None:
        try:
            _menu_ref.clear()
            _menu_ref.deleteLater()
        except Exception:
            pass
        _menu_ref = None

    _menu_actions.clear()
