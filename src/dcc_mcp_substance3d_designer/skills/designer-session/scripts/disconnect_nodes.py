"""Disconnect one exact edge and verify removal, preserving other connections."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_connections import disconnect_nodes
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    source_node: str, source_property: str, target_node: str, target_property: str, expected_graph_uid: str, **_kwargs
):
    return typed_result(
        "Disconnect one exact edge and verify removal, preserving other connections.",
        disconnect_nodes,
        source_node,
        source_property,
        target_node,
        target_property,
        expected_graph_uid,
    )
