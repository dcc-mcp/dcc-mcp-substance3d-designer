"""Set one typed input parameter on an identified Designer node."""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import set_parameter
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(node_id: str, parameter: str, value_type: str, value: Any, **_kwargs):
    return typed_result("Set Designer node parameter", set_parameter, node_id, parameter, value_type, value)
