"""List lighting recipes that resolve in the active Designer graph."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_recipes import list_recipes
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(expected_graph_uid: str | None = None, **_kwargs):
    return typed_result("Listed Designer lighting recipes", list_recipes, "lighting", expected_graph_uid)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
