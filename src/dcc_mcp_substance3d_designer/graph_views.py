"""Read native graph-view identities without Qt pointer wrapping or UI input."""

from __future__ import annotations

import math
from typing import Any

from . import graph_authoring as api
from .graph_inspection import find_in_graph, graph_identity


def _manager():
    manager = api.application().getUIMgr()
    required = ("getGraphViewIDCount", "getGraphViewIDAt", "getGraphFromGraphViewID")
    if manager is None or any(not callable(getattr(manager, name, None)) for name in required):
        raise api.GraphAuthoringError("Native graph-view inspection is unavailable", "GRAPH_VIEW_API_UNAVAILABLE")
    return manager


def _view_ids(manager) -> list[int]:
    count = manager.getGraphViewIDCount()
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 64:
        raise api.GraphAuthoringError("Graph-view inventory exceeds the bounded query", "GRAPH_VIEW_LIMIT")
    result = [manager.getGraphViewIDAt(index) for index in range(count)]
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in result):
        raise api.GraphAuthoringError("Native graph-view identity is invalid", "INVALID_GRAPH_VIEW_ID")
    if len(set(result)) != len(result):
        raise api.GraphAuthoringError("Native graph-view identity is ambiguous", "AMBIGUOUS_GRAPH_VIEW")
    return result


def list_graph_views() -> dict[str, Any]:
    manager = _manager()
    current = manager.getCurrentGraph()
    current_uid = graph_identity(current) if current is not None else None
    result = []
    selection = getattr(manager, "getGraphSelectedNodesFromGraphViewID", None)
    for view_id in _view_ids(manager):
        graph = manager.getGraphFromGraphViewID(view_id)
        if graph is None:
            continue
        uid = graph_identity(graph)
        selected = api.items(selection(view_id)) if callable(selection) else None
        result.append(
            {
                "graph_view_id": str(view_id),
                "graph_uid": uid,
                "identifier": str(api.value(graph, "getIdentifier") or ""),
                "is_current_graph": uid == current_uid,
                "selected_node_ids": [api.node_identifier(node) for node in selected[:200]]
                if selected is not None
                else None,
                "selection_truncated": len(selected) > 200 if selected is not None else False,
            }
        )
    return {
        "views": result,
        "count": len(result),
        "native_capabilities": {
            name: callable(getattr(manager, name, None))
            for name in (
                "getGraphNodeBBox",
                "focusGraphNode",
                "registerGraphViewCreatedCallback",
                "registerExplorerSelectionChangedCallback",
                "unregisterCallback",
            )
        },
    }


def get_graph_view_node_bounds(graph_view_id: str, expected_graph_uid: str, node_ids: list[str]) -> dict[str, Any]:
    if (
        not isinstance(graph_view_id, str)
        or not graph_view_id.isascii()
        or not graph_view_id.isdigit()
        or len(graph_view_id) > 20
    ):
        raise api.GraphAuthoringError("Use a graph_view_id from list_graph_views", "INVALID_GRAPH_VIEW_ID")
    api.require_node_id(expected_graph_uid, "expected_graph_uid")
    if not isinstance(node_ids, list) or not 1 <= len(node_ids) <= 128:
        raise api.GraphAuthoringError("node_ids must contain 1..128 unique native IDs", "INVALID_NODE_IDS")
    for node_id in node_ids:
        api.require_node_id(node_id)
    if len(set(node_ids)) != len(node_ids):
        raise api.GraphAuthoringError("node_ids must be unique", "INVALID_NODE_IDS")
    manager = _manager()
    native_id = int(graph_view_id)
    # Never forward caller-supplied pointer-like IDs until the host enumerates them.
    if native_id not in _view_ids(manager):
        raise api.GraphAuthoringError("The graph view is no longer open", "GRAPH_VIEW_NOT_FOUND")
    graph = manager.getGraphFromGraphViewID(native_id)
    if graph is None or graph_identity(graph) != expected_graph_uid:
        raise api.GraphAuthoringError("The graph view now belongs to another graph", "GRAPH_CONTEXT_CHANGED")
    bounds_method = getattr(manager, "getGraphNodeBBox", None)
    if not callable(bounds_method):
        raise api.GraphAuthoringError("Native node bounds are unavailable", "GRAPH_VIEW_API_UNAVAILABLE")
    nodes = [find_in_graph(graph, node_id) for node_id in node_ids]
    bounds = []
    for node_id, node in zip(node_ids, nodes):
        box = bounds_method(native_id, node)
        values = [float(getattr(box, field)) for field in ("x", "y", "z", "w")]
        if any(not math.isfinite(value) for value in values) or values[2] < 0 or values[3] < 0:
            raise api.GraphAuthoringError("Native node bounds are invalid", "INVALID_GRAPH_VIEW_BOUNDS")
        bounds.append({"node_id": node_id, "x": values[0], "y": values[1], "width": values[2], "height": values[3]})
    return {
        "graph_view_id": graph_view_id,
        "graph_uid": expected_graph_uid,
        "coordinate_space": "native_graph_view",
        "bounds": bounds,
    }
