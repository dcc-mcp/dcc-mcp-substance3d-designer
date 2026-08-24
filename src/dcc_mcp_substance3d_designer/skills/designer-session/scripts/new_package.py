"""Create a new unsaved Designer user package."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import new_package
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(**_kwargs):
    return typed_result("Created Designer package", new_package)
