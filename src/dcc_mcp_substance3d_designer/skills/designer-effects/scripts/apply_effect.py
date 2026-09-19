"""Apply one discoverable Designer effect recipe downstream of a source port."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_effects import apply_effect
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    category: str,
    recipe: str,
    source_node: str,
    source_property: str,
    target_node: str | None = None,
    target_property: str | None = None,
    position: list[float] | None = None,
    expected_graph_uid: str | None = None,
    **_kwargs,
):
    return typed_result(
        "Applied Designer effect recipe",
        apply_effect,
        category,
        recipe,
        source_node,
        source_property,
        target_node,
        target_property,
        position,
        expected_graph_uid,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
