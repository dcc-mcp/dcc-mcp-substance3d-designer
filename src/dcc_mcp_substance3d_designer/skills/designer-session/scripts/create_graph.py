"""Create a compositing graph in a new user package."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import create_graph
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(graph_id: str, open_in_editor: bool = True, **_kwargs):
    return typed_result("Created Designer graph", create_graph, graph_id, open_in_editor)
