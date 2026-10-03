from __future__ import annotations

import copy
import importlib.util
import math
import struct
import sys
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace as NS

import jsonschema
import pytest
import yaml

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_gradients as gradients

KEYS = [
    {"position": 0, "color": [0.62, 0.35, 0.25, 1]},
    {"position": 0.48, "color": [0.70, 0.43, 0.32, 1], "midpoint": 0.5},
    {"position": 1, "color": [0.78, 0.52, 0.41, 1]},
]
SKILL = Path(__file__).parents[1] / "src/dcc_mcp_substance3d_designer/skills/designer-session"


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


class Value:
    def __init__(self, raw):
        self.raw = raw

    def get(self):
        return self.raw


class Key:
    def __init__(self, kind):
        self.kind, self.values = kind, {}

    def getType(self):
        return self.kind

    def setPropertyValueFromId(self, field, value):
        self.values[field] = value

    def getPropertyValueFromId(self, field):
        return self.values[field]


class Array:
    def __init__(self, kind, size):
        self.kind = kind
        self.keys = [None] * size

    def getType(self):
        return NS(getId=lambda: gradients._ARRAY_TYPE, getItemType=lambda: self.kind)

    def getSize(self):
        return len(self.keys)

    def setItem(self, index, key):
        self.keys[index] = key

    def getItem(self, index):
        return self.keys[index]


@pytest.fixture
def host(monkeypatch):
    color = namedtuple("ColorRGBA", "r g b a")
    fields = {"position": "float", "midpoint": "float", "value": "ColorRGBA"}
    kind = NS(
        getId=lambda: gradients._KEY_TYPE,
        getMembers=lambda: [
            NS(
                getId=lambda field=field: field,
                getTypes=lambda field=field: [NS(getId=lambda: fields[field], getModifier=lambda: "Auto")],
            )
            for field in fields
        ],
    )
    original = Array(kind, 2)
    for index in range(2):
        key = Key(kind)
        key.values = {
            "position": Value(index),
            "midpoint": Value(0.5),
            "value": Value(color(index, index, index, 1)),
        }
        original.setItem(index, key)
    state = {"value": original, "writes": [], "readonly": False, "connections": [], "function": None}
    prop = NS(
        getId=lambda: "gradientrgba",
        isReadOnly=lambda: state["readonly"],
        getTypes=lambda: [NS(getId=lambda: gradients._ARRAY_TYPE, getModifier=lambda: "Auto")],
    )

    def write(parameter, value):
        assert parameter == "gradientrgba"
        state["writes"].append(value)
        state["value"] = value

    node = NS(
        getIdentifier=lambda: "200",
        getDefinition=lambda: NS(getId=lambda: "sbs::compositing::gradient"),
        getPropertyFromId=lambda name, category: prop if name == "gradientrgba" and category == "Input" else None,
        getPropertyValue=lambda _: state["value"],
        getPropertyConnections=lambda _: state["connections"],
        getPropertyGraph=lambda _: state["function"],
        setInputPropertyValueFromId=write,
    )
    graph = NS(getUID=lambda: "graph-A", getNodes=lambda: [node])
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    monkeypatch.setattr(
        api,
        "typed_value",
        lambda kind, raw: (
            Value(color(*(f32(component) for component in raw))) if kind == "colorrgba" else Value(f32(raw))
        ),
    )
    for name, attr, wrapper in [
        ("sd.api.sdproperty", "SDPropertyCategory", NS(Input="Input")),
        ("sd.api.sdvaluearray", "SDValueArray", NS(sNew=Array)),
        ("sd.api.sdvaluestruct", "SDValueStruct", NS(sNew=Key)),
    ]:
        monkeypatch.setitem(sys.modules, name, NS(**{attr: wrapper}))
    return state, node, graph, prop, fields


def test_setter_constructs_detached_native_keys_and_returns_float32_readback(host):
    state, _, _, _, _ = host
    original = state["value"]
    result = gradients.set_gradient_keys("200", KEYS, "graph-A")
    assert result["graph_uid"] == "graph-A"
    assert result["parameter"] == "gradientrgba"
    assert len(state["writes"]) == 1 and state["value"] is not original
    assert original.getSize() == 2
    assert result["keys"][1] == {"position": f32(0.48), "color": [f32(v) for v in KEYS[1]["color"]], "midpoint": 0.5}
    assert gradients.get_gradient_keys("200", "graph-A")["keys"] == result["keys"]
    assert len(state["writes"]) == 1


@pytest.mark.parametrize("raw", [None, [], KEYS[:1], KEYS * 22, {}, "keys"])
def test_key_count_and_container_fail_before_host_access(monkeypatch, raw):
    monkeypatch.setattr(api, "active_graph", lambda: pytest.fail("Invalid keys must not access the SDK"))
    with pytest.raises(api.GraphAuthoringError) as caught:
        gradients.set_gradient_keys("200", raw, "graph-A")
    assert caught.value.code == "INVALID_GRADIENT_KEYS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("position", math.nan),
        ("position", math.inf),
        ("position", True),
        ("position", 2**10000),
        ("position", -0.01),
        ("midpoint", 1.01),
        ("midpoint", None),
        ("color", [0, 0, 0]),
        ("color", [0, 0, 0, math.nan]),
        ("color", [0, 0, 0, False]),
        ("color", [0, 0, 0, 1.01]),
        ("unexpected", "code"),
    ],
)
def test_invalid_components_fail_before_host_access(monkeypatch, field, value):
    keys = copy.deepcopy(KEYS)
    keys[0][field] = value
    monkeypatch.setattr(api, "active_graph", lambda: pytest.fail("Invalid keys must not access the SDK"))
    with pytest.raises(api.GraphAuthoringError) as caught:
        gradients.set_gradient_keys("200", keys, "graph-A")
    assert caught.value.code == "INVALID_GRADIENT_KEYS"


@pytest.mark.parametrize("positions", [[0, 0, 1], [1, 0.5, 0]])
def test_ambiguous_or_reversed_positions_are_rejected(positions):
    keys = copy.deepcopy(KEYS)
    for key, position in zip(keys, positions):
        key["position"] = position
    with pytest.raises(api.GraphAuthoringError, match="strictly increasing"):
        gradients.validate_keys(keys)


@pytest.mark.parametrize("uid", [None, "", "x" * 129, "graph-B"])
def test_uid_is_mandatory_and_stale_graphs_never_mutate(host, uid):
    state = host[0]
    with pytest.raises(api.GraphAuthoringError):
        gradients.set_gradient_keys("200", KEYS, uid)
    assert state["writes"] == []


@pytest.mark.parametrize("failure", ["node", "input", "fields", "readonly", "connections", "function"])
def test_type_and_constant_input_guards_prevent_mutation(host, failure):
    state, node, _, prop, fields = host
    if failure == "node":
        node.getDefinition = lambda: NS(getId=lambda: "sbs::compositing::uniform")
    elif failure == "input":
        prop.getTypes = lambda: [NS(getId=lambda: "float", getModifier=lambda: "Auto")]
    elif failure == "fields":
        fields["value"] = "float4"
    elif failure == "readonly":
        state["readonly"] = True
    elif failure == "connections":
        state["connections"] = [object()]
    else:
        state["function"] = object()
    with pytest.raises(api.GraphAuthoringError):
        gradients.set_gradient_keys("200", KEYS, "graph-A")
    assert state["writes"] == []


def test_graph_rechecked_before_mutation(host, monkeypatch):
    state, _, graph, _, _ = host
    calls = []

    def active():
        calls.append(True)
        return graph if len(calls) == 1 else NS(getUID=lambda: "graph-B")

    monkeypatch.setattr(api, "active_graph", active)
    with pytest.raises(api.GraphAuthoringError) as caught:
        gradients.set_gradient_keys("200", KEYS, "graph-A")
    assert caught.value.code == "GRAPH_CONTEXT_CHANGED"
    assert state["writes"] == []


@pytest.mark.parametrize("positions", [[0, 0, 1], [1, 0, 0]])
def test_native_getter_preserves_stacked_pins_and_native_order(host, positions):
    state = host[0]
    original = state["value"]
    original.keys.append(copy.deepcopy(original.getItem(1)))
    for key, position in zip(original.keys, positions):
        key.values["position"] = Value(position)
    result = gradients.get_gradient_keys("200", "graph-A")
    assert [key["position"] for key in result["keys"]] == positions
    assert state["writes"] == []


def test_positions_collapsing_in_native_float32_fail_before_mutation(host):
    keys = copy.deepcopy(KEYS)
    keys[1]["position"] = 1e-100
    with pytest.raises(api.GraphAuthoringError, match="strictly increasing"):
        gradients.set_gradient_keys("200", keys, "graph-A")
    assert host[0]["writes"] == []


def test_failed_native_readback_restores_previous_array(host):
    state, node, _, _, _ = host
    original = state["value"]

    def read(_):
        current = state["value"]
        if current is not original:
            current.getItem(0).values["midpoint"] = Value(0.75)
        return current

    node.getPropertyValue = read
    with pytest.raises(api.GraphAuthoringError) as caught:
        gradients.set_gradient_keys("200", KEYS, "graph-A")
    assert caught.value.code == "GRADIENT_READBACK_FAILED"
    assert state["value"] is original
    assert len(state["writes"]) == 2


@pytest.mark.parametrize("sdk_type", ["SDValueArray", "SDValueStruct"])
def test_failed_sdk_construction_never_mutates(host, monkeypatch, sdk_type):
    state = host[0]
    module = "sd.api.sdvaluearray" if sdk_type == "SDValueArray" else "sd.api.sdvaluestruct"
    monkeypatch.setattr(getattr(sys.modules[module], sdk_type), "sNew", lambda *_args: None)
    with pytest.raises(api.GraphAuthoringError) as caught:
        gradients.set_gradient_keys("200", KEYS, "graph-A")
    assert caught.value.code == "GRADIENT_VALUE_UNAVAILABLE"
    assert state["writes"] == []


def test_sdk_write_failure_after_mutation_restores_original(host):
    state, node, _, _, _ = host
    original = state["value"]

    def write(_parameter, value):
        state["writes"].append(value)
        state["value"] = value
        if value is not original:
            raise RuntimeError("native write failed")

    node.setInputPropertyValueFromId = write
    with pytest.raises(RuntimeError, match="native write failed"):
        gradients.set_gradient_keys("200", KEYS, "graph-A")
    assert state["value"] is original
    assert len(state["writes"]) == 2


def test_tool_schemas_are_bounded_and_entries_return_native_keys(host):
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text())["tools"]
    tools = {tool["name"]: tool for tool in tools}
    arguments = {"node_id": "200", "expected_graph_uid": "graph-A", "keys": KEYS}
    setter = tools["set_gradient_keys"]
    jsonschema.validate(arguments, setter["input_schema"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**arguments, "keys": []}, setter["input_schema"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"node_id": "200", "keys": KEYS}, setter["input_schema"])
    for name in ["set_gradient_keys", "get_gradient_keys"]:
        assert tools[name]["affinity"] == "main" and tools[name]["enforce_thread_affinity"] is True
        spec = importlib.util.spec_from_file_location(name, SKILL / tools[name]["source_file"])
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        params = arguments if name == "set_gradient_keys" else {k: v for k, v in arguments.items() if k != "keys"}
        result = script.main(**params)
        assert result["success"] is True and len(result["context"]["keys"]) == 3
