"""Expose one node input through a supported Designer binding API."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import expose_parameter
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, parameter: str, exposed_id: str, **_kwargs):
    return typed_result("Exposed Designer node parameter", expose_parameter, node_id, parameter, exposed_id)
