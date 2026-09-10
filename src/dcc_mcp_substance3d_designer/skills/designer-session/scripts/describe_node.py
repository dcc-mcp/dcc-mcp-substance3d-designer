"""Describe input/output types, direction, defaults, and editability of one native node."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_inspection import describe_node
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, expected_graph_uid: str, **_kwargs):
    return typed_result(
        "Describe input/output types, direction, defaults, and editability of one native node.",
        describe_node,
        node_id,
        expected_graph_uid,
    )
