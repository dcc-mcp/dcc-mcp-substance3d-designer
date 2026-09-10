from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dcc_mcp_substance3d_designer import graph_views as views
from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError


@pytest.fixture
def host(monkeypatch):
    graph = MagicMock()
    graph.getUID.return_value = "graph_1"
    graph.getIdentifier.return_value = "material"
    node = MagicMock()
    node.getIdentifier.return_value = "node_1"
    graph.getNodes.return_value = [node]
    manager = MagicMock()
    manager.getCurrentGraph.return_value = graph
    manager.getGraphViewIDCount.return_value = 1
    manager.getGraphViewIDAt.return_value = 1234
    manager.getGraphFromGraphViewID.return_value = graph
    manager.getGraphSelectedNodesFromGraphViewID.return_value = [node]
    manager.getGraphNodeBBox.return_value = SimpleNamespace(x=-10, y=20, z=80, w=60)
    monkeypatch.setattr(views.api, "application", lambda: SimpleNamespace(getUIMgr=lambda: manager))
    return manager, graph, node


def test_inventory_uses_native_identity_and_selection(host):
    result = views.list_graph_views()
    assert result["views"] == [
        {
            "graph_view_id": "1234",
            "graph_uid": "graph_1",
            "identifier": "material",
            "is_current_graph": True,
            "selected_node_ids": ["node_1"],
            "selection_truncated": False,
        }
    ]


def test_bounds_preserve_width_height_semantics(host):
    manager, graph, node = host
    result = views.get_graph_view_node_bounds("1234", "graph_1", ["node_1"])
    assert result["bounds"] == [{"node_id": "node_1", "x": -10, "y": 20, "width": 80, "height": 60}]
    manager.getGraphNodeBBox.assert_called_once_with(1234, node)


@pytest.mark.parametrize(
    "view,uid,nodes,code",
    [
        ("8888", "graph_1", ["node_1"], "GRAPH_VIEW_NOT_FOUND"),
        ("1234", "other_graph", ["node_1"], "GRAPH_CONTEXT_CHANGED"),
        ("1234", "graph_1", ["node_1", "node_1"], "INVALID_NODE_IDS"),
        ("1234", "graph_1", [], "INVALID_NODE_IDS"),
        ("1234", "graph_1", ["missing"], "NODE_NOT_FOUND"),
        ("-1", "graph_1", ["node_1"], "INVALID_GRAPH_VIEW_ID"),
    ],
)
def test_bad_or_stale_identity_never_reaches_bounds(host, view, uid, nodes, code):
    with pytest.raises(GraphAuthoringError) as exc:
        views.get_graph_view_node_bounds(view, uid, nodes)
    assert exc.value.code == code
    host[0].getGraphNodeBBox.assert_not_called()


def test_inventory_is_bounded(host):
    host[0].getGraphViewIDCount.return_value = 65
    with pytest.raises(GraphAuthoringError, match="bounded query"):
        views.list_graph_views()
    host[0].getGraphViewIDAt.assert_not_called()


def test_invalid_native_bounds_fail_closed(host):
    host[0].getGraphNodeBBox.return_value = SimpleNamespace(x=0, y=0, z=float("nan"), w=1)
    with pytest.raises(GraphAuthoringError) as exc:
        views.get_graph_view_node_bounds("1234", "graph_1", ["node_1"])
    assert exc.value.code == "INVALID_GRAPH_VIEW_BOUNDS"
