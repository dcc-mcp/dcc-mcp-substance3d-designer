from __future__ import annotations

import logging
import sys
from types import ModuleType


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _NestedQtEventLoop:
    """Small Qt boundary that can pump timers while a modal loop is active."""

    def __init__(self) -> None:
        self.timers = []
        event_loop = self

        class QTimer:
            def __init__(self, *_args) -> None:
                self.timeout = _Signal()
                self.active = False
                self.single_shot = False
                event_loop.timers.append(self)

            def setInterval(self, _interval_ms: int) -> None:
                pass

            def setSingleShot(self, single_shot: bool) -> None:
                self.single_shot = single_shot

            def start(self, *_args) -> None:
                self.active = True

            def stop(self) -> None:
                self.active = False

        self.qtimer_type = QTimer

    def run_once(self) -> None:
        for timer in list(self.timers):
            if timer.active and timer.timeout.callback is not None:
                if timer.single_shot:
                    timer.active = False
                timer.timeout.callback()


def _install_fake_qt(monkeypatch) -> _NestedQtEventLoop:
    event_loop = _NestedQtEventLoop()
    qt_core = ModuleType("PySide6.QtCore")
    qt_core.QTimer = event_loop.qtimer_type
    monkeypatch.setitem(sys.modules, "PySide6", ModuleType("PySide6"))
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qt_core)
    monkeypatch.setitem(sys.modules, "PySide2", None)
    return event_loop


def test_startup_modal_nested_event_loop_can_run_registration(monkeypatch):
    from dcc_mcp_substance3d_designer import plugin

    event_loop = _install_fake_qt(monkeypatch)

    registrations = []
    monkeypatch.setattr(plugin, "_dispatcher", None)
    monkeypatch.setattr(plugin, "start_server", lambda dispatcher: registrations.append(dispatcher))
    monkeypatch.setattr(plugin, "add_menu", lambda: None)

    plugin.initializeSDPlugin()

    assert registrations == []

    # A QMessageBox.exec() nested loop still pumps Qt timers.
    event_loop.run_once()

    assert registrations == [plugin._dispatcher]


def test_startup_registration_failure_is_logged_without_escaping_qt(monkeypatch, caplog):
    from dcc_mcp_substance3d_designer import plugin

    event_loop = _install_fake_qt(monkeypatch)
    monkeypatch.setattr(plugin, "_dispatcher", None)
    monkeypatch.setattr(plugin, "add_menu", lambda: None)

    def fail_registration(_dispatcher) -> None:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(plugin, "start_server", fail_registration)
    plugin.initializeSDPlugin()

    with caplog.at_level(logging.ERROR, logger=plugin.__name__):
        event_loop.run_once()

    assert "registry unavailable" in caplog.text


def test_unload_cancels_registration_pending_in_the_qt_loop(monkeypatch):
    from dcc_mcp_substance3d_designer import plugin

    event_loop = _install_fake_qt(monkeypatch)

    registrations = []
    stops = []
    monkeypatch.setattr(plugin, "_dispatcher", None)
    monkeypatch.setattr(plugin, "start_server", lambda dispatcher: registrations.append(dispatcher))
    monkeypatch.setattr(plugin, "stop_server", lambda: stops.append(True))
    monkeypatch.setattr(plugin, "add_menu", lambda: None)
    monkeypatch.setattr(plugin, "remove_menu", lambda: None)

    plugin.initializeSDPlugin()
    plugin.uninitializeSDPlugin()
    event_loop.run_once()

    assert registrations == []
    assert stops == [True]
    assert plugin._dispatcher is None


def test_startup_registration_is_idempotent(monkeypatch):
    from dcc_mcp_substance3d_designer import plugin

    event_loop = _install_fake_qt(monkeypatch)

    registrations = []
    menus = []
    monkeypatch.setattr(plugin, "_dispatcher", None)
    monkeypatch.setattr(plugin, "start_server", lambda dispatcher: registrations.append(dispatcher))
    monkeypatch.setattr(plugin, "add_menu", lambda: menus.append(True))

    plugin.initializeSDPlugin()
    plugin.initializeSDPlugin()
    event_loop.run_once()
    plugin.initializeSDPlugin()
    event_loop.run_once()

    assert registrations == [plugin._dispatcher]
    assert menus == [True]
