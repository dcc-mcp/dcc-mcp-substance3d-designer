"""Discover actual node definitions supported by the active graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_inspection import list_node_types
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(query: str = "", offset: int = 0, limit: int = 100, **_kwargs):
    return typed_result(
        "Discover actual node definitions supported by the active graph.", list_node_types, query, offset, limit
    )
