from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import yaml

SCRIPTS = (
    Path(__file__).parent.parent / "src" / "dcc_mcp_substance3d_designer" / "skills" / "designer-session" / "scripts"
)


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
        "node_id": "generated",
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
        source_node="node_0",
        source_property="unique_filter_output",
        target_node="node_1",
        target_property="foreground",
    )["success"]
    assert _load_script("set_parameter").main(node_id="node_0", parameter="scale", value_type="float", value=4.0)[
        "success"
    ]
    assert not _load_script("expose_parameter").main(node_id="node_0", parameter="scale", exposed_id="noise_scale")[
        "success"
    ]
    assert _load_script("add_output").main(output_id="base_color", position=[200, 0])["success"]
    assert _load_script("set_output_usage").main(
        node_id="node_2", usage="baseColor", channels="RGBA", color_space="sRGB"
    )["success"]

    state = _load_script("export_graph_state").main(include_parameters=True)
    assert state["success"] is True
    assert state["context"]["graph"]["node_count"] == 3
    assert state["context"]["graph"]["connections"][0]["target_node"] == "node_1"
    assert state["context"]["graph"]["outputs"][0]["usages"][0]["usage"] == "baseColor"
