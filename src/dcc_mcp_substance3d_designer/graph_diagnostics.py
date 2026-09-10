"""Read-only ownership and per-node diagnostics from public Designer SDK state."""

from . import graph_authoring as api
from .graph_inspection import checked_graph, graph_identity, page, property_types


def inspect_graph_session(offset: int = 0, limit: int = 100) -> dict:
    from sd.api.sdproperty import SDPropertyCategory

    graph = checked_graph()
    package = graph.getPackage()
    nodes = api.items(graph.getNodes())
    selected = page(nodes, offset, limit)
    rows = []
    for node in selected["items"]:
        inputs = []
        for prop in api.items(node.getProperties(SDPropertyCategory.Input)):
            inputs.append(
                {
                    "id": prop.getId(),
                    "types": property_types(prop),
                    "value": api.json_value(node.getPropertyValue(prop)),
                    "connected": bool(api.items(node.getPropertyConnections(prop))),
                    "function_bound": node.getPropertyGraph(prop) is not None,
                    "read_only": prop.isReadOnly(),
                }
            )
        resource = node.getReferencedResource()
        rows.append(
            {
                "node_id": api.node_identifier(node),
                "type_id": node.getDefinition().getId(),
                "resource_url": resource.getUrl() if resource else None,
                "inputs": inputs,
            }
        )
    interop = api.application().getAppInteropMgr()
    return {
        "graph_uid": graph_identity(graph),
        "graph_identifier": graph.getIdentifier(),
        "resource_url": graph.getUrl(),
        "package_path": api.package_path(package),
        "package_modified": package.isModified(),
        "node_count": len(nodes),
        "output_ids": [api.json_value(item) for item in api.items(graph.getOutputIdentifiers())],
        "graph_inputs": [
            {"id": prop.getId(), "types": property_types(prop), "value": api.json_value(graph.getPropertyValue(prop))}
            for prop in api.items(graph.getProperties(SDPropertyCategory.Input))
        ],
        "nodes": rows,
        "next_offset": selected["next_offset"],
        "interop_last_error": interop.getLastErrorMessage() if interop else None,
        "diagnostic_scope": "SDK properties and application interop error; not a node compiler log",
    }
