"""Behavioral SDK doubles: handles, directions and mutation/readback boundaries."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_connections as connections
from dcc_mcp_substance3d_designer import graph_inspection as inspection
from dcc_mcp_substance3d_designer.skill_support import typed_result


class Property:
    def __init__(self, identifier, category, type_id="float", readonly=False, connectable=True):
        self.identifier, self.category, self.type_id = identifier, category, type_id
        self.readonly, self.connectable = readonly, connectable

    def getId(self):
        return self.identifier

    def getCategory(self):
        return SimpleNamespace(name=self.category)

    def getTypes(self):
        return (
            []
            if self.type_id is None
            else [SimpleNamespace(getId=lambda: self.type_id, getModifier=lambda: SimpleNamespace(name="Auto"))]
        )

    def isReadOnly(self):
        return self.readonly

    def isConnectable(self):
        return self.connectable

    def isVariadic(self):
        return False

    def getLabel(self):
        return self.identifier

    def getDescription(self):
        return "SDK property"

    def getDefaultValue(self):
        return None


class Value:
    def __init__(self, value, kind="float"):
        self.value, self.kind = value, kind

    def get(self):
        return self.value

    def getType(self):
        return SimpleNamespace(getId=lambda: self.kind)


class Edge:
    def __init__(self, source, output, target, input_):
        self.source, self.output, self.target, self.input = source, output, target, input_

    def getOutputPropertyNode(self):
        return self.source

    def getOutputProperty(self):
        return self.output

    def getInputPropertyNode(self):
        return self.target

    def getInputProperty(self):
        return self.input

    def disconnect(self):
        self.source.edges.remove(self)
        self.target.edges.remove(self)


class Node:
    def __init__(self, identifier):
        self.identifier = identifier
        self.inputs = [Property("in", "Input"), Property("scale", "Input", connectable=False)]
        self.outputs = [Property("out", "Output")]
        self.edges, self.writes = [], []
        self.values = {"scale": Value(1.0)}
        self.ignore_connect = self.ignore_set = False

    def getIdentifier(self):
        return self.identifier

    def getDefinition(self):
        return SimpleNamespace(getId=lambda: "sbs::compositing::test")

    def getProperties(self, category):
        return self.inputs if category == "Input" else self.outputs

    def getPropertyFromId(self, identifier, category):
        return next((prop for prop in self.getProperties(category) if prop.getId() == identifier), None)

    def getPropertyConnections(self, prop):
        return [
            edge
            for edge in self.edges
            if (edge.source is self and edge.output is prop) or (edge.target is self and edge.input is prop)
        ]

    def newPropertyConnectionFromId(self, output, target, input_):
        if self.ignore_connect:
            return object()
        edge = Edge(self, self.getPropertyFromId(output, "Output"), target, target.getPropertyFromId(input_, "Input"))
        self.edges.append(edge)
        target.edges.append(edge)
        return None  # Some SDK calls mutate and return no Python connection object.

    def getPropertyGraph(self, prop):
        return None

    def getPropertyValue(self, prop):
        return self.values.get(prop.getId())

    def getAnnotationPropertyValueFromId(self, identifier):
        return Value("Display label", "string")

    def setInputPropertyValueFromId(self, identifier, value):
        self.writes.append(identifier)
        if not self.ignore_set:
            self.values[identifier] = value


@pytest.fixture
def graph(monkeypatch):
    nodes = [Node("100"), Node("200"), Node("300")]
    graph = SimpleNamespace(
        getUID=lambda: "graph-A",
        getIdentifier=lambda: "material",
        getNodes=lambda: nodes,
        deleteNode=lambda node: nodes.remove(node),
    )
    monkeypatch.setattr(api, "active_graph", lambda: graph)
    prop_module = ModuleType("sd.api.sdproperty")
    prop_module.SDPropertyCategory = SimpleNamespace(Input="Input", Output="Output")
    values = ModuleType("sd.api.sdvaluefloat")
    values.SDValueFloat = SimpleNamespace(sNew=lambda raw: Value(raw))
    monkeypatch.setitem(sys.modules, "sd", ModuleType("sd"))
    monkeypatch.setitem(sys.modules, "sd.api", ModuleType("sd.api"))
    monkeypatch.setitem(sys.modules, "sd.api.sdproperty", prop_module)
    monkeypatch.setitem(sys.modules, "sd.api.sdvaluefloat", values)
    return graph


def test_exact_connect_readback_idempotence_and_disconnect_fanout(graph):
    result = connections.connect_nodes("100", "out", "200", "in", "graph-A")
    assert not result["already_connected"]
    assert connections.connect_nodes("100", "out", "200", "in", "graph-A")["already_connected"]
    connections.connect_nodes("100", "out", "300", "in", "graph-A")
    assert connections.disconnect_nodes("100", "out", "200", "in", "graph-A")["disconnected"]
    assert not connections.disconnect_nodes("100", "out", "200", "in", "graph-A")["disconnected"]
    assert [connections.edge(edge) for edge in graph.getNodes()[0].edges] == [("100", "out", "300", "in")]


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "PORT_NOT_FOUND"),
        ("type", "PORT_TYPE_MISMATCH"),
        ("unknown", "PORT_TYPE_UNAVAILABLE"),
        ("readonly", "PROPERTY_READ_ONLY"),
        ("not_connectable", "PORT_NOT_CONNECTABLE"),
        ("occupied", "INPUT_CONNECTED"),
        ("cycle", "GRAPH_CYCLE"),
    ],
)
def test_connection_preflight_prevents_mutation(graph, case, code):
    source, target, third = graph.getNodes()
    if case == "missing":
        target.inputs.clear()
    if case == "type":
        target.inputs[0].type_id = "texture"
    if case == "unknown":
        target.inputs[0].type_id = None
    if case == "readonly":
        target.inputs[0].readonly = True
    if case == "not_connectable":
        target.inputs[0].connectable = False
    if case == "occupied":
        third.newPropertyConnectionFromId("out", target, "in")
    if case == "cycle":
        target.newPropertyConnectionFromId("out", source, "in")
    before = len(source.edges)
    with pytest.raises(api.GraphAuthoringError) as error:
        connections.connect_nodes("100", "out", "200", "in", "graph-A")
    assert error.value.code == code
    assert len(source.edges) == before


def test_sdk_acknowledgement_without_mutation_is_not_success(graph):
    graph.getNodes()[0].ignore_connect = True
    result = typed_result("connect", connections.connect_nodes, "100", "out", "200", "in", "graph-A")
    assert result["error"] == "CONNECTION_READBACK_FAILED"


def test_disconnect_requires_observed_removal(graph, monkeypatch):
    connections.connect_nodes("100", "out", "200", "in", "graph-A")
    monkeypatch.setattr(Edge, "disconnect", lambda self: None)
    result = typed_result("disconnect", connections.disconnect_nodes, "100", "out", "200", "in", "graph-A")
    assert result["error"] == "DISCONNECT_READBACK_FAILED"


@pytest.mark.parametrize(
    "operation,args",
    [
        (connections.connect_nodes, ("100", "out", "200", "in")),
        (connections.disconnect_nodes, ("100", "out", "200", "in")),
        (api.delete_node, ("100",)),
        (api.set_parameter, ("100", "scale", "float", 2.0)),
    ],
)
def test_changed_graph_context_rejects_mutations(graph, operation, args):
    result = typed_result("mutation", operation, *args, expected_graph_uid="old-graph")
    assert result["error"] == "GRAPH_CONTEXT_CHANGED"
    assert len(graph.getNodes()) == 3
    assert all(not node.writes and not node.edges for node in graph.getNodes())


def test_native_numeric_ids_and_property_metadata(graph):
    page = inspection.list_nodes(limit=2)
    assert page["next_offset"] == 2
    assert page["items"][0]["node_id"] == "100"
    node = inspection.describe_node("100", "graph-A")
    assert node["inputs"][0]["types"] == [{"id": "float", "modifier": "Auto"}]
    assert node["inputs"][1]["connectable"] is False


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), True, 1e20])
def test_invalid_float_never_reaches_sdk_mutation(graph, raw):
    result = typed_result("set", api.set_parameter, "100", "scale", "float", raw)
    assert result["error"] == "INVALID_VALUE"
    assert not graph.getNodes()[0].writes


@pytest.mark.parametrize(
    "case,code",
    [
        ("readonly", "PROPERTY_READ_ONLY"),
        ("type", "PARAMETER_TYPE_MISMATCH"),
        ("connected", "INPUT_CONNECTED"),
        ("function", "PROPERTY_GRAPH_CONNECTED"),
        ("ignored", "PARAMETER_READBACK_FAILED"),
    ],
)
def test_parameter_guards_and_readback(graph, case, code):
    node = graph.getNodes()[0]
    if case == "readonly":
        node.inputs[1].readonly = True
    if case == "type":
        node.inputs[1].type_id = "texture"
    if case == "connected":
        graph.getNodes()[1].newPropertyConnectionFromId("out", node, "scale")
    if case == "function":
        node.getPropertyGraph = lambda prop: object()
    if case == "ignored":
        node.ignore_set = True
    result = typed_result("set", api.set_parameter, "100", "scale", "float", 2.0)
    assert result["error"] == code
    if case != "ignored":
        assert not node.writes


def test_parameter_success_and_deleted_reference(graph):
    assert api.set_parameter("100", "scale", "float", 2.0)["value"] == 2.0
    api.delete_node("100", "graph-A")
    assert typed_result("get", api.get_parameter, "100", "scale")["error"] == "NODE_NOT_FOUND"


def test_ignored_deletion_fails_readback(graph):
    graph.deleteNode = lambda node: None
    assert typed_result("delete", api.delete_node, "100")["error"] == "NODE_DELETE_READBACK_FAILED"


def test_sdk_baseexception_is_reported_but_interrupt_is_propagated(monkeypatch):
    class APIException(BaseException):
        mErrorCode = SimpleNamespace(name="InvalidArgument")

    module = ModuleType("sd.api.apiexception")
    module.APIException = APIException
    monkeypatch.setitem(sys.modules, "sd.api.apiexception", module)

    def fail():
        raise APIException("private path should not leak")

    assert typed_result("compute", fail)["error"] == "SDK_API_ERROR:InvalidArgument"

    def interrupt():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        typed_result("compute", interrupt)
