"""Export the active Designer graph as bounded, typed JSON state."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _value(obj: Any, *names: str) -> Any:
    for name in names:
        member = getattr(obj, name, None)
        if member is not None:
            return member() if callable(member) else member
    return None


def _sequence(value: Any) -> list[Any]:
    resolved = _value(value, "get")
    if resolved is not None and resolved is not value:
        value = resolved
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        pass
    size = _value(value, "getSize")
    if isinstance(size, int):
        item = getattr(value, "getItem", None)
        if callable(item):
            return [item(index) for index in range(size)]
        return [value[index] for index in range(size)]
    return []


def _json_value(value: Any) -> Any:
    resolved = _value(value, "get")
    if resolved is not None and resolved is not value:
        return _json_value(resolved)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    components = []
    for name in ("r", "g", "b", "a") if hasattr(value, "r") else ("x", "y", "z", "w"):
        component = _value(value, name)
        if component is None:
            break
        components.append(component)
    if components:
        return [_json_value(component) for component in components]
    identifier = _value(value, "getId", "getIdentifier")
    if identifier is not None:
        return str(identifier)
    return {"type": type(value).__name__}


def _node_id(node: Any) -> str:
    return str(_value(node, "getIdentifier", "getId", "getUID") or "unknown")


def _position(node: Any) -> list[float] | None:
    position = _value(node, "getPosition")
    if position is None:
        return None
    x = _value(position, "x")
    y = _value(position, "y")
    if x is None or y is None:
        return None
    return [float(x), float(y)]


def _usage_state(node: Any) -> list[dict[str, str]]:
    annotation = getattr(node, "getAnnotationPropertyValueFromId", None)
    if not callable(annotation):
        return []
    usages = []
    for usage in _sequence(annotation("usages")):
        usages.append(
            {
                "usage": str(_value(usage, "getUsage") or ""),
                "channels": str(_value(usage, "getChannels") or ""),
                "color_space": str(_value(usage, "getColorSpace") or ""),
            }
        )
    return usages


def _export_graph_state(include_parameters: bool):
    import sd  # Lazy import: requires Designer's embedded Python.
    from sd.api.sdproperty import SDPropertyCategory

    app = sd.getContext().getSDApplication()
    ui_manager = _value(app, "getUIMgr")
    graph = _value(ui_manager, "getCurrentGraph") if ui_manager else None
    if graph is None:
        return skill_error("No active Designer graph", "NO_ACTIVE_GRAPH")

    nodes = _sequence(_value(graph, "getNodes"))
    node_states = []
    connections = []
    graph_outputs = []
    for node in nodes:
        definition = _value(node, "getDefinition")
        input_properties = _sequence(node.getProperties(SDPropertyCategory.Input))
        output_properties = _sequence(node.getProperties(SDPropertyCategory.Output))
        parameters = {}
        if include_parameters:
            for prop in input_properties:
                prop_id = str(_value(prop, "getId") or "")
                if prop_id:
                    parameters[prop_id] = _json_value(node.getPropertyValue(prop))
        node_states.append(
            {
                "id": _node_id(node),
                "type_url": str(_value(definition, "getId", "getIdentifier") or "unknown"),
                "position": _position(node),
                "parameters": parameters,
                "outputs": [str(_value(prop, "getId") or "") for prop in output_properties],
            }
        )
        for prop in output_properties:
            source_property = str(_value(prop, "getId") or "")
            for connection in _sequence(node.getPropertyConnections(prop)):
                input_node = _value(connection, "getInputPropertyNode", "getInputNode")
                output_node = _value(connection, "getOutputPropertyNode", "getOutputNode")
                if input_node is node and output_node is not None:
                    target_node = output_node
                    target_property = _value(connection, "getOutputProperty")
                else:
                    target_node = input_node
                    target_property = _value(connection, "getInputProperty")
                connections.append(
                    {
                        "source_node": _node_id(node),
                        "source_property": source_property,
                        "target_node": _node_id(target_node),
                        "target_property": str(_value(target_property, "getId") or ""),
                    }
                )
        usages = _usage_state(node)
        if usages:
            graph_outputs.append({"node_id": _node_id(node), "usages": usages})

    return skill_success(
        "Exported active Designer graph state",
        graph={
            "identifier": str(_value(graph, "getIdentifier", "getName") or "unknown"),
            "node_count": len(nodes),
            "nodes": node_states,
            "connections": connections,
            "outputs": graph_outputs,
        },
    )


@skill_entry
def main(include_parameters: bool = True, **_kwargs):
    try:
        return _export_graph_state(bool(include_parameters))
    except Exception as exc:  # Host SDK errors are intentionally redacted.
        return skill_error("Designer graph state export failed", type(exc).__name__)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
