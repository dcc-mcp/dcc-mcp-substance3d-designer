"""Read native node bounds for an explicitly identified graph view."""

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_views import get_graph_view_node_bounds
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(graph_view_id: str, expected_graph_uid: str, node_ids: list, **_kwargs):
    return typed_result(
        "Read native graph-view node bounds", get_graph_view_node_bounds, graph_view_id, expected_graph_uid, node_ids
    )
