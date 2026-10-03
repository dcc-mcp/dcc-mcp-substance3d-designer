"""Read the installed official renderer's bounded help and engine identities."""

from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_substance3d_designer.offline_artifacts import inspect_renderer
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(**_kwargs):
    return typed_result("Read installed official renderer capabilities", inspect_renderer)


if __name__ == "__main__":
    run_main(main)
