"""Set one graph input with typed validation and readback."""

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_parameters import set_graph_parameter
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(parameter: str, value_type: str, value, expected_graph_uid: str, **_kwargs):
    return typed_result("Set graph input", set_graph_parameter, parameter, value_type, value, expected_graph_uid)
