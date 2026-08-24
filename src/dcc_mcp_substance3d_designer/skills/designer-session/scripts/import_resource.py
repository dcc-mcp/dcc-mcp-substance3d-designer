"""Import one validated bitmap or SVG into the active Designer package."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import import_resource
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(path: str, kind: str, embed: bool = False, **_kwargs):
    return typed_result("Imported Designer package resource", import_resource, path, kind, embed)
