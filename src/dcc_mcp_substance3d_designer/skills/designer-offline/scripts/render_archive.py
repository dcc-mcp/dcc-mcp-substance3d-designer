"""Render and byte-verify a hash-pinned compiled archive with the official CLI."""

from __future__ import annotations

from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_substance3d_designer.offline_artifacts import render_archive
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(
    archive_path: str,
    expected_archive_sha256: str,
    graph_identifier: str,
    output_dir: str,
    outputs: list[dict],
    resolution: int = 1024,
    seed: int | None = None,
    input_images: list[dict] | None = None,
    normal_convention: str | None = None,
    timeout_seconds: int = 300,
    engine: str = "sse2",
    **_kwargs,
):
    return typed_result(
        "Rendered verified official Designer maps",
        render_archive,
        archive_path,
        expected_archive_sha256,
        graph_identifier,
        output_dir,
        outputs,
        resolution,
        seed,
        input_images,
        normal_convention,
        timeout_seconds,
        engine,
    )


if __name__ == "__main__":
    run_main(main)
