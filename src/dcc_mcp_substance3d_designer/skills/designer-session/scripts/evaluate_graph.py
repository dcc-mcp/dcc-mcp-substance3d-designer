"""Compute a graph within the node budget and inspect every output texture. SDK compute is synchronous and cannot be cancelled."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_evaluation import evaluate_graph
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(expected_graph_uid: str, max_nodes: int = 1000, max_resolution: int = 2048, **_kwargs):
    return typed_result(
        "Compute a graph within the node budget and inspect every output texture. SDK compute is synchronous and cannot be cancelled.",
        evaluate_graph,
        expected_graph_uid,
        max_nodes,
        max_resolution,
    )
