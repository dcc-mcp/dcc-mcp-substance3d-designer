"""Create an empty reusable graph in the active graph package, without changing selection."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_resources import create_subgraph
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(graph_id: str, expected_graph_uid: str, **_kwargs):
    return typed_result(
        "Create an empty reusable graph in the active graph package, without changing selection.",
        create_subgraph,
        graph_id,
        expected_graph_uid,
    )
