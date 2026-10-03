"""Set bounded RGBA gradient keys on an exact native graph and node."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_gradients import set_gradient_keys
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, keys: list[dict[str, Any]], expected_graph_uid: str, **_kwargs):
    return typed_result("Set Designer RGBA gradient keys", set_gradient_keys, node_id, keys, expected_graph_uid)
