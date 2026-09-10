"""Describe properties of a discovered node definition without creating a node."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_inspection import describe_node_type
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(type_id: str, **_kwargs):
    return typed_result(
        "Describe properties of a discovered node definition without creating a node.", describe_node_type, type_id
    )
