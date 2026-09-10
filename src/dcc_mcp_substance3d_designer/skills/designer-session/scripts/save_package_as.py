"""Save the active Designer package to an explicit .sbs path."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import save_package_as
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(path: str, expected_graph_uid: str | None = None, **_kwargs):
    return typed_result("Saved Designer package as", save_package_as, path, expected_graph_uid)
