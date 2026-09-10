"""List resources and embed state in an explicitly selected open package."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_resources import list_resources
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(package_path: str, offset: int = 0, limit: int = 100, **_kwargs):
    return typed_result(
        "List resources and embed state in an explicitly selected open package.",
        list_resources,
        package_path,
        offset,
        limit,
    )
