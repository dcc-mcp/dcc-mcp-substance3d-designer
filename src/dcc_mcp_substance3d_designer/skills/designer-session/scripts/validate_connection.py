"""Check exact ports, supported type intersection, occupancy, and cycles without mutation."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_connections import validate_connection
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    source_node: str, source_property: str, target_node: str, target_property: str, expected_graph_uid: str, **_kwargs
):
    return typed_result(
        "Check exact ports, supported type intersection, occupancy, and cycles without mutation.",
        validate_connection,
        source_node,
        source_property,
        target_node,
        target_property,
        expected_graph_uid,
    )
