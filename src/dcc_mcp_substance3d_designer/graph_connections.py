"""Exact-edge connection operations with preflight and SDK readback."""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, find_in_graph, graph_identity, property_types


def edge(connection: Any) -> tuple[str, str, str, str]:
    output_node, output = connection.getOutputPropertyNode(), connection.getOutputProperty()
    input_node, input_ = connection.getInputPropertyNode(), connection.getInputProperty()
    # Designer 16 can report these endpoint getters in connection-relative
    # order. Property categories identify the actual producer and consumer.
    output_category = api.value(api.value(output, "getCategory"), "name")
    input_category = api.value(api.value(input_, "getCategory"), "name")
    if output_category == "Input" and input_category == "Output":
        output_node, output, input_node, input_ = input_node, input_, output_node, output
    return (
        api.node_identifier(output_node),
        output.getId(),
        api.node_identifier(input_node),
        input_.getId(),
    )


def _ports(graph: Any, source_node: str, source_property: str, target_node: str, target_property: str):
    from sd.api.sdproperty import SDPropertyCategory

    source = find_in_graph(graph, source_node)
    target = find_in_graph(graph, target_node)
    output = source.getPropertyFromId(api.require_property(source_property), SDPropertyCategory.Output)
    input_ = target.getPropertyFromId(api.require_property(target_property), SDPropertyCategory.Input)
    if output is None or input_ is None:
        raise api.GraphAuthoringError("The requested input or output port does not exist", "PORT_NOT_FOUND")
    return source, output, target, input_


def _compatible(output: Any, input_: Any) -> bool:
    sources, targets = property_types(output), property_types(input_)
    if not sources or not targets:
        raise api.GraphAuthoringError("Port type metadata is unavailable", "PORT_TYPE_UNAVAILABLE")
    return any(
        source["id"] == target["id"] and not (source["modifier"] == "Varying" and target["modifier"] == "Uniform")
        for source in sources
        for target in targets
    )


def _cycle(graph: Any, source: str, target: str) -> bool:
    from sd.api.sdproperty import SDPropertyCategory

    adjacency: dict[str, set[str]] = {}
    for node in api.items(graph.getNodes()):
        for prop in api.items(node.getProperties(SDPropertyCategory.Output)):
            for connection in api.items(node.getPropertyConnections(prop)):
                a, _, b, _ = edge(connection)
                adjacency.setdefault(a, set()).add(b)
    pending, seen = [target], set()
    while pending:
        current = pending.pop()
        if current == source:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(adjacency.get(current, ()))
    return False


def validate_connection(
    source_node: str,
    source_property: str,
    target_node: str,
    target_property: str,
    expected_graph_uid: str | None = None,
) -> dict[str, Any]:
    graph = checked_graph(expected_graph_uid)
    source, output, target, input_ = _ports(graph, source_node, source_property, target_node, target_property)
    if not output.isConnectable() or not input_.isConnectable():
        raise api.GraphAuthoringError("Both properties must be connectable", "PORT_NOT_CONNECTABLE")
    # Designer texture inputs are value-read-only: pixels come from an edge,
    # rather than an assignable SDValue. isConnectable governs their wiring.
    texture_input = any(item["id"] == "SDTypeTexture" for item in property_types(input_))
    if input_.isReadOnly() and not texture_input:
        raise api.GraphAuthoringError("Target input is read-only", "PROPERTY_READ_ONLY")
    if not _compatible(output, input_):
        raise api.GraphAuthoringError("Port types are incompatible without conversion", "PORT_TYPE_MISMATCH")
    requested = (source_node, source_property, target_node, target_property)
    incoming = [edge(connection) for connection in api.items(target.getPropertyConnections(input_))]
    if incoming and incoming != [requested]:
        raise api.GraphAuthoringError(
            "Target input already has a connection; disconnect it explicitly", "INPUT_CONNECTED"
        )
    if source_node == target_node or _cycle(graph, source_node, target_node):
        raise api.GraphAuthoringError("Connection would create a cycle", "GRAPH_CYCLE")
    return {
        "graph_uid": graph_identity(graph),
        "source_node": source_node,
        "source_property": source_property,
        "target_node": target_node,
        "target_property": target_property,
        "already_connected": incoming == [requested],
    }


def connect_nodes(
    source_node: str,
    source_property: str,
    target_node: str,
    target_property: str,
    expected_graph_uid: str | None = None,
) -> dict[str, Any]:
    context = validate_connection(source_node, source_property, target_node, target_property, expected_graph_uid)
    graph = checked_graph(context["graph_uid"])
    source, output, target, input_ = _ports(graph, source_node, source_property, target_node, target_property)
    requested = (source_node, source_property, target_node, target_property)
    if not context["already_connected"]:
        source.newPropertyConnectionFromId(source_property, target, target_property)
    observed = [edge(connection) for connection in api.items(target.getPropertyConnections(input_))]
    if observed != [requested]:
        raise api.GraphAuthoringError("Designer connection readback did not match", "CONNECTION_READBACK_FAILED")
    return context


def disconnect_nodes(
    source_node: str,
    source_property: str,
    target_node: str,
    target_property: str,
    expected_graph_uid: str | None = None,
) -> dict[str, Any]:
    graph = checked_graph(expected_graph_uid)
    source, output, target, input_ = _ports(graph, source_node, source_property, target_node, target_property)
    requested = (source_node, source_property, target_node, target_property)
    # Input-side handles can be connection-relative in Designer 16 and fail
    # disconnect() with ItemNotFound. Use the producer's exact edge handle.
    matches = [
        connection for connection in api.items(source.getPropertyConnections(output)) if edge(connection) == requested
    ]
    if len(matches) > 1:
        raise api.GraphAuthoringError("Connection identity is ambiguous", "AMBIGUOUS_CONNECTION")
    if matches:
        matches[0].disconnect()
    # The disconnected connection handle is invalid. Re-query instead of reusing it.
    if any(edge(connection) == requested for connection in api.items(target.getPropertyConnections(input_))):
        raise api.GraphAuthoringError("Designer did not disconnect the edge", "DISCONNECT_READBACK_FAILED")
    return {
        "graph_uid": graph_identity(graph),
        "source_node": source_node,
        "source_property": source_property,
        "target_node": target_node,
        "target_property": target_property,
        "disconnected": bool(matches),
    }
