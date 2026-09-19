"""Discoverable node-type recipes for procedural effects and lighting maps.

Designer exposes node types through the graph's definition inventory, and the
exact URL that ships with a given Designer build is not guaranteed across
versions. Every recipe therefore declares an ordered list of candidate URLs and
resolves the first one the live SDK actually advertises. Nothing here invents a
node type: an unresolvable recipe fails closed with ``RECIPE_UNAVAILABLE`` and
reports the candidates it tried.

The catalog is experimental and resolution-time only. It currently ships 13
recipes over 31 candidate URLs - 7 effect recipes over 17 candidates and 6
lighting recipes over 14 candidates - all inferred from Designer's naming
conventions rather than verified against a real Designer session, so counts and
candidates must be read as "what this build tries", never as "what exists".
"""

from __future__ import annotations

from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, graph_identity

# Category -> recipe id -> (summary, candidate type URLs in preference order).
RECIPE_CATALOG: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "effects": {
        "blur": (
            "Soften or spread the incoming texture.",
            (
                "sbs::compositing::blur",
                "sbs::filter::blur",
                "sbs::filter::gaussianblur",
            ),
        ),
        "warp": (
            "Displace the incoming texture with a warp field.",
            (
                "sbs::compositing::warp",
                "sbs::filter::warp",
                "sbs::filter::distort",
            ),
        ),
        "levels": (
            "Adjust black point, white point, and contrast.",
            (
                "sbs::compositing::levels",
                "sbs::filter::levels",
                "sbs::filter::histogramadjustments",
            ),
        ),
        "sharpen": (
            "Increase high-frequency detail.",
            (
                "sbs::compositing::sharpen",
                "sbs::filter::sharpen",
            ),
        ),
        "edge_detect": (
            "Extract edges or contour transitions.",
            (
                "sbs::compositing::edgedetect",
                "sbs::filter::edgedetect",
            ),
        ),
        "blend": (
            "Composite a second input over the first one.",
            (
                "sbs::compositing::blend",
                "sbs::filter::blend",
            ),
        ),
        "mask": (
            "Modulate the incoming texture by a mask input.",
            (
                "sbs::compositing::multiply",
                "sbs::filter::multiply",
            ),
        ),
    },
    "lighting": {
        "normal_from_height": (
            "Convert a height field into a tangent-space normal map.",
            (
                "sbs::compositing::normal",
                "sbs::filter::normal",
                "sbs::filter::heighttonormal",
            ),
        ),
        "ambient_occlusion": (
            "Bake ambient occlusion from a height field.",
            (
                "sbs::compositing::ambientocclusion",
                "sbs::filter::ambientocclusion",
                "sbs::filter::ao",
            ),
        ),
        "curvature": (
            "Bake a curvature map from a height field.",
            (
                "sbs::compositing::curvature",
                "sbs::filter::curvature",
            ),
        ),
        "thickness": (
            "Estimate material thickness from a height field.",
            (
                "sbs::compositing::thickness",
                "sbs::filter::thickness",
            ),
        ),
        "emissive": (
            "Produce an emissive contribution from a mask or color input.",
            (
                "sbs::compositing::emissive",
                "sbs::filter::emissive",
            ),
        ),
        "height_to_normal_world_units": (
            "Convert height to a normal map using world-unit scaling.",
            (
                "sbs::compositing::heighttonormalworldunits",
                "sbs::filter::heighttonormalworldunits",
            ),
        ),
    },
}

_CATEGORY_ORDER = ("effects", "lighting")


def categories() -> tuple[str, ...]:
    return _CATEGORY_ORDER


def require_category(category: str) -> str:
    resolved = str(category).strip().lower()
    if resolved not in RECIPE_CATALOG:
        raise api.GraphAuthoringError(f"Unknown recipe category '{category}'", "RECIPE_CATEGORY_UNKNOWN")
    return resolved


def recipe_ids(category: str) -> tuple[str, ...]:
    return tuple(RECIPE_CATALOG[require_category(category)])


def candidates(category: str, recipe: str) -> tuple[str, ...]:
    resolved_category = require_category(category)
    resolved_recipe = str(recipe).strip().lower()
    if resolved_recipe not in RECIPE_CATALOG[resolved_category]:
        raise api.GraphAuthoringError(f"Unknown {resolved_category} recipe '{recipe}'", "RECIPE_UNKNOWN")
    return RECIPE_CATALOG[resolved_category][resolved_recipe][1]


def summary(category: str, recipe: str) -> str:
    resolved_category = require_category(category)
    resolved_recipe = str(recipe).strip().lower()
    if resolved_recipe not in RECIPE_CATALOG[resolved_category]:
        raise api.GraphAuthoringError(f"Unknown {resolved_category} recipe '{recipe}'", "RECIPE_UNKNOWN")
    return RECIPE_CATALOG[resolved_category][resolved_recipe][0]


def definition_urls(graph: Any) -> set[str]:
    return {str(definition.getId()) for definition in api.items(graph.getNodeDefinitions())}


def resolve_recipe(graph: Any, category: str, recipe: str) -> str:
    """Return the first candidate type URL the live SDK advertises."""
    available = definition_urls(graph)
    for candidate in candidates(category, recipe):
        if candidate in available:
            return candidate
    raise api.GraphAuthoringError(
        f"Recipe '{recipe}' is unavailable in this Designer build; tried: " + ", ".join(candidates(category, recipe)),
        "RECIPE_UNAVAILABLE",
    )


def list_recipes(category: str, expected_graph_uid: str | None = None) -> dict[str, Any]:
    """Report every recipe in a category and how it resolves in this session."""
    resolved_category = require_category(category)
    graph = checked_graph(expected_graph_uid)
    available = definition_urls(graph)
    rows = []
    for recipe in recipe_ids(resolved_category):
        candidate_list = candidates(resolved_category, recipe)
        resolved = next((item for item in candidate_list if item in available), None)
        rows.append(
            {
                "recipe": recipe,
                "summary": summary(resolved_category, recipe),
                "type_url": resolved,
                "available": resolved is not None,
                "candidates": list(candidate_list),
            }
        )
    return {
        "graph_uid": graph_identity(graph),
        "category": resolved_category,
        "total": len(rows),
        "available": sum(1 for row in rows if row["available"]),
        "recipes": rows,
        "discovery_note": (
            "Candidate URLs are resolved against the live node-definition inventory; "
            "availability varies by Designer version."
        ),
    }
