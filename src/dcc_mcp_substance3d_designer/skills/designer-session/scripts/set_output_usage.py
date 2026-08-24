"""Set semantic usage metadata on a Designer output node."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import set_output_usage
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, usage: str, channels: str, color_space: str, **_kwargs):
    return typed_result("Set Designer graph output usage", set_output_usage, node_id, usage, channels, color_space)
