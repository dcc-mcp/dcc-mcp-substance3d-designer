from __future__ import annotations

import json
import re
from pathlib import Path

import dcc_mcp_substance3d_designer as adapter

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_is_synchronized():
    manifest = json.loads(ROOT.joinpath(".release-please-manifest.json").read_text(encoding="utf-8"))
    version = re.search(r'(?m)^version = "([^"]+)"$', ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    assert version is not None
    assert version.group(1) == adapter.__version__ == manifest["."]


def test_plugin_and_skill_contract_files_exist():
    package = ROOT / "src" / "dcc_mcp_substance3d_designer"
    assert package.joinpath("designer_plugin.py").exists()
    assert package.joinpath("skills", "designer-session", "SKILL.md").exists()
    assert package.joinpath("skills", "designer-session", "tools.yaml").exists()


def test_start_server_defers_port_resolution_to_core(monkeypatch):
    from types import SimpleNamespace

    from dcc_mcp_substance3d_designer import server as server_module

    ports = []
    stub = SimpleNamespace(
        is_running=False,
        register_builtin_actions=lambda: None,
        start=lambda: None,
        stop=lambda: None,
    )

    monkeypatch.setattr(server_module, "_server", None)
    monkeypatch.setattr(
        server_module,
        "SubstanceDesignerMcpServer",
        lambda _dispatcher, port=None: ports.append(port) or stub,
    )
    monkeypatch.setenv("DCC_MCP_SUBSTANCE3D_DESIGNER_PORT", "8765")

    dispatcher = object()
    server_module.start_server(dispatcher, 0)
    server_module.stop_server()
    server_module.start_server(dispatcher)
    server_module.stop_server()

    assert ports == [0, None]
