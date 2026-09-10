"""Read-only Designer graph contracts, based on the public SD SDK."""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api


def graph_identity(graph: Any) -> str:
    uid = api.value(graph, "getUID")
    if not isinstance(uid, str) or not uid:
        raise api.GraphAuthoringError("Graph identity is unavailable", "GRAPH_IDENTITY_UNAVAILABLE")
    return uid


def checked_graph(expected_graph_uid: str | None = None) -> Any:
    graph = api.active_graph()
    if expected_graph_uid is not None and graph_identity(graph) != expected_graph_uid:
        raise api.GraphAuthoringError("The active graph changed", "GRAPH_CONTEXT_CHANGED")
    return graph


def find_in_graph(graph: Any, node_id: str) -> Any:
    identifier = api.require_node_id(node_id)
    found = [node for node in api.items(graph.getNodes()) if api.node_identifier(node) == identifier]
    if len(found) != 1:
        code = "NODE_NOT_FOUND" if not found else "AMBIGUOUS_NODE_ID"
        raise api.GraphAuthoringError("Native node identity did not resolve uniquely", code)
    return found[0]


def property_types(prop: Any) -> list[dict[str, str]]:
    types = []
    for kind in api.items(prop.getTypes()):
        identifier = kind.getId()
        modifier = kind.getModifier()
        types.append({"id": str(identifier), "modifier": str(getattr(modifier, "name", modifier))})
    return types


def describe_property(prop: Any) -> dict[str, Any]:
    category = prop.getCategory()
    return {
        "id": prop.getId(),
        "label": prop.getLabel(),
        "description": prop.getDescription(),
        "category": str(getattr(category, "name", category)),
        "types": property_types(prop),
        "connectable": bool(prop.isConnectable()),
        "read_only": bool(prop.isReadOnly()),
        "variadic": bool(prop.isVariadic()),
        "default": api.json_value(prop.getDefaultValue()),
    }


def properties(owner: Any) -> dict[str, list[dict[str, Any]]]:
    from sd.api.sdproperty import SDPropertyCategory

    return {
        name: [describe_property(prop) for prop in api.items(owner.getProperties(category))]
        for name, category in (("inputs", SDPropertyCategory.Input), ("outputs", SDPropertyCategory.Output))
    }


def require_input(node: Any, identifier: str) -> Any:
    from sd.api.sdproperty import SDPropertyCategory

    prop = node.getPropertyFromId(api.require_property(identifier), SDPropertyCategory.Input)
    if prop is None:
        raise api.GraphAuthoringError("Input property was not found", "PARAMETER_NOT_FOUND")
    return prop


def page(rows: list[Any], offset: int, limit: int) -> dict[str, Any]:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise api.GraphAuthoringError("offset must be nonnegative and limit must be 1..200", "INVALID_PAGE")
    end = offset + limit
    return {"total": len(rows), "items": rows[offset:end], "next_offset": end if end < len(rows) else None}


def list_nodes(offset: int = 0, limit: int = 100) -> dict[str, Any]:
    page([], offset, limit)
    graph = checked_graph()
    rows = [
        {
            "node_id": api.node_identifier(node),
            "type_id": api.value(node.getDefinition(), "getId"),
            "label": api.json_value(node.getAnnotationPropertyValueFromId("label")),
        }
        for node in api.items(graph.getNodes())
    ]
    return {"graph_uid": graph_identity(graph), **page(rows, offset, limit)}


def list_node_types(query: str = "", offset: int = 0, limit: int = 100) -> dict[str, Any]:
    page([], offset, limit)
    if not isinstance(query, str) or len(query) > 128:
        raise api.GraphAuthoringError("query must contain at most 128 characters", "INVALID_QUERY")
    graph = checked_graph()
    rows = [
        {"type_id": definition.getId(), "label": definition.getLabel(), "description": definition.getDescription()}
        for definition in api.items(graph.getNodeDefinitions())
        if query.casefold() in (definition.getId() + " " + definition.getLabel()).casefold()
    ]
    return {"graph_uid": graph_identity(graph), **page(rows, offset, limit)}


def describe_node(node_id: str, expected_graph_uid: str | None = None) -> dict[str, Any]:
    graph = checked_graph(expected_graph_uid)
    node = find_in_graph(graph, node_id)
    return {
        "graph_uid": graph_identity(graph),
        "node_id": api.node_identifier(node),
        "type_id": api.value(node.getDefinition(), "getId"),
        **properties(node),
    }


def describe_node_type(type_id: str) -> dict[str, Any]:
    graph = checked_graph()
    found = [definition for definition in api.items(graph.getNodeDefinitions()) if definition.getId() == type_id]
    if len(found) != 1:
        raise api.GraphAuthoringError("Node definition was not found uniquely", "NODE_TYPE_UNAVAILABLE")
    return {"graph_uid": graph_identity(graph), "type_id": type_id, **properties(found[0])}
