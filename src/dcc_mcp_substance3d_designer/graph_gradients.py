"""Bounded RGBA gradient editing through the public Designer SDK."""

from __future__ import annotations

import math
from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, find_in_graph, graph_identity, property_types, require_input

_NODE_TYPE = "sbs::compositing::gradient"
_KEY_TYPE = "sbs::compositing::gradient_key_rgba"
_ARRAY_TYPE = f"SDTypeArray<{_KEY_TYPE}>"
_MAX_KEYS = 64


def _unit_number(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise api.GraphAuthoringError("Gradient components must be numbers in 0..1", "INVALID_GRADIENT_KEYS")
    if not 0 <= raw <= 1 or not math.isfinite(raw):
        raise api.GraphAuthoringError("Gradient components must be finite numbers in 0..1", "INVALID_GRADIENT_KEYS")
    return float(raw)


def validate_keys(keys: Any, *, strict_order: bool = True) -> list[dict[str, Any]]:
    """Normalize ordered keys before importing or accessing the SDK."""
    if not isinstance(keys, list) or not 2 <= len(keys) <= _MAX_KEYS:
        raise api.GraphAuthoringError("An RGBA gradient requires 2..64 keys", "INVALID_GRADIENT_KEYS")
    normalized = []
    for key in keys:
        if not isinstance(key, dict) or not {"position", "color"} <= key.keys() <= {"position", "color", "midpoint"}:
            raise api.GraphAuthoringError(
                "Gradient keys require position/color and optional midpoint", "INVALID_GRADIENT_KEYS"
            )
        color = key["color"]
        if not isinstance(color, list) or len(color) != 4:
            raise api.GraphAuthoringError("Gradient color must contain four RGBA components", "INVALID_GRADIENT_KEYS")
        normalized.append(
            {
                "position": _unit_number(key["position"]),
                "color": [_unit_number(component) for component in color],
                "midpoint": _unit_number(key.get("midpoint", 0.5)),
            }
        )
    if strict_order and any(left["position"] >= right["position"] for left, right in zip(normalized, normalized[1:])):
        raise api.GraphAuthoringError("Gradient positions must be strictly increasing", "INVALID_GRADIENT_KEYS")
    return normalized


def _gradient_input(node_id: str, expected_graph_uid: str):
    if not isinstance(expected_graph_uid, str) or not 1 <= len(expected_graph_uid) <= 128:
        raise api.GraphAuthoringError("expected_graph_uid must be a bounded native graph UID", "INVALID_GRAPH_UID")
    graph = checked_graph(expected_graph_uid)
    node = find_in_graph(graph, node_id)
    if node.getDefinition().getId() != _NODE_TYPE:
        raise api.GraphAuthoringError("Node must be a native RGBA gradient", "GRADIENT_NODE_TYPE_MISMATCH")
    prop = require_input(node, "gradientrgba")
    if {kind["id"] for kind in property_types(prop)} != {_ARRAY_TYPE}:
        raise api.GraphAuthoringError("Input must contain RGBA gradient key structs", "GRADIENT_INPUT_TYPE_MISMATCH")
    current = node.getPropertyValue(prop)
    if current is None or current.getType().getId() != _ARRAY_TYPE:
        raise api.GraphAuthoringError("Native RGBA gradient value is unavailable", "GRADIENT_VALUE_UNAVAILABLE")
    key_type = current.getType().getItemType()
    if key_type.getId() != _KEY_TYPE:
        raise api.GraphAuthoringError("Native gradient item type changed", "GRADIENT_INPUT_TYPE_MISMATCH")
    fields = {
        member.getId(): {kind["id"] for kind in property_types(member)} for member in api.items(key_type.getMembers())
    }
    if fields != {"position": {"float"}, "midpoint": {"float"}, "value": {"ColorRGBA"}}:
        raise api.GraphAuthoringError("Native gradient fields are unsupported", "GRADIENT_FIELDS_UNSUPPORTED")
    return graph, node, prop, current, key_type


def _read_keys(native: Any) -> list[dict[str, Any]]:
    size = native.getSize()
    if not isinstance(size, int) or not 2 <= size <= _MAX_KEYS:
        raise api.GraphAuthoringError("Native gradient key count is outside 2..64", "GRADIENT_READBACK_FAILED")
    keys = []
    for index in range(size):
        key = native.getItem(index)
        if key is None or key.getType().getId() != _KEY_TYPE:
            raise api.GraphAuthoringError("Native gradient contains an unexpected key type", "GRADIENT_READBACK_FAILED")
        keys.append(
            {
                "position": api.json_value(key.getPropertyValueFromId("position")),
                "color": api.json_value(key.getPropertyValueFromId("value")),
                "midpoint": api.json_value(key.getPropertyValueFromId("midpoint")),
            }
        )
    return validate_keys(keys, strict_order=False)


def get_gradient_keys(node_id: str, expected_graph_uid: str) -> dict[str, Any]:
    """Read native RGBA gradient keys without editing the graph."""
    graph, node, prop, native, _ = _gradient_input(node_id, expected_graph_uid)
    return {
        "graph_uid": graph_identity(graph),
        "node_id": api.node_identifier(node),
        "parameter": prop.getId(),
        "key_type": _KEY_TYPE,
        "keys": _read_keys(native),
    }


def set_gradient_keys(node_id: str, keys: Any, expected_graph_uid: str) -> dict[str, Any]:
    """Replace a constant gradient and verify the native compound value."""
    normalized = validate_keys(keys)
    graph, node, prop, original, key_type = _gradient_input(node_id, expected_graph_uid)
    if prop.isReadOnly():
        raise api.GraphAuthoringError("Gradient input is read-only", "PROPERTY_READ_ONLY")
    if api.items(node.getPropertyConnections(prop)):
        raise api.GraphAuthoringError("Disconnect the gradient input before editing", "INPUT_CONNECTED")
    if node.getPropertyGraph(prop) is not None:
        raise api.GraphAuthoringError("Gradient input has a function graph", "PROPERTY_GRAPH_CONNECTED")

    from sd.api.sdvaluearray import SDValueArray
    from sd.api.sdvaluestruct import SDValueStruct

    native = SDValueArray.sNew(key_type, len(normalized))
    if native is None:
        raise api.GraphAuthoringError("SDK could not construct gradient keys", "GRADIENT_VALUE_UNAVAILABLE")
    for index, key in enumerate(normalized):
        item = SDValueStruct.sNew(key_type)
        if item is None:
            raise api.GraphAuthoringError("SDK could not construct a gradient key", "GRADIENT_VALUE_UNAVAILABLE")
        item.setPropertyValueFromId("position", api.typed_value("float", key["position"]))
        item.setPropertyValueFromId("midpoint", api.typed_value("float", key["midpoint"]))
        item.setPropertyValueFromId("value", api.typed_value("colorrgba", key["color"]))
        native.setItem(index, item)
    expected = validate_keys(_read_keys(native))
    checked_graph(expected_graph_uid)
    try:
        node.setInputPropertyValueFromId(prop.getId(), native)
        actual = _read_keys(node.getPropertyValue(prop))
        if actual != expected:
            raise api.GraphAuthoringError(
                "Native gradient readback differs from requested keys", "GRADIENT_READBACK_FAILED"
            )
    except BaseException:
        node.setInputPropertyValueFromId(prop.getId(), original)
        raise
    return {
        "graph_uid": graph_identity(graph),
        "node_id": api.node_identifier(node),
        "parameter": prop.getId(),
        "key_type": _KEY_TYPE,
        "keys": actual,
    }
