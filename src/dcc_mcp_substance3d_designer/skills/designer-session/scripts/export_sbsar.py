"""Publish the active Designer package as a verified SBSAR artifact."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import export_sbsar
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(path: str, **_kwargs):
    return typed_result("Exported Designer SBSAR", export_sbsar, path)
