from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parent.parent
    / "src"
    / "dcc_mcp_substance3d_designer"
    / "skills"
    / "designer-session"
    / "scripts"
    / "create_procedural_material.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("create_procedural_material", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identifier_is_normalized_for_designer_resources():
    module = _load_script()

    assert module._normalize_identifier("Signal Forge: Alloy 01") == "signal_forge_alloy_01"


def test_identifier_rejects_empty_values():
    module = _load_script()

    with pytest.raises(ValueError, match="letters or digits"):
        module._normalize_identifier("---")


def test_color_validation_enforces_rgb_unit_interval():
    module = _load_script()

    assert module._validate_color([0.1, 0.2, 0.3], "base") == (0.1, 0.2, 0.3)
    with pytest.raises(ValueError, match="between 0 and 1"):
        module._validate_color([0.1, 1.2, 0.3], "base")


def test_invalid_resolution_fails_before_importing_designer_sdk():
    result = _load_script().main(
        package_path="signal_forge.sbs",
        output_dir="textures",
        resolution=4096,
    )

    assert result["success"] is False
    assert "Unsupported Designer output resolution" in result["message"]


def test_unattended_designer_plugin_entrypoint_is_packaged():
    plugin = (
        Path(__file__).parent.parent
        / "src"
        / "dcc_mcp_substance3d_designer"
        / "designer"
        / "plugins"
        / "dcc_mcp_substance3d_designer_plugin.py"
    )

    source = plugin.read_text(encoding="utf-8")
    assert "initializeSDPlugin" in source
    assert "uninitializeSDPlugin" in source
