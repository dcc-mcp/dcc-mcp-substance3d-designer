"""Read native RGBA gradient keys without mutating the graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_gradients import get_gradient_keys
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, expected_graph_uid: str, **_kwargs):
    return typed_result("Read Designer RGBA gradient keys", get_gradient_keys, node_id, expected_graph_uid)
