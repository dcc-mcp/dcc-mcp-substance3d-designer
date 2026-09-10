"""Bounded graph evaluation and isolated, artifact-verified map export."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import graph_authoring as api
from .graph_inspection import checked_graph, graph_identity


def evaluate_graph(expected_graph_uid: str, max_nodes: int = 1000) -> dict[str, Any]:
    from sd.api.sdproperty import SDPropertyCategory

    if type(max_nodes) is not int or not 1 <= max_nodes <= 1000:
        raise api.GraphAuthoringError("max_nodes must be 1..1000", "INVALID_EVALUATION_LIMIT")
    graph = checked_graph(expected_graph_uid)
    if len(api.items(graph.getNodes())) > max_nodes:
        raise api.GraphAuthoringError("Graph exceeds the evaluation node budget", "EVALUATION_LIMIT")
    output_nodes = api.items(graph.getOutputNodes())
    if not output_nodes:
        raise api.GraphAuthoringError("Graph has no outputs", "NO_GRAPH_OUTPUTS")
    graph.compute()  # SDK is synchronous. The main-thread tool is dispatched async.
    outputs = []
    for node in output_nodes:
        ports = api.items(node.getProperties(SDPropertyCategory.Output))
        if not ports:
            raise api.GraphAuthoringError("Output node has no output property", "OUTPUT_NOT_COMPUTED")
        for prop in ports:
            result = node.getPropertyValue(prop)
            texture = result.get() if result is not None else None
            if texture is None:
                raise api.GraphAuthoringError("An output did not compute", "OUTPUT_NOT_COMPUTED")
            size = texture.getSize()
            if size.x <= 0 or size.y <= 0:
                raise api.GraphAuthoringError("Output texture dimensions are invalid", "OUTPUT_NOT_COMPUTED")
            pixel_format = texture.getPixelFormat()
            outputs.append(
                {
                    "node_id": api.node_identifier(node),
                    "property": prop.getId(),
                    "width": size.x,
                    "height": size.y,
                    "pixel_format": str(getattr(pixel_format, "name", pixel_format)),
                }
            )
    return {"graph_uid": graph_identity(graph), "computed": True, "outputs": outputs}


def export_maps(
    output_dir: str,
    image_format: str = "png",
    bit_depth: str = "8",
    color_space: str = "Raw",
    expected_graph_uid: str | None = None,
    output_color_spaces: dict[str, str] | None = None,
) -> dict[str, Any]:
    formats = {"png": {"8", "16"}, "tga": {"8"}, "tiff": {"8", "16", "16f", "32f"}, "exr": {"16f", "32f"}}
    if image_format not in formats or bit_depth not in formats[image_format]:
        raise api.GraphAuthoringError("Image format and bit depth are incompatible", "INVALID_EXPORT_FORMAT")
    if not isinstance(color_space, str) or not api._COLOR_SPACE.fullmatch(color_space):
        raise api.GraphAuthoringError("Invalid output color space", "INVALID_COLOR_SPACE")
    graph = checked_graph(expected_graph_uid)
    graph_id = api.require_identifier(graph.getIdentifier(), "graph_id")
    identifiers = [
        api.require_node_id(api.json_value(item), "output_id") for item in api.items(graph.getOutputIdentifiers())
    ]
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise api.GraphAuthoringError("Output identifiers must be present and unique", "INVALID_GRAPH_OUTPUTS")
    spaces = output_color_spaces or {}
    if not isinstance(spaces, dict) or set(spaces) - set(identifiers):
        raise api.GraphAuthoringError("Color-space overrides must name graph outputs", "INVALID_OUTPUT_OVERRIDE")
    if any(not isinstance(space, str) or not api._COLOR_SPACE.fullmatch(space) for space in spaces.values()):
        raise api.GraphAuthoringError("Invalid per-output color space", "INVALID_COLOR_SPACE")
    executable = shutil.which("sbsrender")
    if executable is None:
        raise api.GraphAuthoringError("Official sbsrender is unavailable", "SBSRENDER_UNAVAILABLE")
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # A fresh directory prevents any previous file from proving export success.
    run_dir = Path(tempfile.mkdtemp(prefix="designer-export-", dir=destination))
    from sd.api.sbs.sdsbsarexporter import SDSBSARExporter

    archive = run_dir / "material.sbsar"
    SDSBSARExporter.sNew().exportPackageToSBSAR(graph.getPackage(), str(archive))
    if not archive.is_file() or not archive.stat().st_size:
        raise api.GraphAuthoringError("Designer did not compile an SBSAR", "SBSAR_EXPORT_FAILED")
    command = [
        executable,
        "render",
        "--input",
        str(archive),
        "--input-graph",
        graph_id,
        "--output-path",
        str(run_dir),
        "--output-name",
        "{outputNodeName}",
        "--output-format",
        image_format,
        "--output-bit-depth",
        bit_depth,
        "--output-colorspace",
        color_space,
    ]
    for identifier, space in sorted(spaces.items()):
        command.extend(["--set-output-colorspace", f"{identifier}@{space}"])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    except subprocess.TimeoutExpired as exc:
        raise api.GraphAuthoringError("sbsrender timed out", "MAP_EXPORT_TIMEOUT") from exc
    if result.returncode != 0:
        raise api.GraphAuthoringError("sbsrender failed", "MAP_EXPORT_FAILED")
    files = []
    for identifier in identifiers:
        path = run_dir / f"{identifier}.{image_format}"
        if not path.is_file() or path.is_symlink() or not path.stat().st_size:
            raise api.GraphAuthoringError(f"Missing or empty output: {identifier}", "MAP_OUTPUT_MISSING")
        files.append(
            {
                "output_id": identifier,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "color_space": spaces.get(identifier, color_space),
            }
        )
    return {
        "graph_uid": graph_identity(graph),
        "output_dir": str(run_dir),
        "image_format": image_format,
        "bit_depth": bit_depth,
        "color_space": color_space,
        "files": files,
        "sbsar_path": str(archive),
    }
