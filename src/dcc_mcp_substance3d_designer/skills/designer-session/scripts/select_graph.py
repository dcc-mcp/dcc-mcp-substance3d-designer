"""Open a package graph in the editor and verify its active graph identity."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_resources import select_graph
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(package_path: str, resource_url: str, **_kwargs):
    return typed_result(
        "Open a package graph in the editor and verify its active graph identity.",
        select_graph,
        package_path,
        resource_url,
    )
