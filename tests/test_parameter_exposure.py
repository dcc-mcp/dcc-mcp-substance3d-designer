import sys
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer.graph_parameters import expose_parameter


class Value:
    def __init__(self, raw, kind="float"):
        self.raw, self.kind = raw, kind

    def get(self):
        return self.raw

    def getType(self):
        return NS(getId=lambda: self.kind)


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(api, "typed_value", lambda kind, raw: Value(raw, kind))
    prop = NS(getId=lambda: "scale", isReadOnly=lambda: False)
    variable = NS(
        getId=lambda: "actual_sdk_variable_port",
        isReadOnly=lambda: False,
        getTypes=lambda: [NS(getId=lambda: "string", getModifier=lambda: "Auto")],
    )
    output = NS(getTypes=lambda: [NS(getId=lambda: "float", getModifier=lambda: "Auto")])
    state = {
        "constant": Value(0.5),
        "function": None,
        "public": None,
        "outputs": [],
        "binding": None,
        "definitions": ["sbs::function::get_float1"],
    }
    reader = NS(
        getIdentifier=lambda: "200",
        getProperties=lambda cat: [variable] if cat == "Input" else [output],
        setInputPropertyValueFromId=lambda name, val: state.update(binding=val),
        getPropertyValue=lambda prop: state["binding"],
    )
    function = NS(
        getNodeDefinitions=lambda: [NS(getId=lambda d=d: d) for d in state["definitions"]],
        newNode=lambda type_id: reader,
        setOutputNode=lambda n, flag: state.update(outputs=[n]),
        getOutputNodes=lambda: state["outputs"],
    )

    def create_function(*args):
        state["function"] = function
        return function

    def create_public(*args):
        state["public"] = prop
        return prop

    node = NS(
        getIdentifier=lambda: "100",
        getPropertyFromId=lambda *args: prop,
        getPropertyConnections=lambda prop: [],
        getPropertyGraph=lambda prop: state["function"],
        getPropertyValue=lambda prop: state["constant"],
        newPropertyGraph=create_function,
        deletePropertyGraph=lambda prop: state.update(function=None),
        setInputPropertyValueFromId=lambda name, val: state.update(constant=val),
    )
    graph = NS(
        getUID=lambda: "graph-A",
        getNodes=lambda: [node],
        getPropertyFromId=lambda *args: state["public"],
        newProperty=create_public,
        setPropertyValue=lambda prop, val: state.update(public_value=val),
        getPropertyValue=lambda prop: state["public_value"],
        deleteProperty=lambda prop: state.update(public=None),
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    for name, attr, value in [
        ("sd.api.sdproperty", "SDPropertyCategory", NS(Input="Input", Output="Output")),
        ("sd.api.sdvaluestring", "SDValueString", NS(sNew=lambda raw: Value(raw, "string"))),
    ]:
        module = ModuleType(name)
        setattr(module, attr, value)
        monkeypatch.setitem(sys.modules, name, module)
    return state, node, graph


def test_public_function_binding_preserves_default_and_reads_actual_port(host):
    state, _, _ = host
    result = expose_parameter("100", "scale", "paint_coverage", "graph-A")
    assert result["reader_node_id"] == "200" and state["binding"].get() == "paint_coverage"
    assert state["public_value"].get() == 0.5 and state["function"] is not None


@pytest.mark.parametrize("failure", ["definition", "readback", "public_readback"])
def test_exposure_rolls_back_only_its_objects(host, failure):
    state, node, graph = host
    if failure == "definition":
        state["definitions"] = []
    elif failure == "readback":
        original = node.newPropertyGraph

        def create(*args):
            function = original(*args)
            function.newNode("x").getPropertyValue = lambda prop: Value("wrong", "string")
            return function

        node.newPropertyGraph = create
    else:
        graph.getPropertyValue = lambda prop: Value(99)
    with pytest.raises(api.GraphAuthoringError):
        expose_parameter("100", "scale", "coverage", "graph-A")
    assert state["public"] is None and state["function"] is None and state["constant"].get() == 0.5


def test_existing_binding_is_not_reset(host):
    state, _, _ = host
    previous = object()
    state["function"] = previous
    with pytest.raises(api.GraphAuthoringError):
        expose_parameter("100", "scale", "coverage", "graph-A")
    assert state["function"] is previous


def test_native_color_json_values():
    assert api.json_value(NS(r=0.1, g=0.2, b=0.3, a=1.0)) == [0.1, 0.2, 0.3, 1.0]
