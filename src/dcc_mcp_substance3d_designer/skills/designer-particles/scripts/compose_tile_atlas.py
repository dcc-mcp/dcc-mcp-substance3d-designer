"""Pack one map from a baked variation series into a grid sprite-sheet atlas."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_series import compose_atlas
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(series_dir: str, output_path: str, file_name: str, columns: int | None = None, **_kwargs):
    return typed_result("Composed Designer tile atlas", compose_atlas, series_dir, output_path, file_name, columns)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
