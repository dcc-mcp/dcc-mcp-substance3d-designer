"""Delete one identified node from the active Designer graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import delete_node
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, **_kwargs):
    return typed_result("Deleted Designer graph node", delete_node, node_id)
