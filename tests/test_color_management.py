from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_script():
    path = (
        Path(__file__).parent.parent
        / "src"
        / "dcc_mcp_substance3d_designer"
        / "skills"
        / "designer-session"
        / "scripts"
        / "inspect_session.py"
    )
    spec = importlib.util.spec_from_file_location("inspect_session", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inspect_session_reports_effective_ocio_config(monkeypatch, tmp_path):
    config = tmp_path / "config.ocio"
    config.write_text("ocio_profile_version: 2.4\n", encoding="utf-8")
    engine = SimpleNamespace(
        getName=lambda: "ocio",
        getWorkingColorSpaceName=lambda: "ACEScg",
        getRawColorSpaceName=lambda: "Raw",
        getOCIOConfigFileName=lambda: str(config),
    )
    app = SimpleNamespace(
        getVersion=lambda: "16.0.0",
        getUIMgr=lambda: SimpleNamespace(getCurrentGraph=lambda: None),
        getColorManagementEngine=lambda: engine,
    )
    sd = ModuleType("sd")
    sd.getContext = lambda: SimpleNamespace(getSDApplication=lambda: app)
    monkeypatch.setitem(sys.modules, "sd", sd)
    monkeypatch.setenv("OCIO", str(config))

    result = _load_script().main()

    assert result["success"] is True
    color_management = result["context"]["color_management"]
    assert color_management["mode"] == "ocio"
    assert color_management["working_space"] == "ACEScg"
    assert color_management["environment_path"] == str(config)
    assert len(color_management["config_sha256"]) == 64


def test_inspect_session_reports_adapter_lifecycle_health(monkeypatch):
    from dcc_mcp_substance3d_designer import plugin

    app = SimpleNamespace(
        getVersion=lambda: "16.0.0",
        getUIMgr=lambda: SimpleNamespace(getCurrentGraph=lambda: None),
        getColorManagementEngine=lambda: None,
    )
    sd = ModuleType("sd")
    sd.getContext = lambda: SimpleNamespace(getSDApplication=lambda: app)
    monkeypatch.setitem(sys.modules, "sd", sd)
    lifecycle = {
        "phase": "ready",
        "healthy": True,
        "dispatcher_installed": True,
        "server_running": True,
        "instance_id": "designer-instance",
        "failure": None,
    }
    monkeypatch.setattr(plugin, "get_lifecycle_status", lambda: lifecycle)

    result = _load_script().main()

    assert result["context"]["adapter_lifecycle"] == lifecycle
