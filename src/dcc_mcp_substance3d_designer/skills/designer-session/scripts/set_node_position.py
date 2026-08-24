"""Set the position of one identified Designer node."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import set_node_position
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, position: list[float], **_kwargs):
    return typed_result("Positioned Designer graph node", set_node_position, node_id, position)
