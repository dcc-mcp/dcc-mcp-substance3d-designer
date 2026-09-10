"""Instance a resource from an open package; reject direct and indirect graph recursion."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_resources import instance_resource
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(package_path: str, resource_url: str, expected_graph_uid: str, **_kwargs):
    return typed_result(
        "Instance a resource from an open package; reject direct and indirect graph recursion.",
        instance_resource,
        package_path,
        resource_url,
        expected_graph_uid,
    )
