"""Bake lighting-response maps from one source port in the active Designer graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_lighting import bake_lighting_maps
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    output_dir: str,
    source_node: str,
    source_property: str,
    maps: list[str],
    expected_graph_uid: str,
    max_resolution: int = 2048,
    spacing: float = 160.0,
    **_kwargs,
):
    return typed_result(
        "Baked Designer lighting maps",
        bake_lighting_maps,
        output_dir,
        source_node,
        source_property,
        maps,
        expected_graph_uid,
        max_resolution,
        spacing,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
