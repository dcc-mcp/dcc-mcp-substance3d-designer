"""Behavioral tests for discoverable Designer recipe resolution and effect chains."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_effects as effects
from dcc_mcp_substance3d_designer import graph_recipes as recipes

EFFECTS = "effects"
LIGHTING = "lighting"


def _definition(identifier):
    return SimpleNamespace(getId=lambda: identifier)


class _Edge:
    """Connection double matching the SDK endpoint getters graph_connections reads."""

    def __init__(self, source, output, target, input_):
        self.source, self.output = source, output
        self.target, self.input = target, input_

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


class _Node:
    """Minimal node double exposing connectable input/output ports."""

    def __init__(self, identifier, inputs=None, outputs=None):
        self.identifier = identifier
        self.inputs = inputs if inputs is not None else ["input"]
        self.outputs = outputs if outputs is not None else ["output"]
        self.edges = []

    def getIdentifier(self):
        return self.identifier

    def setPosition(self, position):
        self.position = position

    def getProperties(self, category):
        names = self.inputs if category == "Input" else self.outputs
        return [_property(name, category) for name in names]

    def getPropertyFromId(self, identifier, category):
        return next((prop for prop in self.getProperties(category) if prop.getId() == identifier), None)

    def getPropertyConnections(self, prop):
        return list(self.edges)

    def newPropertyConnectionFromId(self, output, target, input_):
        connection = _Edge(
            self, self.getPropertyFromId(output, "Output"), target, target.getPropertyFromId(input_, "Input")
        )
        self.edges.append(connection)
        target.edges.append(connection)
        return connection


def _property(identifier, category, type_id="float", connectable=True):
    return SimpleNamespace(
        getId=lambda: identifier,
        getCategory=lambda: SimpleNamespace(name=category),
        getTypes=lambda: [SimpleNamespace(getId=lambda: type_id, getModifier=lambda: SimpleNamespace(name="Auto"))],
        isConnectable=lambda: connectable,
        isReadOnly=lambda: False,
        isVariadic=lambda: False,
        getLabel=lambda: identifier,
        getDescription=lambda: "double property",
        getDefaultValue=lambda: None,
    )


def _install_property_module(monkeypatch):
    """Install the minimal fake SDK modules that port discovery imports."""
    monkeypatch.setitem(sys.modules, "sd", ModuleType("sd"))
    monkeypatch.setitem(sys.modules, "sd.api", ModuleType("sd.api"))
    property_module = ModuleType("sd.api.sdproperty")
    property_module.SDPropertyCategory = SimpleNamespace(Input="Input", Output="Output")
    monkeypatch.setitem(sys.modules, "sd.api.sdproperty", property_module)


@pytest.fixture
def graph(monkeypatch):
    """Active-graph double whose definition inventory is controlled per test."""
    nodes = [_Node("100"), _Node("200")]
    available = ["sbs::compositing::blur", "sbs::filter::warp", "sbs::filter::levels"]
    created = []

    def new_node(type_url):
        node = _Node(str(1000 + len(created)))
        created.append(node)
        nodes.append(node)
        return node

    holder = SimpleNamespace(
        getUID=lambda: "graph-A",
        getNodes=lambda: nodes,
        getNodeDefinitions=lambda: [_definition(url) for url in available],
        newNode=lambda type_url: new_node(type_url),
        deleteNode=lambda node: nodes.remove(node),
    )
    monkeypatch.setattr(api, "active_graph", lambda: holder)
    monkeypatch.setitem(sys.modules, "sd", ModuleType("sd"))
    monkeypatch.setitem(sys.modules, "sd.api", ModuleType("sd.api"))
    property_module = ModuleType("sd.api.sdproperty")
    property_module.SDPropertyCategory = SimpleNamespace(Input="Input", Output="Output")
    monkeypatch.setitem(sys.modules, "sd.api.sdproperty", property_module)
    monkeypatch.setitem(sys.modules, "sd.api.sdbasetypes", SimpleNamespace(float2=lambda *values: list(values)))
    holder.available = available
    holder.created = created
    holder.nodes = nodes
    return holder


def test_resolve_recipe_prefers_first_advertised_candidate(graph):
    # "blur" advertises sbs::compositing::blur before sbs::filter::blur.
    assert recipes.resolve_recipe(graph, EFFECTS, "blur") == "sbs::compositing::blur"
    # "warp" only advertises the filter namespace candidate.
    assert recipes.resolve_recipe(graph, EFFECTS, "warp") == "sbs::filter::warp"


def test_resolve_recipe_fails_closed_and_reports_candidates(graph):
    with pytest.raises(api.GraphAuthoringError) as error:
        recipes.resolve_recipe(graph, LIGHTING, "normal_from_height")
    assert error.value.code == "RECIPE_UNAVAILABLE"
    assert "sbs::compositing::normal" in str(error.value)
    assert graph.created == []


@pytest.mark.parametrize("category", ["effects", "lighting"])
def test_list_recipes_reports_availability_without_creating_nodes(graph, category):
    result = recipes.list_recipes(category, "graph-A")
    assert result["total"] == len(result["recipes"])
    assert result["available"] == sum(1 for row in result["recipes"] if row["available"])
    assert all(row["type_url"] is None for row in result["recipes"] if not row["available"])
    assert graph.created == []


def test_unknown_category_and_recipe_are_rejected(graph):
    with pytest.raises(api.GraphAuthoringError) as error:
        recipes.list_recipes("shading")
    assert error.value.code == "RECIPE_CATEGORY_UNKNOWN"
    with pytest.raises(api.GraphAuthoringError) as error:
        recipes.candidates(EFFECTS, "nonexistent_recipe")
    assert error.value.code == "RECIPE_UNKNOWN"


def test_module_namespace_extraction_covers_nested_and_root_ids():
    from dcc_mcp_substance3d_designer import graph_modules as modules

    assert modules.module_of("sbs::compositing::blur") == "sbs::compositing"
    assert modules.module_of("sbs::function::get_float1") == "sbs::function"
    assert modules.module_of("sbs::compositing") == "sbs::compositing"
    assert modules.module_of("rootnode") == "<root>"


def test_apply_effect_creates_node_and_wires_the_source(graph):
    result = effects.apply_effect(EFFECTS, "blur", "100", "output", expected_graph_uid="graph-A")
    assert result["mode"] == "single"
    assert result["steps"][0]["type_url"] == "sbs::compositing::blur"
    assert result["connected"] is False
    assert len(graph.created) == 1


def test_apply_effect_wires_optional_target(graph):
    result = effects.apply_effect(
        EFFECTS, "blur", "100", "output", target_node="200", target_property="input", expected_graph_uid="graph-A"
    )
    assert result["connected"] is True
    # The edge is recorded on the source node, which connects into the new node.
    assert graph.created[0].edges or graph.nodes[0].edges
    assert graph.nodes[0].edges[0].target is graph.created[0]


def test_apply_effect_rolls_back_when_connection_fails(graph, monkeypatch):
    def boom(*_args, **_kwargs):
        raise api.GraphAuthoringError("cycle", "GRAPH_CYCLE")

    monkeypatch.setattr(effects, "connect_nodes", boom)
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.apply_effect(EFFECTS, "blur", "100", "output", target_node="200", target_property="input")
    assert error.value.code == "GRAPH_CYCLE"
    assert len(graph.nodes) == 2


def test_apply_effect_rolls_back_when_port_discovery_fails(graph, monkeypatch):
    """Finding #2: PORT_NOT_FOUND during discovery must not leave the node behind."""

    def no_ports(node):
        raise api.GraphAuthoringError("Node exposes no connectable input", "PORT_NOT_FOUND")

    monkeypatch.setattr(effects, "primary_input", no_ports)
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.apply_effect(EFFECTS, "blur", "100", "output", expected_graph_uid="graph-A")
    assert error.value.code == "PORT_NOT_FOUND"
    # The created node was removed from the graph, not just abandoned.
    assert len(graph.nodes) == 2
    assert graph.created[0] not in graph.nodes


def test_apply_effect_chain_rolls_back_when_final_target_connection_fails(graph, monkeypatch):
    """Finding #1: the last edge into the optional target is inside the rollback unit.

    The existing mid-chain test only covers connections created inside the loop,
    so a failure on the final target edge would previously orphan every node.
    """
    connect_calls = []

    def fail_on_final_target(source_node, source_property, target_node, target_property):
        connect_calls.append(target_node)
        if target_node == "200":
            raise api.GraphAuthoringError("port not found", "PORT_NOT_FOUND")
        return None

    monkeypatch.setattr(effects, "connect_nodes", fail_on_final_target)
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.apply_effect_chain(
            EFFECTS, ["warp", "blur"], "100", "output", target_node="200", target_property="input"
        )
    assert error.value.code == "PORT_NOT_FOUND"
    # Both created nodes are removed; only the two originals remain.
    assert len(graph.nodes) == 2
    assert all(node not in graph.nodes for node in graph.created)
    assert connect_calls.count("200") == 1


def test_apply_effect_chain_wires_each_step_in_order(graph):
    result = effects.apply_effect_chain(EFFECTS, ["warp", "blur"], "100", "output", expected_graph_uid="graph-A")
    assert [step["step"] for step in result["steps"]] == ["warp", "blur"]
    assert [step["type_url"] for step in result["steps"]] == ["sbs::filter::warp", "sbs::compositing::blur"]
    assert result["head_node"] == result["steps"][-1]["node_id"]
    assert len(graph.created) == 2


def test_apply_effect_chain_resolves_every_recipe_before_creating_any_node(graph):
    before = len(graph.nodes)
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.apply_effect_chain(EFFECTS, ["warp", "sharpen"], "100", "output", expected_graph_uid="graph-A")
    assert error.value.code == "RECIPE_UNAVAILABLE"
    assert len(graph.nodes) == before


def test_apply_effect_chain_rolls_back_created_nodes_on_connection_failure(graph, monkeypatch):
    calls = []

    def fail_on_second(*_args, **_kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise api.GraphAuthoringError("port mismatch", "PORT_TYPE_MISMATCH")
        return None

    monkeypatch.setattr(effects, "connect_nodes", fail_on_second)
    before = len(graph.nodes)
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.apply_effect_chain(EFFECTS, ["warp", "blur"], "100", "output", expected_graph_uid="graph-A")
    assert error.value.code == "PORT_TYPE_MISMATCH"
    assert len(graph.nodes) == before


@pytest.mark.parametrize(
    "steps",
    [[], ["blur"] * 13, [""], ["ok", 7]],
)
def test_apply_effect_chain_rejects_invalid_step_lists(graph, steps):
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.apply_effect_chain(EFFECTS, steps, "100", "output", expected_graph_uid="graph-A")
    assert error.value.code == "INVALID_EFFECT_CHAIN"
    assert graph.created == []


def test_port_discovery_prefers_texture_then_conventional_names(monkeypatch):
    _install_property_module(monkeypatch)
    textured = _Node("1", inputs=["weird_name"], outputs=["strange"])
    ports = {
        "Input": [_property("weird_name", "Input", type_id="SDTypeTexture")],
        "Output": [_property("strange", "Output", type_id="SDTypeTexture")],
    }
    textured.getProperties = lambda category: ports[category]
    assert effects.primary_input(textured) == "weird_name"
    assert effects.primary_output(textured) == "strange"

    named = _Node("2", inputs=["source"], outputs=["result"])
    assert effects.primary_input(named) == "source"
    assert effects.primary_output(named) == "result"

    plain = _Node("3", inputs=["aaa"], outputs=["bbb"])
    assert effects.primary_input(plain) == "aaa"
    assert effects.primary_output(plain) == "bbb"


def test_port_discovery_fails_closed_when_absent(monkeypatch):
    _install_property_module(monkeypatch)
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.primary_input(_Node("4", inputs=[]))
    assert error.value.code == "PORT_NOT_FOUND"
    with pytest.raises(api.GraphAuthoringError) as error:
        effects.primary_output(_Node("5", outputs=[]))
    assert error.value.code == "PORT_NOT_FOUND"


def test_changed_graph_context_blocks_recipe_mutation(graph):
    from dcc_mcp_substance3d_designer.skill_support import typed_result

    result = typed_result(
        "apply", effects.apply_effect, EFFECTS, "blur", "100", "output", None, None, None, "stale-uid"
    )
    assert result["error"] == "GRAPH_CONTEXT_CHANGED"
    assert graph.created == []
