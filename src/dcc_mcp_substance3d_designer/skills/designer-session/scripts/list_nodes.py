"""Enumerate native node identities and labels in the active graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_inspection import list_nodes
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(offset: int = 0, limit: int = 100, **_kwargs):
    return typed_result("Enumerate native node identities and labels in the active graph.", list_nodes, offset, limit)
