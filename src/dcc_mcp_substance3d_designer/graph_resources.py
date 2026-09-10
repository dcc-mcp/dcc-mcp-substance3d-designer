"""Explicit package-resource navigation and instance creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, graph_identity, page


def _package(path: str):
    resolved = api._sbs_path(path, must_exist=True)
    found = api.package_manager().getUserPackageFromFilePath(str(resolved))
    if found is None:
        raise api.GraphAuthoringError("Open the requested package first", "PACKAGE_NOT_OPEN")
    return found


def list_resources(package_path: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    page([], offset, limit)
    package = _package(package_path)
    rows = [
        {
            "resource_url": resource.getUrl(),
            "identifier": resource.getIdentifier(),
            "type_id": api.value(resource.getType(), "getId"),
            "embed_method": str(getattr(resource.getEmbedMethod(), "name", resource.getEmbedMethod())),
        }
        for resource in api.items(package.getChildrenResources(True))
    ]
    return {"package_path": api.package_path(package), **page(rows, offset, limit)}


def _resource(package: Any, resource_url: str) -> Any:
    if not isinstance(resource_url, str) or not resource_url or len(resource_url) > 1024:
        raise api.GraphAuthoringError("resource_url must be a bounded nonempty string", "INVALID_RESOURCE_URL")
    resource = package.findResourceFromUrl(resource_url)
    if resource is None:
        raise api.GraphAuthoringError("Resource was not found in the selected package", "RESOURCE_NOT_FOUND")
    return resource


def select_graph(package_path: str, resource_url: str) -> dict[str, str]:
    from sd.api.sdgraph import SDGraph

    graph = _resource(_package(package_path), resource_url)
    if not isinstance(graph, SDGraph):
        raise api.GraphAuthoringError("Resource is not a graph", "RESOURCE_NOT_GRAPH")
    uid = graph_identity(graph)
    api.application().getUIMgr().openResourceInEditor(graph)
    if graph_identity(api.active_graph()) != uid:
        raise api.GraphAuthoringError("Graph selection readback failed", "GRAPH_SELECTION_FAILED")
    return {"graph_uid": uid, "resource_url": graph.getUrl()}


def create_subgraph(graph_id: str, expected_graph_uid: str) -> dict[str, str]:
    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph

    graph = checked_graph(expected_graph_uid)
    package = graph.getPackage()
    identifier = api.require_identifier(graph_id, "graph_id")
    if any(resource.getIdentifier() == identifier for resource in api.items(package.getChildrenResources(True))):
        raise api.GraphAuthoringError("Resource identifier already exists", "DUPLICATE_RESOURCE_ID")
    resource = SDSBSCompGraph.sNew(package)
    try:
        resource.setIdentifier(identifier)
        return {"resource_url": resource.getUrl(), "graph_uid": graph_identity(resource)}
    except BaseException:
        resource.delete()
        raise


def instance_resource(package_path: str, resource_url: str, expected_graph_uid: str) -> dict[str, str]:
    from sd.api.sdgraph import SDGraph

    graph = checked_graph(expected_graph_uid)
    resource = _resource(_package(package_path), resource_url)
    # Walk referenced graphs before instancing: direct and indirect recursion fail.
    pending, seen = [resource], set()
    while pending:
        current = pending.pop()
        if not isinstance(current, SDGraph):
            continue
        uid = graph_identity(current)
        if uid == expected_graph_uid:
            raise api.GraphAuthoringError("Graph instances would be recursive", "GRAPH_RECURSION")
        if uid not in seen:
            seen.add(uid)
            pending.extend(node.getReferencedResource() for node in api.items(current.getNodes()))
    node = graph.newInstanceNode(resource)
    if node is None:
        raise api.GraphAuthoringError("Resource cannot be instanced in this graph", "RESOURCE_INSTANCE_FAILED")
    return {"graph_uid": expected_graph_uid, "node_id": api.node_identifier(node), "resource_url": resource.getUrl()}


def open_package(path: str) -> dict[str, Any]:
    resolved = api._sbs_path(path, must_exist=True)
    manager = api.package_manager()
    package = manager.getUserPackageFromFilePath(str(resolved))
    if package is not None:
        # Never reload an already open package and discard unsaved edits.
        return {"package_path": str(resolved), "saved": not package.isModified(), "already_open": True}
    package = manager.loadUserPackage(str(resolved), True, False)
    if package is None or Path(package.getFilePath()).resolve() != resolved:
        raise api.GraphAuthoringError("Package open readback failed", "PACKAGE_OPEN_FAILED")
    return {"package_path": str(resolved), "saved": not package.isModified(), "already_open": False}
