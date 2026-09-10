"""Select an explicit graph in an already loaded package."""

from __future__ import annotations

from pathlib import Path

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import GraphAuthoringError, application, require_identifier
from dcc_mcp_substance3d_designer.skill_support import typed_result


def select_graph(package_path: str, graph_id: str) -> dict:
    graph_id = require_identifier(graph_id, "graph_id")
    path = Path(package_path).resolve()
    app = application()
    packages = [
        p for p in app.getPackageMgr().getUserPackages() if p.getFilePath() and Path(p.getFilePath()).resolve() == path
    ]
    if len(packages) != 1:
        raise GraphAuthoringError("Expected one loaded package at the explicit path", "PACKAGE_NOT_FOUND")
    graph = packages[0].findResourceFromUrl(graph_id)
    if graph is None or not callable(getattr(graph, "getNodes", None)):
        raise GraphAuthoringError("Graph not found in the loaded package", "GRAPH_NOT_FOUND")
    app.getUIMgr().openResourceInEditor(graph)
    return {"package_path": str(path), "graph_id": graph_id}


@skill_entry
def main(package_path: str, graph_id: str | None = None, resource_url: str | None = None, **_kwargs):
    if resource_url is not None:
        from dcc_mcp_substance3d_designer.graph_resources import select_graph as select_resource

        return typed_result("Selected Designer graph", select_resource, package_path, resource_url)
    return typed_result("Selected Designer graph", select_graph, package_path, graph_id)
