"""Probe which Designer module-manager APIs this build advertises."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_modules import module_capabilities
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(**_kwargs):
    return typed_result("Probed Designer module capabilities", module_capabilities)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
