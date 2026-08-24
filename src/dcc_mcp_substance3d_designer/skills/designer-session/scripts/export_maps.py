"""Render map outputs with the official bounded sbsrender CLI."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import export_maps
from dcc_mcp_substance3d_designer.skill_support import typed_result


@skill_entry
def main(output_dir: str, image_format: str = "png", bit_depth: str = "8", color_space: str = "Raw", **_kwargs):
    return typed_result("Exported Designer graph maps", export_maps, output_dir, image_format, bit_depth, color_space)
