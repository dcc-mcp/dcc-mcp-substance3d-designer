"""Report time-like Designer inputs that can drive a frame sweep."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_series import list_animation_parameters
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(expected_graph_uid: str | None = None, scan_nodes: bool = True, max_nodes: int = 200, **_kwargs):
    return typed_result(
        "Listed Designer animation parameter candidates",
        list_animation_parameters,
        expected_graph_uid,
        scan_nodes,
        max_nodes,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
