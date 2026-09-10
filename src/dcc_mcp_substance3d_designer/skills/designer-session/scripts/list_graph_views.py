"""List native Designer graph views and their selected nodes."""

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_views import list_graph_views
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(**_kwargs):
    return typed_result("Listed native Designer graph views", list_graph_views)
