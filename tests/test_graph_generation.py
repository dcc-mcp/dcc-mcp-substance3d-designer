"""Tests for the generated Designer skills that wrap existing typed primitives."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[1] / "src" / "dcc_mcp_substance3d_designer" / "skills"

SKILL_CONTRACTS = {
    "designer-effects": ["list_effect_recipes", "apply_effect"],
    "designer-lighting": ["list_light_recipes", "bake_lighting_maps"],
    "designer-plugins": ["list_node_modules", "describe_node_module", "module_capabilities"],
    "designer-particles": ["bake_variation_tiles", "compose_tile_atlas"],
    "designer-dynamics": ["bake_iteration_passes"],
    "designer-animation": ["list_animation_parameters", "bake_animation_frames"],
}


def load_script(skill: str, tool: str):
    path = SKILLS / skill / "scripts" / f"{tool}.py"
    assert path.is_file(), f"missing script for {skill}.{tool}"
    spec = importlib.util.spec_from_file_location(f"{skill}_{tool}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_tools(skill: str):
    return yaml.safe_load((SKILLS / skill / "tools.yaml").read_text(encoding="utf-8"))["tools"]


@pytest.mark.parametrize("skill", sorted(SKILL_CONTRACTS))
def test_skill_declares_expected_tools(skill):
    names = [tool["name"] for tool in load_tools(skill)]
    assert set(SKILL_CONTRACTS[skill]).issubset(names)


@pytest.mark.parametrize("skill", sorted(SKILL_CONTRACTS))
def test_skill_metadata_targets_designer(skill):
    frontmatter = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
    metadata = yaml.safe_load(frontmatter)["metadata"]["dcc-mcp"]
    assert metadata["dcc"] == "substance3d_designer"
    assert metadata["tools"] == "tools.yaml"
    assert metadata["tags"]


@pytest.mark.parametrize("skill", sorted(SKILL_CONTRACTS))
def test_declared_scripts_exist_and_are_importable(skill):
    for tool in load_tools(skill):
        source = (SKILLS / skill / tool["source_file"]).name
        assert (SKILLS / skill / "scripts" / source).is_file()
        module = load_script(skill, source[:-3])
        assert callable(module.main), f"{skill}.{tool['name']} must expose main()"


@pytest.mark.parametrize("skill", sorted(SKILL_CONTRACTS))
def test_skill_scripts_do_not_import_designer_host_api(skill):
    """Host APIs must stay lazy so metadata discovery is safe outside Designer."""
    for tool in load_tools(skill):
        source = (SKILLS / skill / "scripts" / (SKILLS / skill / tool["source_file"]).name).read_text(encoding="utf-8")
        body = [line for line in source.splitlines() if not line.strip().startswith("#")]
        for line in body:
            stripped = line.strip()
            assert not stripped.startswith("import sd") or "def " in stripped, (
                f"{skill}.{tool['name']} imports the Designer SDK at module scope"
            )
        assert "import sd" not in "\n".join(body).split("def ")[0]


@pytest.mark.parametrize(
    "skill, tool",
    [(skill, tool) for skill, tools in SKILL_CONTRACTS.items() for tool in tools],
)
def test_tools_declare_required_execution_fields(skill, tool):
    entry = next(item for item in load_tools(skill) if item["name"] == tool)
    assert entry["affinity"] == "main"
    assert entry["execution"] in {"sync", "async"}
    assert entry["source_file"].startswith("scripts/")
    assert entry["input_schema"]["type"] == "object"
    assert set(entry["output_schema"]["required"]) >= {"success", "message"}
    assert isinstance(entry["read_only"], bool) and isinstance(entry["destructive"], bool)
    assert "read_only_hint" in entry["annotations"] and "destructive_hint" in entry["annotations"]


@pytest.mark.parametrize(
    "skill, tool",
    [(skill, tool) for skill, tools in SKILL_CONTRACTS.items() for tool in tools],
)
def test_read_only_tools_never_announce_destruction(skill, tool):
    entry = next(item for item in load_tools(skill) if item["name"] == tool)
    if entry["read_only"]:
        assert entry["destructive"] is False
        assert entry["annotations"]["read_only_hint"] is True
        assert entry["annotations"]["destructive_hint"] is False


@pytest.mark.parametrize("skill", sorted(SKILL_CONTRACTS))
def test_recipe_skills_avoid_hardcoded_designer_versions(skill):
    """Skills ride the adapter version; no exact SDK version assertions."""
    for tool in load_tools(skill):
        blob = (SKILLS / skill / "scripts" / (SKILLS / skill / tool["source_file"]).name).read_text(encoding="utf-8")
        assert "getVersion" not in blob


def test_generated_scripts_route_through_existing_primitives():
    """New skills must reuse the adapter's verified modules, not reimplement them."""
    # Each skill routes through the adapter package rather than reimplementing
    # host logic inside the script.
    allowed = {"graph_effects", "graph_lighting", "graph_modules", "graph_series", "graph_recipes"}
    for skill in SKILL_CONTRACTS:
        for tool in load_tools(skill):
            name = (SKILLS / skill / tool["source_file"]).name
            source = (SKILLS / skill / "scripts" / name).read_text(encoding="utf-8")
            assert "dcc_mcp_substance3d_designer." in source, f"{skill}.{tool['name']}"
            imported = {
                line.split("dcc_mcp_substance3d_designer.")[1].split()[0]
                for line in source.splitlines()
                if "dcc_mcp_substance3d_designer." in line
            }
            assert imported & allowed, f"{skill}.{tool['name']} imports no adapter module"
            assert "skill_support import typed_result" in source


@pytest.mark.parametrize(
    "skill, tool",
    [(skill, tool) for skill, tools in SKILL_CONTRACTS.items() for tool in tools],
)
def test_skill_tool_main_rejects_empty_arguments_without_host(skill, tool, monkeypatch):
    """Calling main() with no arguments must fail closed without touching the host."""
    module = load_script(skill, tool)
    called = []
    monkeypatch.setattr(module, "typed_result", lambda *args: called.append(args))
    result = module.main()
    if called:
        assert called[0][0]
        return
    assert result["success"] is False
    assert result["error"]
    # Failing closed must not require the Designer host module to be imported.
    assert "sd" not in sys.modules
