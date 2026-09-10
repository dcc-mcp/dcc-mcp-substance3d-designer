"""Read active graph ownership and typed node diagnostic state."""

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_diagnostics import inspect_graph_session
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(offset: int = 0, limit: int = 100, **_kwargs):
    return typed_result("Inspected graph ownership and diagnostics", inspect_graph_session, offset, limit)
