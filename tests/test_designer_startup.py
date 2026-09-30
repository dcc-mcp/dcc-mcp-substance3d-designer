"""Startup uses official SDK activation and preserves caller-owned scripts."""

import os
import sys
from enum import Enum
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import _launch, _startup


class Status(Enum):
    Loaded = 0
    Unloaded = 1
    LoadFailed = 2


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    path = tmp_path / "plugins" / "adapter.py"
    path.parent.mkdir()
    path.write_text("# adapter")
    plugin = SimpleNamespace(
        getName=lambda: "adapter",
        getDirectory=lambda: str(path.parent),
        getStatus=lambda: Status.Loaded,
        getLastErrorMessage=lambda: "native failure",
    )
    calls = []
    manager = SimpleNamespace(getPlugins=lambda: [], loadPlugin=lambda *args: calls.append(args) or plugin)
    module = ModuleType("sd")
    module.getContext = lambda: SimpleNamespace(getSDApplication=lambda: SimpleNamespace(getPluginMgr=lambda: manager))
    monkeypatch.setitem(sys.modules, "sd", module)
    statuses = ModuleType("sd.api.sdplugin")
    statuses.SDPluginStatus = Status
    monkeypatch.setitem(sys.modules, statuses.__name__, statuses)
    return path, plugin, manager, calls


def test_activation_uses_native_name_directory_and_loaded_status(sdk):
    path, _, _, calls = sdk
    _startup.activate_plugin(str(path))
    assert calls == [("adapter", str(path.parent))]


def test_already_loaded_owned_plugin_is_not_reloaded(sdk):
    path, plugin, manager, calls = sdk
    manager.getPlugins = lambda: SimpleNamespace(getSize=lambda: 1, getItem=lambda index: plugin)
    _startup.activate_plugin(str(path))
    assert calls == []


@pytest.mark.parametrize("mode", ["none", "failed", "foreign", "ambiguous"])
def test_activation_does_not_accept_unproven_plugin(sdk, mode):
    path, plugin, manager, _ = sdk
    if mode == "none":
        manager.loadPlugin = lambda *args: None
    elif mode == "failed":
        plugin.getStatus = lambda: Status.LoadFailed
    elif mode == "foreign":
        plugin.getDirectory = lambda: str(path.parent / "foreign")
    else:
        manager.getPlugins = lambda: [plugin, plugin]
    with pytest.raises(RuntimeError):
        _startup.activate_plugin(str(path))


@pytest.mark.parametrize("failed", [False, True])
def test_user_startup_script_is_preserved_after_activation(monkeypatch, tmp_path, failed):
    script = tmp_path / "user.py"
    script.write_text("# user script")
    monkeypatch.setenv("DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT", str(script))
    order = []

    def activate(path):
        order.append("adapter")
        if failed:
            raise RuntimeError("activation failed")

    monkeypatch.setattr(_startup, "activate_plugin", activate)
    monkeypatch.setattr(_startup.runpy, "run_path", lambda path, run_name: order.append((path, run_name)))
    if failed:
        with pytest.raises(RuntimeError, match="activation failed"):
            _startup.run_startup("owned.py")
    else:
        _startup.run_startup("owned.py")
    assert order == ["adapter", (str(script), "__main__")]


@pytest.mark.parametrize("equals", [False, True])
def test_launcher_composes_startup_and_preserves_arguments_environment(monkeypatch, tmp_path, equals):
    script = tmp_path / "user with spaces.py"
    script.write_text("# user")
    monkeypatch.setenv("DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT", "stale")
    monkeypatch.setenv("SBS_DESIGNER_PYTHON_PATH", "existing-plugins")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(_launch.subprocess, "run", run)
    custom = ["--startup-script=" + str(script)] if equals else ["--startup-script", str(script)]
    assert _launch.launch("host.exe", "owned-startup.py", ["--config-file", "owned.sbscfg", *custom, "--quit"]) == 7
    command, options = calls[0]
    assert command == ["host.exe", "--startup-script", "owned-startup.py", "--config-file", "owned.sbscfg", "--quit"]
    assert options["env"]["DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT"] == str(script)
    assert options["env"]["SBS_DESIGNER_PYTHON_PATH"] == "existing-plugins"
    assert os.environ["DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT"] == "stale"


@pytest.mark.parametrize("arguments", [["--startup-script"], ["--startup-script", "--quit"], ["--startup-script="]])
def test_missing_startup_argument_fails_before_host_launch(monkeypatch, arguments):
    monkeypatch.setattr(_launch.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not launch host"))
    with pytest.raises(ValueError):
        _launch.launch("host.exe", "owned.py", arguments)


def test_duplicate_startup_argument_fails_before_host_launch(monkeypatch, tmp_path):
    path = tmp_path / "user.py"
    path.write_text("# user")
    monkeypatch.setattr(_launch.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not launch host"))
    with pytest.raises(ValueError, match="only one"):
        _launch.launch("host.exe", "owned.py", ["--startup-script", str(path), "--startup-script=" + str(path)])


def test_launcher_drops_stale_composition_environment(monkeypatch):
    monkeypatch.setenv("DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT", "stale")
    monkeypatch.setattr(
        _launch.subprocess,
        "run",
        lambda command, **options: SimpleNamespace(
            returncode=int("DCC_MCP_DESIGNER_USER_STARTUP_SCRIPT" in options["env"])
        ),
    )
    assert _launch.main(["--host", "host.exe", "--startup", "owned.py", "--", "file.sbs"]) == 0


def test_native_end_of_options_preserves_positional_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        _launch.subprocess,
        "run",
        lambda command, **options: calls.append(command) or SimpleNamespace(returncode=0),
    )
    assert _launch.launch("host.exe", "owned.py", ["--", "--startup-script", "literal-filename"]) == 0
    assert calls == [["host.exe", "--startup-script", "owned.py", "--", "--startup-script", "literal-filename"]]
