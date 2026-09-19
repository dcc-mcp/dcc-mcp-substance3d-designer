"""Apply an ordered chain of discoverable Designer effect recipes."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_effects import apply_effect_chain
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    category: str,
    steps: list[str],
    source_node: str,
    source_property: str,
    target_node: str | None = None,
    target_property: str | None = None,
    origin: list[float] | None = None,
    spacing: float = 160.0,
    expected_graph_uid: str | None = None,
    **_kwargs,
):
    return typed_result(
        "Applied Designer effect chain",
        apply_effect_chain,
        category,
        steps,
        source_node,
        source_property,
        target_node,
        target_property,
        origin,
        spacing,
        expected_graph_uid,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
