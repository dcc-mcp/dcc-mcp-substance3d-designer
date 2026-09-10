"""Resource navigation preserves edits and rejects recursive graph instances."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_substance3d_designer import graph_authoring as api
from dcc_mcp_substance3d_designer import graph_resources as resources


class Graph:
    def __init__(self, uid):
        self.uid, self.nodes = uid, []

    def getUID(self):
        return self.uid

    def getNodes(self):
        return self.nodes

    def getUrl(self):
        return "pkg://" + self.uid

    def newInstanceNode(self, resource):
        node = SimpleNamespace(getIdentifier=lambda: "123", getReferencedResource=lambda: resource)
        self.nodes.append(node)
        return node


@pytest.fixture
def host(monkeypatch):
    module = ModuleType("sd.api.sdgraph")
    module.SDGraph = Graph
    monkeypatch.setitem(sys.modules, module.__name__, module)
    target, resource = Graph("target"), Graph("resource")
    package = SimpleNamespace(findResourceFromUrl=lambda url: resource)
    monkeypatch.setattr(resources, "_package", lambda path: package)
    monkeypatch.setattr(api, "active_graph", lambda: target)
    return target, resource, package


def test_resource_instance_returns_native_handle(host):
    target, resource, _ = host
    assert resources.instance_resource("package.sbs", resource.getUrl(), "target")["node_id"] == "123"
    assert target.nodes[0].getReferencedResource() is resource


@pytest.mark.parametrize("indirect", [False, True])
def test_resource_instance_rejects_recursion_before_mutation(host, indirect):
    target, resource, package = host
    if indirect:
        resource.nodes.append(SimpleNamespace(getReferencedResource=lambda: target))
    else:
        package.findResourceFromUrl = lambda url: target
    with pytest.raises(api.GraphAuthoringError) as error:
        resources.instance_resource("package.sbs", "pkg://resource", "target")
    assert error.value.code == "GRAPH_RECURSION" and target.nodes == []


def test_graph_selection_requires_readback(host, monkeypatch):
    _, resource, _ = host
    calls = []
    monkeypatch.setattr(
        api,
        "application",
        lambda: SimpleNamespace(
            getUIMgr=lambda: SimpleNamespace(openResourceInEditor=lambda graph: calls.append(graph))
        ),
    )
    with pytest.raises(api.GraphAuthoringError) as error:
        resources.select_graph("package.sbs", resource.getUrl())
    assert error.value.code == "GRAPH_SELECTION_FAILED" and calls == [resource]
    monkeypatch.setattr(api, "active_graph", lambda: resource)
    assert resources.select_graph("package.sbs", resource.getUrl())["graph_uid"] == "resource"


def test_subgraph_duplicate_rejected_before_creation(host, monkeypatch):
    target, _, package = host
    target.getPackage = lambda: package
    package.getChildrenResources = lambda recursive: [SimpleNamespace(getIdentifier=lambda: "material")]
    module = ModuleType("sd.api.sbs.sdsbscompgraph")
    module.SDSBSCompGraph = SimpleNamespace(sNew=lambda package: pytest.fail("Must not create duplicate"))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(api.GraphAuthoringError) as error:
        resources.create_subgraph("material", "target")
    assert error.value.code == "DUPLICATE_RESOURCE_ID"


def test_sdk_value_array_uses_get_item():
    array = SimpleNamespace(getSize=lambda: 2, getItem=lambda index: ["a", "b"][index])
    assert api.items(array) == ["a", "b"]


def test_function_node_type_is_valid_without_compositing_namespace():
    assert api.require_type_url("sbs::add") == "sbs::add"
