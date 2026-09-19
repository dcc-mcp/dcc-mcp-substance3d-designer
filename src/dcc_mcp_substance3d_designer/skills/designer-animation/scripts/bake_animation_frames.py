"""Bake ordered animation frames from the active Designer graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_series import bake_animation_frames
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    output_dir: str,
    node_id: str,
    parameter: str,
    start: float,
    stop: float,
    count: int,
    outputs: list[dict],
    expected_graph_uid: str,
    value_type: str = "float",
    max_resolution: int = 2048,
    **_kwargs,
):
    return typed_result(
        "Baked Designer animation frames",
        bake_animation_frames,
        output_dir,
        node_id,
        parameter,
        value_type,
        start,
        stop,
        count,
        outputs,
        expected_graph_uid,
        max_resolution,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
