"""Test artifact evidence and preservation of open packages independently of UI."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_evaluation as evaluation
from dcc_mcp_substance3d_designer import graph_resources as resources


@pytest.fixture
def export_host(monkeypatch):
    graph = SimpleNamespace(
        getUID=lambda: "graph-A",
        getIdentifier=lambda: "material",
        getOutputIdentifiers=lambda: ["basecolor", "roughness"],
        getPackage=lambda: object(),
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    monkeypatch.setattr(evaluation.shutil, "which", lambda name: "sbsrender.exe")
    exporter = SimpleNamespace(exportPackageToSBSAR=lambda package, path: Path(path).write_bytes(b"archive"))
    module = ModuleType("sd.api.sbs.sdsbsarexporter")
    module.SDSBSARExporter = SimpleNamespace(sNew=lambda: exporter)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return graph, exporter


def test_export_uses_archive_isolates_artifacts_and_passes_per_output_space(export_host, monkeypatch, tmp_path):
    calls = []

    def render(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 600
        archive = Path(command[command.index("--input") + 1])
        assert archive.suffix == ".sbsar" and archive.read_bytes() == b"archive"
        output = Path(command[command.index("--output-path") + 1])
        for identifier in ("basecolor", "roughness"):
            (output / f"{identifier}.png").write_bytes(b"fresh renderer output")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(evaluation.subprocess, "run", render)
    result = evaluation.export_maps(
        str(tmp_path), bit_depth="16", expected_graph_uid="graph-A", output_color_spaces={"basecolor": "sRGB"}
    )
    assert Path(result["output_dir"]).parent == tmp_path
    assert calls[0][-2:] == ["--set-output-colorspace", "basecolor@sRGB"]
    assert len(result["files"]) == 2 and all(len(item["sha256"]) == 64 for item in result["files"])
    second = evaluation.export_maps(str(tmp_path))
    assert second["output_dir"] != result["output_dir"]


@pytest.mark.parametrize(
    "mode,code",
    [
        ("archive", "SBSAR_EXPORT_FAILED"),
        ("missing", "MAP_OUTPUT_MISSING"),
        ("failed", "MAP_EXPORT_FAILED"),
        ("timeout", "MAP_EXPORT_TIMEOUT"),
    ],
)
def test_export_rejects_false_success_and_stale_files(export_host, monkeypatch, tmp_path, mode, code):
    (tmp_path / "basecolor.png").write_bytes(b"stale")
    (tmp_path / "roughness.png").write_bytes(b"stale")
    if mode == "archive":
        export_host[1].exportPackageToSBSAR = lambda *args: None

    def render(*args, **kwargs):
        if mode == "timeout":
            raise evaluation.subprocess.TimeoutExpired("sbsrender", 600)
        return SimpleNamespace(returncode=1 if mode == "failed" else 0)

    monkeypatch.setattr(evaluation.subprocess, "run", render)
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.export_maps(str(tmp_path))
    assert error.value.code == code


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({"image_format": "png", "bit_depth": "32f"}, "INVALID_EXPORT_FORMAT"),
        ({"output_color_spaces": {"absent": "Raw"}}, "INVALID_OUTPUT_OVERRIDE"),
        ({"expected_graph_uid": "other"}, "GRAPH_CONTEXT_CHANGED"),
    ],
)
def test_export_preflight_leaves_destination_absent(export_host, tmp_path, arguments, code):
    destination = tmp_path / "new"
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.export_maps(str(destination), **arguments)
    assert error.value.code == code
    assert not destination.exists()


def test_open_existing_dirty_package_does_not_reload(monkeypatch, tmp_path):
    path = tmp_path / "material.sbs"
    path.write_bytes(b"package")
    package = SimpleNamespace(isModified=lambda: True)

    def forbidden(*args):
        pytest.fail("Must not reload dirty package")

    monkeypatch.setattr(
        api,
        "package_manager",
        lambda: SimpleNamespace(getUserPackageFromFilePath=lambda path: package, loadUserPackage=forbidden),
    )
    assert resources.open_package(str(path)) == {"package_path": str(path), "saved": False, "already_open": True}


def test_close_dirty_package_preserves_edits(monkeypatch):
    monkeypatch.setattr(api, "active_package", lambda: SimpleNamespace(isModified=lambda: True, getFilePath=lambda: ""))
    with pytest.raises(api.GraphAuthoringError, match="Save the modified"):
        api.close_package()


def test_save_requires_file_not_only_sdk_ack(monkeypatch, tmp_path):
    path = tmp_path / "material.sbs"
    package = SimpleNamespace(isModified=lambda: False, getFilePath=lambda: str(path))
    monkeypatch.setattr(api, "active_package", lambda: package)
    monkeypatch.setattr(api, "package_manager", lambda: SimpleNamespace(savePackage=lambda package: True))
    with pytest.raises(api.GraphAuthoringError) as error:
        api.save_package()
    assert error.value.code == "PACKAGE_SAVE_FAILED"
    path.write_bytes(b"saved package")
    assert api.save_package()["saved"]


def test_save_as_refuses_other_package(monkeypatch, tmp_path):
    path = tmp_path / "other.sbs"
    path.write_bytes(b"other user data")
    monkeypatch.setattr(api, "active_package", lambda: SimpleNamespace(getFilePath=lambda: ""))
    with pytest.raises(api.GraphAuthoringError) as error:
        api.save_package_as(str(path))
    assert error.value.code == "PACKAGE_ALREADY_EXISTS"
    assert path.read_bytes() == b"other user data"


def test_sbsar_export_refuses_stale_destination(tmp_path):
    path = tmp_path / "existing.sbsar"
    path.write_bytes(b"old archive")
    with pytest.raises(api.GraphAuthoringError) as error:
        api.export_sbsar(str(path))
    assert error.value.code == "SBSAR_ALREADY_EXISTS"


def test_duplicate_output_rejected_before_node_creation(monkeypatch):
    monkeypatch.setattr(api, "active_graph", lambda: SimpleNamespace(getOutputIdentifiers=lambda: ["basecolor"]))
    with pytest.raises(api.GraphAuthoringError) as error:
        api.add_output("basecolor")
    assert error.value.code == "DUPLICATE_OUTPUT_ID"


def test_output_setup_failure_removes_new_node(monkeypatch):
    node = SimpleNamespace(
        getIdentifier=lambda: "100",
        setAnnotationPropertyValueFromId=lambda *args: None,
        getAnnotationPropertyValueFromId=lambda name: "wrong",
    )
    nodes = [node]
    graph = SimpleNamespace(
        getOutputIdentifiers=lambda: [], getNodes=lambda: nodes, deleteNode=lambda node: nodes.remove(node)
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    monkeypatch.setattr(api, "create_node", lambda *args: {"node_id": "100"})
    module = ModuleType("sd.api.sdvaluestring")
    module.SDValueString = SimpleNamespace(sNew=lambda value: value)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(api.GraphAuthoringError) as error:
        api.add_output("basecolor")
    assert error.value.code == "OUTPUT_IDENTIFIER_READBACK_FAILED" and nodes == []


def test_evaluation_requires_outputs_and_real_texture_dimensions(monkeypatch):
    module = ModuleType("sd.api.sdproperty")
    module.SDPropertyCategory = SimpleNamespace(Output="Output")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    calls, outputs = [], []
    graph = SimpleNamespace(
        getUID=lambda: "graph-A",
        getNodes=lambda: [1],
        getOutputNodes=lambda: outputs,
        compute=lambda: calls.append("compute"),
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.evaluate_graph("graph-A")
    assert error.value.code == "NO_GRAPH_OUTPUTS" and calls == []
    texture = SimpleNamespace(getSize=lambda: SimpleNamespace(x=1024, y=1024), getPixelFormat=lambda: "RGBA8")
    outputs.append(
        SimpleNamespace(
            getIdentifier=lambda: "100",
            getProperties=lambda category: [SimpleNamespace(getId=lambda: "out")],
            getPropertyValue=lambda prop: SimpleNamespace(get=lambda: texture),
        )
    )
    assert evaluation.evaluate_graph("graph-A")["outputs"][0]["width"] == 1024
    texture.getSize = lambda: SimpleNamespace(x=0, y=0)
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.evaluate_graph("graph-A")
    assert error.value.code == "OUTPUT_NOT_COMPUTED"
