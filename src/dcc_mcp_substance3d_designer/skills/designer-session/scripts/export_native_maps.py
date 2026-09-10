"""Export native graph texture precision with image-header verification."""

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_evaluation import export_native_maps
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(output_dir: str, outputs: list, expected_graph_uid: str, max_resolution: int = 2048, **_kwargs):
    return typed_result(
        "Exported native graph textures", export_native_maps, output_dir, outputs, expected_graph_uid, max_resolution
    )
