import sys
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError
from dcc_mcp_substance3d_designer.graph_evaluation import validate_resolution_budget


@pytest.fixture
def graph(monkeypatch):
    module = ModuleType("sd.api.sdproperty")
    module.SDPropertyCategory = NS(Input="Input")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    node = NS(
        getPropertyFromId=lambda *a: object(),
        getPropertyGraph=lambda p: None,
        getPropertyValue=lambda p: [0, 0],
        getPropertyInheritanceMethod=lambda p: NS(name="RelativeToParent"),
    )
    return NS(
        getPropertyFromId=lambda *a: object(),
        getPropertyInheritanceMethod=lambda p: NS(name="Absolute"),
        getPropertyValue=lambda p: [10, 10],
        getNodes=lambda: [node],
    )


def test_parent_relative_size_within_budget(graph):
    validate_resolution_budget(graph, 1024)


@pytest.mark.parametrize("failure", ["root_size", "root_inherited", "node_size", "dynamic", "input_growth"])
def test_unknown_or_excess_resolution_rejected(graph, failure):
    node = graph.getNodes()[0]
    if failure == "root_size":
        graph.getPropertyValue = lambda p: [13, 10]
    elif failure == "root_inherited":
        graph.getPropertyInheritanceMethod = lambda p: NS(name="RelativeToParent")
    elif failure == "node_size":
        node.getPropertyValue = lambda p: [1, 0]
    elif failure == "dynamic":
        node.getPropertyGraph = lambda p: object()
    else:
        node.getPropertyInheritanceMethod = lambda p: NS(name="RelativeToInput")
        node.getPropertyValue = lambda p: [1, 0]
    with pytest.raises(GraphAuthoringError):
        validate_resolution_budget(graph, 1024)
