"""A failed native export must be diagnosable and retryable at the same path."""

import hashlib
import struct
import sys
import zlib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_evaluation as evaluation


def png_header(width=8):
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">IIBBBBB", width, 8, 16, 0, 0, 0, 0)
    return header + struct.pack(">I", zlib.crc32(header[12:]))


@pytest.fixture
def native_host(monkeypatch):
    module = ModuleType("sd.api.sdproperty")
    module.SDPropertyCategory = SimpleNamespace(Output="Output")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    textures, nodes = [], []
    for index in range(2):
        texture = SimpleNamespace(
            getSize=lambda: SimpleNamespace(x=8, y=8),
            getPixelFormat=lambda: SimpleNamespace(name="LUM16"),
            save=lambda path: Path(path).write_bytes(png_header()),
        )
        textures.append(texture)
        prop = SimpleNamespace(getId=lambda: "output")
        nodes.append(
            SimpleNamespace(
                getIdentifier=lambda index=index: str(index),
                getPropertyFromId=lambda *args, prop=prop: prop,
                getPropertyValue=lambda prop, index=index: SimpleNamespace(get=lambda: textures[index]),
            )
        )
    graph = SimpleNamespace(getUID=lambda: "graph-A", getNodes=lambda: nodes)
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    monkeypatch.setattr(evaluation, "evaluate_graph", lambda *args: {})
    return textures


OUTPUTS = [
    {"name": "height", "node_id": "0", "property": "output"},
    {"name": "roughness", "node_id": "1", "property": "output"},
]


@pytest.mark.parametrize(
    "failure,code",
    [("missing", "OUTPUT_NOT_COMPUTED"), ("save", "MAP_OUTPUT_MISSING"), ("dimensions", "MAP_HEADER_INVALID")],
)
def test_failure_does_not_publish_partial_files_and_same_path_can_retry(native_host, tmp_path, failure, code):
    destination = tmp_path / "maps"
    second = native_host[1]
    if failure == "missing":
        native_host[1] = None
    elif failure == "save":
        second.save = lambda path: False
    else:
        second.save = lambda path: Path(path).write_bytes(png_header(width=4))
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.export_native_maps(str(destination), OUTPUTS, "graph-A")
    assert error.value.code == code
    if failure == "missing":
        assert "roughness (1.output)" in str(error.value)
        assert "graph output node" in str(error.value)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
    native_host[1] = second
    second.save = lambda path: Path(path).write_bytes(png_header())
    result = evaluation.export_native_maps(str(destination), OUTPUTS, "graph-A")
    assert len(result["files"]) == 2
    for item in result["files"]:
        assert Path(item["path"]).parent == destination
        assert item["pixel_format"] == "LUM16"
        assert item["property"] == "output"
        assert item["sha256"] == hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()


def test_destination_created_during_save_is_preserved(native_host, tmp_path):
    destination = tmp_path / "maps"

    def save(path):
        destination.mkdir()
        (destination / "owned-by-user").write_text("keep")
        Path(path).write_bytes(png_header())

    native_host[1].save = save
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.export_native_maps(str(destination), OUTPUTS, "graph-A")
    assert error.value.code == "OUTPUT_EXISTS"
    assert list(destination.iterdir()) == [destination / "owned-by-user"]
    assert (destination / "owned-by-user").read_text() == "keep"
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("outputs", [[None], [{"name": "height"}], OUTPUTS + [OUTPUTS[0]]])
def test_malformed_selection_leaves_destination_absent(native_host, tmp_path, outputs):
    with pytest.raises(api.GraphAuthoringError) as error:
        evaluation.export_native_maps(str(tmp_path / "maps"), outputs, "graph-A")
    assert error.value.code == "INVALID_GRAPH_OUTPUTS"
    assert list(tmp_path.iterdir()) == []
