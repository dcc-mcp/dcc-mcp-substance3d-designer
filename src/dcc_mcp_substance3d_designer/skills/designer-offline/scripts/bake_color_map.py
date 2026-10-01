"""Bake explicit pinned FBX vertex/material colour IDs through official SAT."""

from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_substance3d_designer.color_artifacts import bake_color_map
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(mesh_path, expected_mesh_sha256, output_dir, color_source="vertex", resolution=2048,
         padding_radius=4, timeout_seconds=300, **_kwargs):
    return typed_result("Baked verified native colour IDs", bake_color_map, mesh_path,
                        expected_mesh_sha256, output_dir, color_source, resolution,
                        padding_radius, timeout_seconds)


if __name__ == "__main__":
    run_main(main)
