"""Bake pinned mesh positions through the installed official native baker."""

from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_substance3d_designer.position_artifacts import bake_position_map
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    mesh_path: str,
    expected_mesh_sha256: str,
    output_dir: str,
    resolution: int = 2048,
    padding_radius: int = 4,
    timeout_seconds: int = 300,
    **_kwargs,
):
    return typed_result(
        "Baked verified native rest positions",
        bake_position_map,
        mesh_path,
        expected_mesh_sha256,
        output_dir,
        resolution,
        padding_radius,
        timeout_seconds,
    )


if __name__ == "__main__":
    run_main(main)
