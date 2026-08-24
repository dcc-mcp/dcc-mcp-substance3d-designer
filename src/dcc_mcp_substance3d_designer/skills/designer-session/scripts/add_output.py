"""Add one named output node to the active Designer graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import add_output
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(output_id: str, position: list[float] | None = None, **_kwargs):
    return typed_result("Added Designer graph output", add_output, output_id, position)
