"""Create one typed built-in node in the active Designer graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import create_node
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(type_url: str, node_id: str | None = None, position: list[float] | None = None, **_kwargs):
    return typed_result("Created Designer graph node", create_node, type_url, node_id, position)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
