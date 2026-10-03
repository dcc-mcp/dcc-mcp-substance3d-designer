"""Read the installed official mesh baker's bounded help."""

from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_substance3d_designer.color_artifacts import inspect_mesh_baker
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(baker="Color.Raytraced", **_kwargs):
    return typed_result("Read installed official mesh baker capabilities", inspect_mesh_baker, baker)


if __name__ == "__main__":
    run_main(main)
