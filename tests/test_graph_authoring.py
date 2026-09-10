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
IMPORTED_SCRIPT = SCRIPT.with_name("create_imported_pbr_material.py")


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


def test_imported_material_rejects_missing_sources_before_designer_sdk():
    spec = importlib.util.spec_from_file_location("create_imported_pbr_material", IMPORTED_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.main(
        package_path="captured.sbs",
        output_dir="textures",
        base_color_path="missing_base.png",
        normal_path="missing_normal.png",
        packed_rmas_path="missing_rmas.png",
    )

    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_imported_material_supports_common_packed_channel_layouts():
    spec = importlib.util.spec_from_file_location("create_imported_pbr_material", IMPORTED_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._packed_outputs("RMA") == {
        "Roughness": "R",
        "Metallic": "G",
        "AmbientOcclusion": "B",
    }
    assert module._packed_outputs("arm") == {
        "AmbientOcclusion": "R",
        "Roughness": "G",
        "Metallic": "B",
    }


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


@pytest.mark.parametrize("layout", ["separate", "ARM", "RMA"])
@pytest.mark.parametrize("embed", [False, True])
@pytest.mark.parametrize("failed_save", [None, "package", "map"])
def test_imported_pbr_graph_routes_channels_and_optional_height(tmp_path, monkeypatch, layout, embed, failed_save):
    import sys
    from types import ModuleType, SimpleNamespace
    from unittest.mock import MagicMock

    spec = importlib.util.spec_from_file_location("imported", IMPORTED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    texture = tmp_path / "source.png"
    texture.write_bytes(b"source")
    inputs = {"base_color_path": str(texture), "normal_path": str(texture), "height_path": str(texture)}
    if layout == "separate":
        inputs.update(roughness_path=str(texture), metallic_path=str(texture), ambient_occlusion_path=str(texture))
    else:
        inputs.update(packed_rmas_path=str(texture), packed_channel_layout=layout)
    sources, outputs = [], []

    def make_node(*_args):
        node = MagicMock()
        node.getProperties.return_value = [SimpleNamespace(getId=lambda: "out")]
        node.getPropertyValueFromId.return_value.get.return_value.save.side_effect = lambda path: (
            False if failed_save == "map" else Path(path).write_bytes(b"rendered")
        )
        return node

    def source_node(*args):
        node = make_node()
        sources.append(node)
        return node

    def output_node(*args):
        node = make_node()
        outputs.append(node)
        return node

    graph = MagicMock()
    graph.newInstanceNode.side_effect = source_node
    graph.newNode.side_effect = output_node
    manager = MagicMock()
    application = MagicMock()
    application.getPackageMgr.return_value = manager
    application.getPath.return_value = str(tmp_path)
    manager.savePackageAs.side_effect = lambda package, path: (
        False if failed_save == "package" else Path(path).write_bytes(b"sbs")
    )
    sd = ModuleType("sd")
    sd.getContext = lambda: SimpleNamespace(getSDApplication=lambda: application)
    monkeypatch.setitem(sys.modules, "sd", sd)
    bitmap = MagicMock()
    members = {
        "sd.api.sbs.sdsbscompgraph": {"SDSBSCompGraph": SimpleNamespace(sNew=lambda _: graph)},
        "sd.api.sdapplication": {"SDApplicationPath": SimpleNamespace(DefaultResourcesDir=1)},
        "sd.api.sdbasetypes": {"float2": lambda x, y: (x, y)},
        "sd.api.sdproperty": {"SDPropertyCategory": SimpleNamespace(Output=1)},
        "sd.api.sdresource": {"EmbedMethod": SimpleNamespace(Linked="linked", Embedded="embedded")},
        "sd.api.sdresourcebitmap": {"SDResourceBitmap": bitmap},
        "sd.api.sdtypeusage": {"SDTypeUsage": SimpleNamespace(sNew=lambda: None)},
        "sd.api.sdvaluearray": {"SDValueArray": SimpleNamespace(sNew=lambda *_: MagicMock())},
        "sd.api.sdvalueusage": {
            "SDUsage": SimpleNamespace(sNew=lambda *args: args),
            "SDValueUsage": SimpleNamespace(sNew=lambda value: value),
        },
        "sd.ui.graphgrid": {"GraphGrid": SimpleNamespace(sGetFirstLevelSize=lambda: 32)},
    }
    for name, attributes in members.items():
        fake = ModuleType(name)
        fake.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, fake)
    result = module.main(
        package_path=str(tmp_path / "material.sbs"),
        output_dir=str(tmp_path / "maps"),
        embed_resources=embed,
        open_in_editor=False,
        **inputs,
    )
    if failed_save:
        assert result["success"] is False
        assert ("PACKAGE_SAVE_FAILED" if failed_save == "package" else "MAP_SAVE_FAILED") in result["error"]
        return
    assert result["success"] is True
    assert len(outputs) == 6
    assert all(Path(path).read_bytes() == b"rendered" for path in result["context"]["texture_files"].values())
    assert {out.setAnnotationPropertyValueFromId.call_args.args[1].pushBack.call_args.args[0] for out in outputs} == {
        ("baseColor", "RGBA", "sRGB"),
        ("normal", "RGBA", "Raw"),
        ("roughness", "L", "Raw"),
        ("metallic", "L", "Raw"),
        ("ambientOcclusion", "L", "Raw"),
        ("height", "L", "Raw"),
    }
    assert all(call.args[2] == ("embedded" if embed else "linked") for call in bitmap.sNewFromFile.call_args_list)
    if layout == "separate":
        manager.loadUserPackage.assert_not_called()
        assert all(node.newPropertyConnectionFromId.call_count == 1 for node in sources)
    else:
        split = sources[-1]
        assert {call.args[0] for call in split.newPropertyConnectionFromId.call_args_list} == {"R", "G", "B"}
    application.getUIMgr.assert_not_called()


@pytest.mark.parametrize(
    "extra, message",
    [
        ({}, "require roughness_path and metallic_path"),
        ({"packed_rmas_path": "source", "roughness_path": "source"}, "not both"),
        (
            {"roughness_path": "source", "metallic_path": "source", "height_path": "missing"},
            "height_path does not exist",
        ),
    ],
)
def test_separate_pbr_rejects_invalid_inputs_without_host_mutation(tmp_path, extra, message):
    spec = importlib.util.spec_from_file_location("imported", IMPORTED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    texture = tmp_path / "source.png"
    texture.write_bytes(b"source")
    extra = {key: str(texture) if value == "source" else str(tmp_path / value) for key, value in extra.items()}
    result = module.main(
        package_path=str(tmp_path / "new" / "material.sbs"),
        output_dir=str(tmp_path / "maps"),
        base_color_path=str(texture),
        normal_path=str(texture),
        **extra,
    )
    assert result["success"] is False
    assert message in result["error"]
    assert not (tmp_path / "new").exists()
    assert not (tmp_path / "maps").exists()
