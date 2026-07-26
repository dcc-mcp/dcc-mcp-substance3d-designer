from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import menu


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _Action:
    def __init__(self, text: str, parent: object) -> None:
        self.text = text
        self.parent = parent
        self.triggered = _Signal()


class _Menu:
    def __init__(self) -> None:
        self.actions = []
        self.deleted = False

    def addAction(self, action) -> None:
        self.actions.append(action)

    def addSeparator(self) -> None:
        return None

    def clear(self) -> None:
        self.actions.clear()

    def deleteLater(self) -> None:
        self.deleted = True


class _MenuBar:
    def __init__(self) -> None:
        self.menu = _Menu()

    def addMenu(self, _title: str) -> _Menu:
        return self.menu


class _MainWindow:
    def __init__(self) -> None:
        self.menu_bar = _MenuBar()

    def menuBar(self) -> _MenuBar:
        return self.menu_bar


@pytest.mark.parametrize(
    "qt",
    [
        SimpleNamespace(QtGui=SimpleNamespace(QAction=_Action), QtWidgets=SimpleNamespace()),
        SimpleNamespace(QtGui=SimpleNamespace(), QtWidgets=SimpleNamespace(QAction=_Action)),
    ],
    ids=["pyside6-qtgui", "pyside2-qtwidgets"],
)
def test_add_menu_uses_binding_specific_qaction(monkeypatch, qt) -> None:
    main_window = _MainWindow()
    monkeypatch.setattr(menu, "_menu_ref", None)
    monkeypatch.setattr(menu, "_menu_actions", [])
    monkeypatch.setattr(menu, "_get_qt_binding", lambda: qt)
    monkeypatch.setattr(menu, "_find_main_window", lambda: main_window)

    menu.add_menu()

    actions = main_window.menu_bar.menu.actions
    assert [action.text for action in actions] == ["Copy Instance ID", "Server Info", "About DCC MCP"]
    assert [action.triggered.callback for action in actions] == [
        menu._copy_instance_id,
        menu._show_server_info,
        menu._show_about,
    ]


def test_add_menu_logs_registration_failure(monkeypatch, caplog) -> None:
    main_window = _MainWindow()

    def fail_to_add_menu(_title: str) -> _Menu:
        raise RuntimeError("boom")

    monkeypatch.setattr(menu, "_menu_ref", None)
    monkeypatch.setattr(menu, "_menu_actions", [])
    monkeypatch.setattr(
        menu,
        "_get_qt_binding",
        lambda: SimpleNamespace(QtGui=SimpleNamespace(QAction=_Action), QtWidgets=SimpleNamespace()),
    )
    monkeypatch.setattr(menu, "_find_main_window", lambda: main_window)
    monkeypatch.setattr(main_window.menu_bar, "addMenu", fail_to_add_menu)

    with caplog.at_level(logging.ERROR, logger=menu.__name__):
        menu.add_menu()

    assert "Failed to add the DCC MCP menu" in caplog.text
