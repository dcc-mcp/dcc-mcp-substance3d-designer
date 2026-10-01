"""Cook a hash-pinned SBS source with the installed official CLI."""

from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_substance3d_designer.offline_artifacts import cook_package
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    source_path: str,
    expected_source_sha256: str,
    output_dir: str,
    max_resolution: int = 2048,
    timeout_seconds: int = 300,
    **_kwargs,
):
    return typed_result(
        "Cooked official Designer archive",
        cook_package,
        source_path,
        expected_source_sha256,
        output_dir,
        max_resolution,
        timeout_seconds,
    )


if __name__ == "__main__":
    run_main(main)
