"""Bake lighting-response maps from a height or mask source in a Designer graph.

Designer is a procedural texture authoring host, not a lighting renderer. There
are no lights, no scene, and no physically based light transport. What Designer
does provide are filter/converter nodes that derive lighting-response maps from
a height field: tangent-space normals, ambient occlusion, curvature, and
thickness. This module builds those derived maps with the adapter's verified
primitives and exports them with header verification.
"""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api
from . import graph_recipes as recipes
from .graph_connections import connect_nodes
from .graph_effects import primary_input, primary_output
from .graph_evaluation import export_native_maps
from .graph_inspection import checked_graph, graph_identity

_MAX_MAPS = 6


def _require_maps(maps: Any) -> list[str]:
    if not isinstance(maps, list) or not 1 <= len(maps) <= _MAX_MAPS:
        raise api.GraphAuthoringError(f"Select one to {_MAX_MAPS} lighting maps", "INVALID_LIGHTING_MAPS")
    resolved, seen = [], set()
    for item in maps:
        if not isinstance(item, str) or not item.strip():
            raise api.GraphAuthoringError("Each lighting map must be a recipe name", "INVALID_LIGHTING_MAPS")
        name = item.strip().lower()
        if name in seen:
            raise api.GraphAuthoringError("Lighting map names must be unique", "DUPLICATE_LIGHTING_MAP")
        seen.add(name)
        resolved.append(name)
    return resolved


def bake_lighting_maps(
    output_dir: str,
    source_node: str,
    source_property: str,
    maps: list[str],
    expected_graph_uid: str,
    max_resolution: int = 2048,
    spacing: float = 160.0,
) -> dict[str, Any]:
    """Derive lighting-response maps from one source port and export them."""
    resolved_maps = _require_maps(maps)
    resolved_source = api.require_node_id(source_node)
    resolved_property = api.require_property(source_property)
    if isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or not 0 <= spacing <= 10000:
        raise api.GraphAuthoringError("spacing must be a nonnegative number", "INVALID_SPACING")

    graph = checked_graph(expected_graph_uid)
    # Resolve every recipe before creating any node so an unavailable type
    # cannot leave a partial graph behind.
    resolved_urls = [(name, recipes.resolve_recipe(graph, "lighting", name)) for name in resolved_maps]

    created: list[str] = []
    results = []
    try:
        for index, (name, type_url) in enumerate(resolved_urls):
            node = api.create_node(type_url, None, [spacing * (index + 1), 0.0])
            node_id = node["node_id"]
            created.append(node_id)
            input_property = primary_input(_node(graph, node_id))
            connect_nodes(resolved_source, resolved_property, node_id, input_property)
            results.append(
                {
                    "map": name,
                    "type_url": type_url,
                    "node_id": node_id,
                    "input_property": input_property,
                    "output_property": primary_output(_node(graph, node_id)),
                }
            )
        # Exporting is part of this call's unit of work: a failed export must not
        # leave the derived nodes behind.
        exported = export_native_maps(
            output_dir,
            [
                {"name": item["map"], "node_id": item["node_id"], "property": item["output_property"]}
                for item in results
            ],
            expected_graph_uid,
            max_resolution,
        )
    except BaseException:
        api.remove_created(created)
        raise

    return {
        "graph_uid": graph_identity(graph),
        "source_node": resolved_source,
        "source_property": resolved_property,
        "maps": results,
        "output_dir": exported.get("output_dir", output_dir),
        "files": exported["files"],
        "precision_policy": exported["precision_policy"],
        "lighting_note": (
            "Designer has no light transport; these maps encode surface response "
            "for a downstream renderer's lighting model."
        ),
    }


def _node(graph: Any, node_id: str) -> Any:
    from .graph_inspection import find_in_graph

    return find_in_graph(graph, node_id)
