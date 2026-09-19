"""Apply discoverable procedural-effect and lighting recipes to a graph.

Recipe nodes are created and wired through the adapter's verified primitives
(``create_node`` and ``connect_nodes``), so this module never re-implements
node creation, port lookup, cycle detection, or connection readback.
"""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api
from . import graph_recipes as recipes
from .graph_connections import connect_nodes
from .graph_inspection import checked_graph, graph_identity, property_types

_MAX_CHAIN = 12
_DEFAULT_INPUT_PROPERTY = "input"
_DEFAULT_OUTPUT_PROPERTY = "output"
_TEXTURE_TYPE = "SDTypeTexture"
_PREFERRED_INPUTS = ("input", "source", "bitmap", "background")
_PREFERRED_OUTPUTS = ("output", "result", "unique_filter_output")


def _is_texture(prop: Any) -> bool:
    return any(item["id"] == _TEXTURE_TYPE for item in property_types(prop))


def primary_input(node: Any) -> str:
    """Resolve a node's main input port by discovery, never by assumption."""
    from sd.api.sdproperty import SDPropertyCategory

    candidates = [prop for prop in api.items(node.getProperties(SDPropertyCategory.Input)) if prop.isConnectable()]
    if not candidates:
        raise api.GraphAuthoringError("Node exposes no connectable input", "PORT_NOT_FOUND")
    for selector in (
        lambda props: [prop for prop in props if _is_texture(prop)],
        lambda props: [prop for prop in props if prop.getId() in _PREFERRED_INPUTS],
    ):
        matched = selector(candidates)
        if matched:
            return matched[0].getId()
    return candidates[0].getId()


def primary_output(node: Any) -> str:
    """Resolve a node's main output port by discovery, never by assumption."""
    from sd.api.sdproperty import SDPropertyCategory

    candidates = list(api.items(node.getProperties(SDPropertyCategory.Output)))
    if not candidates:
        raise api.GraphAuthoringError("Node exposes no output port", "PORT_NOT_FOUND")
    for selector in (
        lambda props: [prop for prop in props if _is_texture(prop)],
        lambda props: [prop for prop in props if prop.getId() in _PREFERRED_OUTPUTS],
    ):
        matched = selector(candidates)
        if matched:
            return matched[0].getId()
    return candidates[0].getId()


def _require_steps(steps: Any) -> list[str]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= _MAX_CHAIN:
        raise api.GraphAuthoringError(f"Provide one to {_MAX_CHAIN} recipe steps", "INVALID_EFFECT_CHAIN")
    resolved = []
    for step in steps:
        if not isinstance(step, str) or not step.strip():
            raise api.GraphAuthoringError("Each chain step must be a recipe name", "INVALID_EFFECT_CHAIN")
        resolved.append(step)
    return resolved


def _find(graph: Any, node_id: str) -> Any:
    from .graph_inspection import find_in_graph

    return find_in_graph(graph, node_id)


def _connect_or_report(source_node: str, source_property: str, target_node: str, target_property: str) -> bool:
    """Wire one edge when both endpoints are given. Return True when wired."""
    if not target_node or not target_property:
        return False
    connect_nodes(source_node, source_property, target_node, target_property)
    return True


def apply_effect(
    category: str,
    recipe: str,
    source_node: str,
    source_property: str,
    target_node: str | None = None,
    target_property: str | None = None,
    position: list[float] | None = None,
    expected_graph_uid: str | None = None,
) -> dict[str, Any]:
    """Insert one recipe node downstream of a source output port."""
    resolved_category = recipes.require_category(category)
    graph = checked_graph(expected_graph_uid)
    type_url = recipes.resolve_recipe(graph, resolved_category, recipe)
    resolved_source = api.require_node_id(source_node)
    resolved_property = api.require_property(source_property)

    created = api.create_node(type_url, None, position)
    node_id = created["node_id"]
    # Track the node before resolving ports so a PORT_NOT_FOUND during discovery
    # still triggers the rollback this tool advertises.
    created_nodes = [node_id]
    connected = False
    try:
        input_property = primary_input(_find(graph, node_id))
        output_property = primary_output(_find(graph, node_id))
        # Wire the source through the new node, then optionally onward to a target.
        connect_nodes(resolved_source, resolved_property, node_id, input_property)
        connected = _connect_or_report(
            node_id,
            output_property,
            str(target_node) if target_node else "",
            str(target_property) if target_property else "",
        )
    except BaseException:
        api.remove_created(created_nodes)
        raise
    return {
        "graph_uid": graph_identity(graph),
        "mode": "single",
        "category": resolved_category,
        "steps": [
            {
                "step": str(recipe).strip().lower(),
                "type_url": type_url,
                "node_id": node_id,
                "input_property": input_property,
            }
        ],
        "source_node": resolved_source,
        "source_property": resolved_property,
        "head_node": node_id,
        "head_property": output_property,
        "connected": connected,
        "rollback": "The created node is removed when any connection or port lookup fails.",
    }


def apply_effect_chain(
    category: str,
    steps: list[str],
    source_node: str,
    source_property: str,
    target_node: str | None = None,
    target_property: str | None = None,
    origin: list[float] | None = None,
    spacing: float = 160.0,
    expected_graph_uid: str | None = None,
) -> dict[str, Any]:
    """Chain recipe nodes in order, wiring each step into the next one."""
    resolved_category = recipes.require_category(category)
    resolved_steps = _require_steps(steps)
    if isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or not 0 <= spacing <= 10000:
        raise api.GraphAuthoringError("spacing must be a nonnegative number", "INVALID_SPACING")
    graph = checked_graph(expected_graph_uid)
    # Resolve every recipe before creating anything so a missing type creates
    # no partial chain.
    resolved_urls = [(step, recipes.resolve_recipe(graph, resolved_category, step)) for step in resolved_steps]

    start = [float(origin[0]), float(origin[1])] if origin else [0.0, 0.0]
    created: list[dict[str, Any]] = []
    try:
        previous_node = api.require_node_id(source_node)
        previous_property = api.require_property(source_property)
        for index, (step, type_url) in enumerate(resolved_urls):
            position = [start[0] + spacing * (index + 1), start[1]]
            node = api.create_node(type_url, None, position)
            created.append({"step": step, "type_url": type_url, "node_id": node["node_id"]})
            node_handle = _find(graph, node["node_id"])
            input_property = primary_input(node_handle)
            created[-1]["input_property"] = input_property
            connect_nodes(previous_node, previous_property, node["node_id"], input_property)
            previous_node = node["node_id"]
            previous_property = primary_output(node_handle)
        # The final target connection is part of this call's unit of work: if it
        # fails, the nodes created above must not survive.
        connected = _connect_or_report(
            previous_node,
            previous_property,
            str(target_node) if target_node else "",
            str(target_property) if target_property else "",
        )
    except BaseException:
        api.remove_created(created)
        raise

    return {
        "graph_uid": graph_identity(graph),
        "category": resolved_category,
        "steps": created,
        "source_node": source_node,
        "source_property": source_property,
        "head_node": created[-1]["node_id"],
        "head_property": previous_property,
        "connected": connected,
        "rollback": "Created nodes are removed when any step or connection fails.",
    }
