"""Read one typed input parameter from an identified Designer node."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import get_parameter
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, parameter: str, **_kwargs):
    return typed_result("Read Designer node parameter", get_parameter, node_id, parameter)
