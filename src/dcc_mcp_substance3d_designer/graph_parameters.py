"""Graph-input exposure through public property/function graph APIs."""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, find_in_graph, graph_identity, property_types, require_input


def expose_parameter(
    node_id: str, parameter: str, exposed_id: str, expected_graph_uid: str | None = None
) -> dict[str, Any]:
    from sd.api.sdproperty import SDPropertyCategory
    from sd.api.sdvaluestring import SDValueString

    graph = checked_graph(expected_graph_uid)
    node = find_in_graph(graph, node_id)
    prop = require_input(node, parameter)
    public_id = api.require_identifier(exposed_id, "exposed_id")
    if prop.isReadOnly() or api.items(node.getPropertyConnections(prop)) or node.getPropertyGraph(prop) is not None:
        raise api.GraphAuthoringError("Exposure requires a writable constant input", "PARAMETER_NOT_CONSTANT")
    if graph.getPropertyFromId(public_id, SDPropertyCategory.Input) is not None:
        raise api.GraphAuthoringError("Graph input already exists", "DUPLICATE_GRAPH_INPUT")
    original = node.getPropertyValue(prop)
    if original is None:
        raise api.GraphAuthoringError("Input has no constant value", "PARAMETER_VALUE_UNAVAILABLE")
    kind = original.getType().getId()
    suffixes = {
        "float": "float1",
        "float2": "float2",
        "float3": "float3",
        "float4": "float4",
        "int": "integer1",
        "int2": "integer2",
        "bool": "bool",
    }
    if kind not in suffixes:
        raise api.GraphAuthoringError("Input type has no supported variable reader", "EXPOSE_TYPE_UNSUPPORTED")
    # Keep an independent SDK value: creating a function resets the node input.
    original = api.typed_value(kind, api.json_value(original))
    function = None
    public = None
    try:
        # Adobe sample_sbs_parameter_function uses this graph class; creation resets
        # an existing binding, which is why the constant-input guard is mandatory.
        function = node.newPropertyGraph(prop, "SDSBSFunctionGraph")
        if function is None:
            raise api.GraphAuthoringError("Property function graph is unavailable", "EXPOSE_API_UNAVAILABLE")
        reader_id = "sbs::function::get_" + suffixes[kind]
        if reader_id not in {definition.getId() for definition in api.items(function.getNodeDefinitions())}:
            raise api.GraphAuthoringError(
                "SDK does not advertise the required variable reader", "EXPOSE_API_UNAVAILABLE"
            )
        reader = function.newNode(reader_id)
        inputs = [
            item
            for item in api.items(reader.getProperties(SDPropertyCategory.Input))
            if not item.isReadOnly() and {t["id"] for t in property_types(item)} == {"string"}
        ]
        outputs = [
            item
            for item in api.items(reader.getProperties(SDPropertyCategory.Output))
            if kind in {t["id"] for t in property_types(item)}
        ]
        if len(inputs) != 1 or len(outputs) != 1:
            raise api.GraphAuthoringError("Variable reader metadata is ambiguous", "EXPOSE_API_UNAVAILABLE")
        # Discover the SDK input ID rather than assuming the XML serialization name.
        variable_port = inputs[0]
        reader.setInputPropertyValueFromId(variable_port.getId(), SDValueString.sNew(public_id))
        if api.json_value(reader.getPropertyValue(variable_port)) != public_id:
            raise api.GraphAuthoringError("Variable reader did not retain its binding", "EXPOSE_READBACK_FAILED")
        public = graph.newProperty(public_id, original.getType(), SDPropertyCategory.Input)
        if public is None:
            raise api.GraphAuthoringError("SDK rejected the graph input", "EXPOSE_API_UNAVAILABLE")
        graph.setPropertyValue(public, original)
        function.setOutputNode(reader, True)
        if (
            api.json_value(graph.getPropertyValue(public)) != api.json_value(original)
            or node.getPropertyGraph(prop) is None
            or [api.node_identifier(item) for item in api.items(function.getOutputNodes())]
            != [api.node_identifier(reader)]
        ):
            raise api.GraphAuthoringError("Graph input binding readback failed", "EXPOSE_READBACK_FAILED")
        return {
            "graph_uid": graph_identity(graph),
            "node_id": api.node_identifier(node),
            "parameter": prop.getId(),
            "exposed_id": public_id,
            "value_type": kind,
            "reader_node_id": api.node_identifier(reader),
        }
    except BaseException:
        # Only objects created by this call are removed. Restore the pre-call constant.
        if function is not None:
            node.deletePropertyGraph(prop)
        if public is not None:
            graph.deleteProperty(public)
        node.setInputPropertyValueFromId(prop.getId(), original)
        raise


def set_graph_parameter(parameter: str, value_type: str, raw: Any, expected_graph_uid: str) -> dict:
    graph = checked_graph(expected_graph_uid)
    prop = require_input(graph, parameter)
    if prop.isReadOnly():
        raise api.GraphAuthoringError("Graph input is read-only", "PROPERTY_READ_ONLY")
    wrapped = api.typed_value(value_type, raw)
    if wrapped.getType().getId() not in {kind["id"] for kind in property_types(prop)}:
        raise api.GraphAuthoringError("Value type is not supported by the graph input", "PARAMETER_TYPE_MISMATCH")
    expected = api.json_value(wrapped)
    graph.setPropertyValue(prop, wrapped)
    actual = api.json_value(graph.getPropertyValue(prop))
    if actual != expected:
        raise api.GraphAuthoringError("Graph parameter readback failed", "PARAMETER_READBACK_FAILED")
    return {"graph_uid": expected_graph_uid, "parameter": prop.getId(), "value": actual}
