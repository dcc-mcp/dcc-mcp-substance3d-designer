"""Open one explicit .sbs package in Designer."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import open_package
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(path: str, **_kwargs):
    return typed_result("Opened Designer package", open_package, path)
