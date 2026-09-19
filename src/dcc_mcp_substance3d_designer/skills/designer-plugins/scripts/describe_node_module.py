"""Describe the node definitions owned by one Designer module namespace."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_modules import describe_node_module
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(module: str, query: str = "", offset: int = 0, limit: int = 100, **_kwargs):
    return typed_result("Described Designer node module", describe_node_module, module, query, offset, limit)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
