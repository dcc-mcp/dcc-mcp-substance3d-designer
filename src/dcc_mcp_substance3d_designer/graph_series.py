"""Bounded parameter-driven series baking for Designer graphs.

Designer has no particle simulator, dynamics solver, or timeline track. What it
does expose is a deterministic graph that can be re-evaluated after a typed
input changes. This module turns that capability into three honest series
families -- variation tiles (particles), iteration passes (dynamics), and timed
frames (animation) -- by sweeping one parameter, re-evaluating the graph, and
exporting verified textures per step.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import graph_authoring as api
from .graph_evaluation import export_native_maps
from .graph_inspection import checked_graph, graph_identity

_MAX_STEPS = 64
_SERIES_VALUE_TYPES = ("float", "int")
_RESOLUTIONS = (256, 512, 1024, 2048, 4096)


def require_resolution(max_resolution: int) -> int:
    if isinstance(max_resolution, bool) or max_resolution not in _RESOLUTIONS:
        raise api.GraphAuthoringError("Unsupported resolution budget", "INVALID_RESOLUTION_BUDGET")
    return max_resolution


def require_value_type(value_type: str) -> str:
    resolved = str(value_type).strip().lower()
    if resolved not in _SERIES_VALUE_TYPES:
        raise api.GraphAuthoringError("Series values must be float or int", "UNSUPPORTED_VALUE_TYPE")
    return resolved


def numeric_values(start: float, stop: float, count: int, value_type: str) -> list[Any]:
    """Build a bounded, evenly spaced numeric sweep. A single step returns start."""
    resolved_type = require_value_type(value_type)
    for name, bound in (("start", start), ("stop", stop)):
        if isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound):
            raise api.GraphAuthoringError(f"{name} must be a finite number", "INVALID_SERIES_RANGE")
        if abs(bound) > 1_000_000:
            raise api.GraphAuthoringError(f"{name} is out of range", "INVALID_SERIES_RANGE")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= _MAX_STEPS:
        raise api.GraphAuthoringError(f"count must be 1..{_MAX_STEPS}", "INVALID_SERIES_COUNT")
    if count == 1:
        values: list[Any] = [float(start)]
    else:
        span = (float(stop) - float(start)) / (count - 1)
        values = [float(start) + span * index for index in range(count)]
    if resolved_type == "int":
        values = [int(round(item)) for item in values]
    return values


def require_values(values: Any) -> list[Any]:
    if not isinstance(values, list) or not 1 <= len(values) <= _MAX_STEPS:
        raise api.GraphAuthoringError(f"Provide one to {_MAX_STEPS} series values", "INVALID_SERIES_VALUES")
    resolved = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
            raise api.GraphAuthoringError("Series values must be finite numbers", "INVALID_SERIES_VALUES")
        if abs(item) > 1_000_000:
            raise api.GraphAuthoringError("Series value is out of range", "INVALID_SERIES_VALUES")
        resolved.append(item)
    return resolved


def require_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not api._IDENTIFIER.fullmatch(prefix):
        raise api.GraphAuthoringError(
            "prefix must start with a letter and contain only letters, digits, or underscores",
            "INVALID_SERIES_PREFIX",
        )
    return prefix


def _restore(node_id: str, parameter: str, value_type: str, original: Any, expected_graph_uid: str) -> None:
    """Best-effort rollback. Never mask the exception that triggered it."""
    try:
        api.set_parameter(node_id, parameter, value_type, original, expected_graph_uid)
    except BaseException:  # noqa: BLE001 - rollback is best effort.
        pass


def bake_series(
    output_dir: str,
    node_id: str,
    parameter: str,
    value_type: str,
    values: list[Any],
    outputs: list[dict],
    expected_graph_uid: str,
    max_resolution: int = 2048,
    prefix: str = "frame",
) -> dict[str, Any]:
    """Sweep one typed input and export verified textures for every step."""
    resolved_type = require_value_type(value_type)
    resolved_values = require_values(values)
    resolved_prefix = require_prefix(prefix)
    resolved_resolution = require_resolution(max_resolution)
    resolved_node = api.require_node_id(node_id)
    resolved_parameter = api.require_property(parameter)

    graph = checked_graph(expected_graph_uid)
    # Validate the destination before the first host mutation.
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists() or destination.is_symlink():
        raise api.GraphAuthoringError("Use a fresh series output directory", "OUTPUT_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)

    original = api.get_parameter(resolved_node, resolved_parameter)["value"]
    steps = []
    try:
        for index, value in enumerate(resolved_values):
            api.set_parameter(resolved_node, resolved_parameter, resolved_type, value, expected_graph_uid)
            step_dir = destination / "{}_{:04d}".format(resolved_prefix, index)
            exported = export_native_maps(str(step_dir), outputs, expected_graph_uid, resolved_resolution)
            steps.append({"index": index, "value": value, "output_dir": str(step_dir), "files": exported["files"]})
    except BaseException:
        _restore(resolved_node, resolved_parameter, resolved_type, original, expected_graph_uid)
        raise
    return {
        "graph_uid": graph_identity(graph),
        "node_id": resolved_node,
        "parameter": resolved_parameter,
        "value_type": resolved_type,
        "restored_value": original,
        "output_dir": str(destination),
        "step_count": len(steps),
        "values": resolved_values,
        "steps": steps,
        "max_resolution": resolved_resolution,
        "precision_policy": "native SDK texture precision; per-step export is header-verified",
    }


def _series_note(context: dict[str, Any], kind: str, note: str) -> dict[str, Any]:
    context["series_kind"] = kind
    context["series_note"] = note
    return context


def bake_variation_series(
    output_dir: str,
    node_id: str,
    parameter: str,
    value_type: str,
    start: float,
    stop: float,
    count: int,
    outputs: list[dict],
    expected_graph_uid: str,
    max_resolution: int = 2048,
) -> dict[str, Any]:
    """Sweep a seed/variation parameter and export one tile per step."""
    resolved_type = require_value_type(value_type)
    values = numeric_values(start, stop, count, resolved_type)
    context = bake_series(
        output_dir,
        node_id,
        parameter,
        resolved_type,
        values,
        outputs,
        expected_graph_uid,
        max_resolution,
        "tile",
    )
    return _series_note(
        context,
        "variation",
        "Designer has no particle system; these tiles are decorrelated variations of "
        "one procedural source for a downstream particle system.",
    )


def bake_iteration_series(
    output_dir: str,
    node_id: str,
    parameter: str,
    start: float,
    stop: float,
    count: int,
    outputs: list[dict],
    expected_graph_uid: str,
    max_resolution: int = 2048,
) -> dict[str, Any]:
    """Sweep an integer iteration-count parameter and export one pass per step."""
    values = numeric_values(start, stop, count, "int")
    context = bake_series(
        output_dir, node_id, parameter, "int", values, outputs, expected_graph_uid, max_resolution, "pass"
    )
    return _series_note(
        context,
        "iteration",
        "Designer has no dynamics solver; each pass is a deterministic re-evaluation at "
        "a different iteration count, not a simulated timestep.",
    )


def bake_animation_frames(
    output_dir: str,
    node_id: str,
    parameter: str,
    value_type: str,
    start: float,
    stop: float,
    count: int,
    outputs: list[dict],
    expected_graph_uid: str,
    max_resolution: int = 2048,
) -> dict[str, Any]:
    """Sweep a time-like parameter and export one frame per step."""
    resolved_type = require_value_type(value_type)
    values = numeric_values(start, stop, count, resolved_type)
    context = bake_series(
        output_dir,
        node_id,
        parameter,
        resolved_type,
        values,
        outputs,
        expected_graph_uid,
        max_resolution,
        "frame",
    )
    return _series_note(
        context,
        "animation",
        "Designer has no timeline track; frames are ordered graph re-evaluations along "
        "the swept parameter. Frame rate is a downstream playback choice.",
    )


_TIME_KEYWORDS = ("time", "frame", "phase", "speed", "duration", "animation", "offset")
_MAX_ANIMATION_SCAN_NODES = 200


def list_animation_parameters(
    expected_graph_uid: str | None = None,
    scan_nodes: bool = True,
    max_nodes: int = _MAX_ANIMATION_SCAN_NODES,
) -> dict[str, Any]:
    """Report time-like inputs that can drive a frame sweep. Read-only.

    Designer has no timeline track, so there is no authoritative animation
    parameter to read. This reports candidates by name convention and marks the
    result as discovery, not as a verified animation binding.
    """
    from sd.api.sdproperty import SDPropertyCategory

    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or not 1 <= max_nodes <= 1000:
        raise api.GraphAuthoringError("max_nodes must be 1..1000", "INVALID_SCAN_LIMIT")
    graph = checked_graph(expected_graph_uid)

    def time_like(identifier: str) -> bool:
        lowered = str(identifier).lower()
        return any(keyword in lowered for keyword in _TIME_KEYWORDS)

    graph_inputs = [
        {"parameter": prop.getId(), "value": api.json_value(graph.getPropertyValue(prop))}
        for prop in api.items(graph.getProperties(SDPropertyCategory.Input))
        if time_like(prop.getId())
    ]
    node_inputs = []
    if scan_nodes:
        for node in api.items(graph.getNodes())[:max_nodes]:
            for prop in api.items(node.getProperties(SDPropertyCategory.Input)):
                if not time_like(prop.getId()):
                    continue
                node_inputs.append(
                    {
                        "node_id": api.node_identifier(node),
                        "parameter": prop.getId(),
                        "value": api.json_value(node.getPropertyValue(prop)),
                        "read_only": bool(prop.isReadOnly()),
                        "connected": bool(api.items(node.getPropertyConnections(prop))),
                    }
                )
    return {
        "graph_uid": graph_identity(graph),
        "graph_inputs": graph_inputs,
        "node_inputs": node_inputs,
        "scanned_nodes": max_nodes if scan_nodes else 0,
        "animation_note": (
            "Designer has no timeline track. These are name-matched candidates for a "
            "frame sweep; confirm the parameter before baking."
        ),
    }


def compose_atlas(
    series_dir: str,
    output_path: str,
    file_name: str,
    columns: int | None = None,
) -> dict[str, Any]:
    """Tile one named output from a baked series into a grid atlas image."""
    # Validate every input before importing the composer so a caller with a bad
    # argument sees the real cause, not a missing-QtGui message.
    if not isinstance(file_name, str) or not file_name or "/" in file_name or "\\" in file_name:
        raise api.GraphAuthoringError("file_name must be a single map file name", "INVALID_ATLAS_FILE")
    source = Path(series_dir).expanduser().resolve()
    if not source.is_dir():
        raise api.GraphAuthoringError("Series directory does not exist", "SERIES_DIR_NOT_FOUND")

    try:
        from PySide2.QtGui import QImage
    except ImportError as exc:
        raise api.GraphAuthoringError(
            "Atlas composition needs PySide2 QtGui, which Designer provides", "ATLAS_COMPOSER_UNAVAILABLE"
        ) from exc
    steps = sorted(path for path in source.iterdir() if path.is_dir())
    images = []
    for step in steps:
        candidate = step / file_name
        if not candidate.is_file() or not candidate.stat().st_size:
            raise api.GraphAuthoringError(f"Step {step.name} is missing {file_name}", "ATLAS_STEP_FILE_MISSING")
        image = QImage(str(candidate))
        if image.isNull():
            raise api.GraphAuthoringError(f"Step {step.name} could not be decoded", "ATLAS_STEP_UNREADABLE")
        images.append((step.name, image))
    if not images:
        raise api.GraphAuthoringError("Series directory has no steps", "SERIES_EMPTY")

    total = len(images)
    if columns is None:
        columns = int(math.ceil(math.sqrt(total)))
    if isinstance(columns, bool) or not isinstance(columns, int) or not 1 <= columns <= total:
        raise api.GraphAuthoringError("columns must be 1..step_count", "INVALID_ATLAS_COLUMNS")
    rows = int(math.ceil(total / columns))
    tile_width = max(image.width() for _, image in images)
    tile_height = max(image.height() for _, image in images)
    if not 0 < tile_width <= 8192 or not 0 < tile_height <= 8192:
        raise api.GraphAuthoringError("Series tile size is out of range", "ATLAS_TILE_TOO_LARGE")

    atlas = QImage(tile_width * columns, tile_height * rows, QImage.Format_RGBA8888)
    atlas.fill(0)
    placed = []
    for index, (name, image) in enumerate(images):
        column, row = index % columns, index // columns
        for y in range(image.height()):
            for x in range(image.width()):
                atlas.setPixelColor(column * tile_width + x, row * tile_height + y, image.pixelColor(x, y))
        placed.append({"step": name, "column": column, "row": row})

    destination = Path(output_path).expanduser().resolve()
    if destination.exists() or destination.is_symlink():
        raise api.GraphAuthoringError("Use a fresh atlas destination", "ATLAS_EXISTS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not atlas.save(str(destination)) or not destination.is_file() or not destination.stat().st_size:
        raise api.GraphAuthoringError("Atlas was not written", "ATLAS_WRITE_FAILED")
    return {
        "atlas_path": str(destination),
        "series_dir": str(source),
        "columns": columns,
        "rows": rows,
        "tile_width": tile_width,
        "tile_height": tile_height,
        "tiles": placed,
        "file_name": file_name,
    }
