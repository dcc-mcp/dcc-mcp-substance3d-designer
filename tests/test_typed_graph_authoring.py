from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from dcc_mcp_substance3d_designer import graph_authoring

SCRIPTS = (
    Path(__file__).parent.parent / "src" / "dcc_mcp_substance3d_designer" / "skills" / "designer-session" / "scripts"
)


def test_native_read_only_identifier_is_returned_and_resolves(monkeypatch):
    labels = {}
    node = SimpleNamespace(
        getIdentifier=lambda: "1581078951",
        getProperties=lambda _: [],
        newProperty=lambda *args: None,
        setAnnotationPropertyValueFromId=lambda name, val: labels.update({name: val}),
        setPosition=lambda pos: None,
    )
    graph = SimpleNamespace(newNode=lambda _: node, getNodes=lambda: [node])
    monkeypatch.setattr(graph_authoring, "active_graph", lambda: graph)
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", SimpleNamespace(float2=lambda *v: v))
    monkeypatch.setitem(
        sys.modules, "sd.api.sdproperty", SimpleNamespace(SDPropertyCategory=SimpleNamespace(Annotation="annotation"))
    )
    monkeypatch.setitem(
        sys.modules, "sd.api.sdtypestring", SimpleNamespace(SDTypeString=SimpleNamespace(sNew=lambda: "string"))
    )
    monkeypatch.setitem(
        sys.modules, "sd.api.sdvaluestring", SimpleNamespace(SDValueString=SimpleNamespace(sNew=lambda v: v))
    )
    result = graph_authoring.create_node("sbs::compositing::uniform", "wood")
    assert result["node_id"] == "1581078951"
    assert labels == {}
    assert result["requested_node_id"] == "wood"
    assert result["identifier_assigned"] is False
    assert graph_authoring.find_node(result["node_id"]) is node


def test_failed_node_setup_removes_only_created_node(monkeypatch):
    deleted = []

    def fail(_):
        raise RuntimeError("position rejected")

    node = SimpleNamespace(getIdentifier=lambda: "123", setPosition=fail)
    graph = SimpleNamespace(newNode=lambda _: node, deleteNode=deleted.append)
    monkeypatch.setattr(graph_authoring, "active_graph", lambda: graph)
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", SimpleNamespace(float2=lambda *v: v))
    with pytest.raises(RuntimeError, match="position rejected"):
        graph_authoring.create_node("sbs::compositing::uniform")
    assert deleted == [node]


def test_native_render_validates_ports_and_preserves_existing_exports(monkeypatch, tmp_path):
    script = _load_script("render_graph_maps")
    mutations = []
    texture = SimpleNamespace(
        save=lambda path: Path(path).write_bytes(b"fresh texture"), getSize=lambda: SimpleNamespace(x=512, y=512)
    )
    node = SimpleNamespace(
        getProperties=lambda _: [SimpleNamespace(getId=lambda: "out")],
        getPropertyValueFromId=lambda *args: SimpleNamespace(get=lambda: texture),
    )
    graph = SimpleNamespace(
        getNodes=lambda: [node],
        getPropertyFromId=lambda *args: "size_property",
        setPropertyInheritanceMethod=lambda prop, mode: mutations.append("absolute"),
        setInputPropertyValueFromId=lambda *args: mutations.append("resize"),
        compute=lambda: mutations.append("compute"),
    )
    monkeypatch.setattr(script, "active_graph", lambda: graph)
    monkeypatch.setattr(script, "find_node", lambda _: node)
    monkeypatch.setitem(
        sys.modules,
        "sd.api.sdproperty",
        SimpleNamespace(
            SDPropertyCategory=SimpleNamespace(Output=1, Input=0),
            SDPropertyInheritanceMethod=SimpleNamespace(Absolute=2),
        ),
    )
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", SimpleNamespace(int2=lambda *v: v))
    monkeypatch.setitem(
        sys.modules, "sd.api.sdvalueint2", SimpleNamespace(SDValueInt2=SimpleNamespace(sNew=lambda v: v))
    )
    outputs = [{"name": "height", "node_id": "123", "property": "missing"}]
    with pytest.raises(graph_authoring.GraphAuthoringError, match="port not found"):
        script.render_graph_maps(str(tmp_path / "new"), outputs)
    assert mutations == []
    outputs[0]["property"] = "out"
    with pytest.raises(graph_authoring.GraphAuthoringError, match="new output directory"):
        script.render_graph_maps(str(tmp_path), outputs)
    assert mutations == []
    result = script.render_graph_maps(str(tmp_path / "new"), outputs, 512)
    assert mutations == ["absolute", "resize", "compute"]
    assert Path(result["files"][0]["path"]).read_bytes() == b"fresh texture"
    assert len(result["files"][0]["sha256"]) == 64
    with pytest.raises(graph_authoring.GraphAuthoringError, match="requested resolution"):
        script.render_graph_maps(str(tmp_path / "wrong_size"), outputs, 1024)
    assert list((tmp_path / "wrong_size").iterdir()) == []


def test_select_graph_requires_exact_loaded_package(monkeypatch, tmp_path):
    script = _load_script("select_graph")
    opened = []
    graph = SimpleNamespace(getNodes=lambda: [])
    path = tmp_path / "material.sbs"
    package = SimpleNamespace(
        getFilePath=lambda: str(path), findResourceFromUrl=lambda name: graph if name == "wood" else None
    )
    app = SimpleNamespace(
        getPackageMgr=lambda: SimpleNamespace(getUserPackages=lambda: [package]),
        getUIMgr=lambda: SimpleNamespace(openResourceInEditor=opened.append),
    )
    monkeypatch.setattr(script, "application", lambda: app)
    with pytest.raises(graph_authoring.GraphAuthoringError, match="loaded package"):
        script.select_graph(str(tmp_path / "other.sbs"), "wood")
    with pytest.raises(graph_authoring.GraphAuthoringError, match="Graph not found"):
        script.select_graph(str(path), "missing")
    assert opened == []
    assert script.select_graph(str(path), "wood")["graph_id"] == "wood"
    assert opened == [graph]


@pytest.mark.parametrize("package", ["../noise.sbs", "C:/noise.sbs", "noise.sbsar", "https://noise.sbs"])
def test_resource_node_rejects_non_shipped_paths_before_sdk(package):
    result = _load_script("create_resource_node").main(package_name=package, resource_id="noise", node_id="noise")
    assert not result["success"]
    assert result["error"] == "INVALID_PACKAGE_NAME"


def test_rgba_color_uses_color_sdk_type_and_readback(monkeypatch):
    from collections import namedtuple

    color = namedtuple("ColorRGBA", "r g b a")
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", SimpleNamespace(ColorRGBA=color))
    monkeypatch.setitem(
        sys.modules, "sd.api.sdvaluecolorrgba", SimpleNamespace(SDValueColorRGBA=SimpleNamespace(sNew=lambda v: v))
    )
    value = graph_authoring.typed_value("colorrgba", [0.1, 0.2, 0.3, 1.0])
    assert graph_authoring.json_value(value) == [0.1, 0.2, 0.3, 1.0]


def test_sdk_base_exception_is_failure_but_interrupt_still_propagates(monkeypatch):
    from dcc_mcp_substance3d_designer.skill_support import typed_result

    class APIException(BaseException):
        pass

    monkeypatch.setitem(sys.modules, "sd.api.apiexception", SimpleNamespace(APIException=APIException))

    def fail(error):
        raise error

    result = typed_result("operation", fail, APIException("sensitive host details"))
    assert not result["success"]
    assert result["error"] == "SDK_API_ERROR:Unknown"
    assert "sensitive" not in str(result)
    with pytest.raises(KeyboardInterrupt):
        typed_result("operation", fail, KeyboardInterrupt())


def _load_script(name: str):
    script = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Property:
    def getTypes(self):
        return [SimpleNamespace(getId=lambda: "float", getModifier=lambda: SimpleNamespace(name="Auto"))]

    def isReadOnly(self):
        return False

    def isConnectable(self):
        return True

    def __init__(self, identifier: str) -> None:
        self._identifier = identifier

    def getId(self) -> str:
        return self._identifier


class _Value:
    def __init__(self, value) -> None:
        self._value = value

    def get(self):
        return self._value

    def getType(self):
        return SimpleNamespace(getId=lambda: "float")


class _Connection:
    def __init__(self, target, target_property: str) -> None:
        self._target = target
        self._target_property = _Property(target_property)

    def getInputProperty(self):
        return self._target_property

    def getInputNode(self):
        return self._target

    def getInputPropertyNode(self):
        return self._target

    def getOutputPropertyNode(self):
        return self._source

    def getOutputProperty(self):
        return _Property(self._output)


class _Node:
    def __init__(self, identifier: str, type_url: str, position: tuple[float, float]) -> None:
        self._identifier = identifier
        self._definition = SimpleNamespace(getId=lambda: type_url)
        self._position = SimpleNamespace(x=position[0], y=position[1])
        self._properties = {"input": [], "output": []}
        self._values = {}
        self._connections = {}
        self._usages = []
        self._annotations = {}

    def getIdentifier(self) -> str:
        return self._identifier

    def getDefinition(self):
        return self._definition

    def getPosition(self):
        return self._position

    def getProperties(self, category):
        return self._properties[category]

    def getPropertyValue(self, prop):
        return self._values.get(prop.getId())

    def getPropertyConnections(self, prop):
        return self._connections.get(prop.getId(), [])

    def getAnnotationPropertyValueFromId(self, identifier: str):
        if identifier == "usages":
            return _Value(self._usages)
        return self._annotations.get(identifier)

    def setIdentifier(self, identifier: str) -> None:
        self._identifier = identifier

    def setPosition(self, position) -> None:
        self._position = position

    def getPropertyFromId(self, identifier: str, category):
        return next(
            (prop for prop in self._properties[category] if prop.getId() == identifier),
            None,
        )

    def getPropertyGraph(self, prop):
        return None

    def setInputPropertyValueFromId(self, identifier: str, value) -> None:
        prop = self.getPropertyFromId(identifier, "input")
        if prop is None:
            prop = _Property(identifier)
            self._properties["input"].append(prop)
        self._values[identifier] = value

    def newPropertyConnectionFromId(self, output: str, target, input_property: str):
        connection = _Connection(target, input_property)
        connection._source, connection._output = self, output
        self._connections.setdefault(output, []).append(connection)
        target._connections.setdefault(input_property, []).append(connection)
        return connection

    def setAnnotationPropertyValueFromId(self, identifier: str, value) -> None:
        self._annotations[identifier] = value
        if identifier == "usages":
            self._usages = list(value)


def _install_fake_designer(monkeypatch):
    noise = _Node("noise", "sbs::compositing::perlin_noise_2", (-200.0, 0.0))
    blend = _Node("blend", "sbs::compositing::blend", (0.0, 0.0))
    output = _Node("base_color", "sbs::compositing::output", (200.0, 0.0))

    noise_output = _Property("unique_filter_output")
    noise._properties["input"] = [_Property("scale")]
    noise._properties["output"] = [noise_output]
    noise._values["scale"] = _Value(4.0)
    noise.newPropertyConnectionFromId("unique_filter_output", blend, "foreground")
    output._usages = [
        SimpleNamespace(
            getName=lambda: "baseColor",
            getComponents=lambda: "RGBA",
            getColorSpace=lambda: "sRGB",
        )
    ]

    graph = SimpleNamespace(
        getIdentifier=lambda: "typed_material",
        getNodes=lambda: [noise, blend, output],
    )
    application = SimpleNamespace(getUIMgr=lambda: SimpleNamespace(getCurrentGraph=lambda: graph))
    sd_module = ModuleType("sd")
    sd_module.getContext = lambda: SimpleNamespace(getSDApplication=lambda: application)
    property_module = ModuleType("sd.api.sdproperty")
    property_module.SDPropertyCategory = SimpleNamespace(Input="input", Output="output")
    strings = ModuleType("sd.api.sdvaluestring")
    strings.SDValueString = SimpleNamespace(sNew=lambda value: _Value(value))
    monkeypatch.setitem(sys.modules, "sd.api.sdvaluestring", strings)
    monkeypatch.setitem(sys.modules, "sd", sd_module)
    monkeypatch.setitem(sys.modules, "sd.api", ModuleType("sd.api"))
    monkeypatch.setitem(sys.modules, "sd.api.sdproperty", property_module)
    return graph


def test_export_graph_state_reports_typed_topology_and_output_usages(monkeypatch):
    _install_fake_designer(monkeypatch)

    result = _load_script("export_graph_state").main(include_parameters=True)

    assert result["success"] is True
    graph = result["context"]["graph"]
    assert graph["identifier"] == "typed_material"
    assert graph["node_count"] == 3
    assert graph["nodes"][0] == {
        "id": "noise",
        "type_url": "sbs::compositing::perlin_noise_2",
        "position": [-200.0, 0.0],
        "parameters": {"scale": 4.0},
        "outputs": ["unique_filter_output"],
    }
    assert graph["connections"] == [
        {
            "source_node": "noise",
            "source_property": "unique_filter_output",
            "target_node": "blend",
            "target_property": "foreground",
        }
    ]
    assert graph["outputs"] == [
        {
            "node_id": "base_color",
            "usages": [{"usage": "baseColor", "channels": "RGBA", "color_space": "sRGB"}],
        }
    ]


def test_create_node_uses_bounded_type_url_and_active_graph(monkeypatch):
    graph = _install_fake_designer(monkeypatch)
    created = _Node("generated", "sbs::compositing::uniform", (0.0, 0.0))
    graph.newNode = lambda type_url: created
    created.setIdentifier = lambda identifier: setattr(created, "_identifier", identifier)
    created.setPosition = lambda position: setattr(created, "_position", position)
    base_types = ModuleType("sd.api.sdbasetypes")
    base_types.float2 = lambda x, y: SimpleNamespace(x=x, y=y)
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", base_types)

    result = _load_script("create_node").main(
        type_url="sbs::compositing::uniform",
        node_id="uniform_color",
        position=[10.0, 20.0],
    )

    assert result["success"] is True
    assert result["context"] == {
        "node_id": "uniform_color",
        "requested_node_id": "uniform_color",
        "identifier_assigned": True,
        "type_url": "sbs::compositing::uniform",
        "position": [10.0, 20.0],
    }


def test_create_node_rejects_external_urls_before_importing_designer_sdk(monkeypatch):
    monkeypatch.delitem(sys.modules, "sd", raising=False)

    result = _load_script("create_node").main(type_url="https://example.invalid/node")

    assert result["success"] is False
    assert result["error"] == "INVALID_TYPE_URL"


def test_manifest_registers_only_typed_graph_and_package_operations():
    manifest = yaml.safe_load((SCRIPTS.parent / "tools.yaml").read_text(encoding="utf-8"))
    tools = {tool["name"]: tool for tool in manifest["tools"]}
    expected = {
        "create_graph",
        "create_node",
        "connect_nodes",
        "delete_node",
        "set_node_position",
        "set_parameter",
        "get_parameter",
        "expose_parameter",
        "add_output",
        "set_output_usage",
        "new_package",
        "open_package",
        "save_package",
        "save_package_as",
        "close_package",
        "import_resource",
        "export_maps",
        "export_sbsar",
        "export_graph_state",
    }

    assert expected <= tools.keys()
    assert not {"execute", "eval", "run_script"} & tools.keys()
    for name in expected:
        tool = tools[name]
        assert tool["affinity"] == "main"
        assert tool["input_schema"]["additionalProperties"] is False
        assert tool["output_schema"]["required"] == ["success", "message"]
        assert (SCRIPTS.parent / tool["source_file"]).is_file()


def test_typed_public_calls_build_and_verify_a_small_graph(monkeypatch):
    nodes = []

    def new_node(type_url: str):
        node = _Node(f"node_{len(nodes)}", type_url, (0.0, 0.0))
        if type_url != "sbs::compositing::output":
            node._properties["output"] = [_Property("unique_filter_output")]
        node._properties["input"] = [_Property("scale"), _Property("foreground")]
        nodes.append(node)
        return node

    graph = SimpleNamespace(
        getIdentifier=lambda: "typed_material",
        getNodes=lambda: nodes,
        newNode=new_node,
        getUID=lambda: "graph-uid",
        getOutputIdentifiers=lambda: [
            node._annotations["identifier"] for node in nodes if "identifier" in node._annotations
        ],
        deleteNode=lambda node: nodes.remove(node),
    )
    application = SimpleNamespace(getUIMgr=lambda: SimpleNamespace(getCurrentGraph=lambda: graph))
    sd_module = ModuleType("sd")
    sd_module.getContext = lambda: SimpleNamespace(getSDApplication=lambda: application)
    strings = ModuleType("sd.api.sdvaluestring")
    strings.SDValueString = SimpleNamespace(sNew=lambda value: _Value(value))
    monkeypatch.setitem(sys.modules, "sd.api.sdvaluestring", strings)
    monkeypatch.setitem(sys.modules, "sd", sd_module)
    monkeypatch.setitem(sys.modules, "sd.api", ModuleType("sd.api"))
    property_module = ModuleType("sd.api.sdproperty")
    property_module.SDPropertyCategory = SimpleNamespace(Input="input", Output="output")
    monkeypatch.setitem(sys.modules, "sd.api.sdproperty", property_module)
    base_types = ModuleType("sd.api.sdbasetypes")
    base_types.float2 = lambda x, y: SimpleNamespace(x=x, y=y)
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", base_types)
    float_values = ModuleType("sd.api.sdvaluefloat")
    float_values.SDValueFloat = SimpleNamespace(sNew=lambda value: _Value(value))
    monkeypatch.setitem(sys.modules, "sd.api.sdvaluefloat", float_values)
    usage_types = ModuleType("sd.api.sdtypeusage")
    usage_types.SDTypeUsage = SimpleNamespace(sNew=lambda: object())
    monkeypatch.setitem(sys.modules, "sd.api.sdtypeusage", usage_types)

    class _Array(list):
        @classmethod
        def sNew(cls, *_args):
            return cls()

        def pushBack(self, item) -> None:
            self.append(item)

    arrays = ModuleType("sd.api.sdvaluearray")
    arrays.SDValueArray = _Array
    monkeypatch.setitem(sys.modules, "sd.api.sdvaluearray", arrays)
    usage_values = ModuleType("sd.api.sdvalueusage")
    usage_values.SDUsage = SimpleNamespace(
        sNew=lambda usage, channels, color_space: SimpleNamespace(
            getName=lambda: usage,
            getComponents=lambda: channels,
            getColorSpace=lambda: color_space,
        )
    )
    usage_values.SDValueUsage = SimpleNamespace(sNew=lambda usage: usage)
    monkeypatch.setitem(sys.modules, "sd.api.sdvalueusage", usage_values)

    assert _load_script("create_node").main(
        type_url="sbs::compositing::perlin_noise_2",
        node_id="noise",
        position=[-200, 0],
    )["success"]
    assert _load_script("create_node").main(
        type_url="sbs::compositing::blend",
        node_id="blend",
        position=[0, 0],
    )["success"]
    assert _load_script("connect_nodes").main(
        source_node="noise",
        source_property="unique_filter_output",
        target_node="blend",
        target_property="foreground",
    )["success"]
    assert _load_script("set_parameter").main(node_id="noise", parameter="scale", value_type="float", value=4.0)[
        "success"
    ]
    assert not _load_script("expose_parameter").main(node_id="noise", parameter="scale", exposed_id="noise_scale")[
        "success"
    ]
    assert _load_script("add_output").main(output_id="base_color", position=[200, 0])["success"]
    assert _load_script("set_output_usage").main(
        node_id="base_color", usage="baseColor", channels="RGBA", color_space="sRGB"
    )["success"]

    state = _load_script("export_graph_state").main(include_parameters=True)
    assert state["success"] is True
    assert state["context"]["graph"]["node_count"] == 3
    assert state["context"]["graph"]["connections"][0]["target_node"] == "blend"
    assert state["context"]["graph"]["outputs"][0]["usages"][0]["usage"] == "baseColor"
