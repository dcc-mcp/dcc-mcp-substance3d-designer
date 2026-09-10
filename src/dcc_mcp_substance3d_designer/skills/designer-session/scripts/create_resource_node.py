"""Instance a shipped Designer resource without arbitrary package paths."""

from __future__ import annotations

import re
from pathlib import Path

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import (
    GraphAuthoringError,
    active_graph,
    application,
    name_node,
    require_identifier,
)
from dcc_mcp_substance3d_designer.skill_support import typed_result


def create_resource_node(package_name: str, resource_id: str, node_id: str) -> dict:
    if not isinstance(package_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}\.sbs", package_name):
        raise GraphAuthoringError("Expected a shipped .sbs package filename", "INVALID_PACKAGE_NAME")
    resource_id = require_identifier(resource_id, "resource_id")
    node_id = require_identifier(node_id, "node_id")
    graph = active_graph()
    if any(node.getIdentifier() == node_id for node in graph.getNodes()):
        raise GraphAuthoringError("Node identifier already exists", "DUPLICATE_NODE_ID")

    from sd.api.sdapplication import SDApplicationPath
    from sd.api.sdproperty import SDPropertyCategory

    app = application()
    root = (Path(app.getPath(SDApplicationPath.DefaultResourcesDir)) / "packages").resolve()
    path = (root / package_name).resolve()
    if path.parent != root or not path.is_file():
        raise GraphAuthoringError("Shipped resource package not found", "RESOURCE_NOT_FOUND")
    package = app.getPackageMgr().loadUserPackage(str(path), True)
    resource = package.findResourceFromUrl(resource_id)
    if resource is None:
        raise GraphAuthoringError("Resource identifier not found in package", "RESOURCE_NOT_FOUND")
    node = graph.newInstanceNode(resource)
    if node is None:
        raise GraphAuthoringError("Designer rejected resource instance", "NODE_TYPE_UNAVAILABLE")
    try:
        assigned = name_node(node, node_id)
        return {
            "node_id": node.getIdentifier(),
            "requested_node_id": node_id,
            "identifier_assigned": assigned,
            "package_name": package_name,
            "resource_id": resource_id,
            "inputs": [prop.getId() for prop in node.getProperties(SDPropertyCategory.Input)],
            "outputs": [prop.getId() for prop in node.getProperties(SDPropertyCategory.Output)],
        }
    except BaseException:
        graph.deleteNode(node)
        raise


@skill_entry
def main(package_name: str, resource_id: str, node_id: str, **_kwargs):
    return typed_result(
        "Created shipped Designer resource node", create_resource_node, package_name, resource_id, node_id
    )
