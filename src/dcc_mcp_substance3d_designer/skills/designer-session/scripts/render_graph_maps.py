"""Compute bounded graph textures with Designer's native engine."""

from __future__ import annotations

import hashlib
from pathlib import Path

from dcc_mcp_core.skill import skill_entry

from dcc_mcp_substance3d_designer.graph_authoring import (
    GraphAuthoringError,
    active_graph,
    find_node,
    require_identifier,
    require_property,
)
from dcc_mcp_substance3d_designer.skill_support import typed_result


def render_graph_maps(output_dir: str, outputs: list[dict], resolution: int = 1024) -> dict:
    if isinstance(resolution, bool) or resolution not in (256, 512, 1024, 2048):
        raise GraphAuthoringError("Unsupported render resolution", "INVALID_RESOLUTION")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 8:
        raise GraphAuthoringError("Expected one to eight explicit outputs", "INVALID_OUTPUTS")
    graph = active_graph()
    if len(list(graph.getNodes())) > 128:
        raise GraphAuthoringError("Graph exceeds native render node limit", "GRAPH_TOO_LARGE")
    from sd.api.sdbasetypes import int2
    from sd.api.sdproperty import SDPropertyCategory, SDPropertyInheritanceMethod
    from sd.api.sdvalueint2 import SDValueInt2

    selected = []
    names = set()
    for item in outputs:
        name = require_identifier(item["name"], "output name")
        if name.casefold() in names:
            raise GraphAuthoringError("Output names must be unique", "DUPLICATE_OUTPUT")
        names.add(name.casefold())
        node = find_node(item["node_id"])
        port = require_property(item["property"])
        if port not in [prop.getId() for prop in node.getProperties(SDPropertyCategory.Output)]:
            raise GraphAuthoringError("Output port not found", "OUTPUT_NOT_FOUND")
        selected.append((name, node, port))
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise GraphAuthoringError("Use a new output directory to preserve existing exports", "OUTPUT_EXISTS")
    destination.mkdir(parents=True)
    power = resolution.bit_length() - 1
    size_property = graph.getPropertyFromId("$outputsize", SDPropertyCategory.Input)
    graph.setPropertyInheritanceMethod(size_property, SDPropertyInheritanceMethod.Absolute)
    graph.setInputPropertyValueFromId("$outputsize", SDValueInt2.sNew(int2(power, power)))
    graph.compute()
    files = []
    for name, node, port in selected:
        value = node.getPropertyValueFromId(port, SDPropertyCategory.Output)
        texture = value.get() if value is not None else None
        if texture is None:
            raise GraphAuthoringError("Graph did not produce a texture", "TEXTURE_UNAVAILABLE")
        size = texture.getSize()
        if (size.x, size.y) != (resolution, resolution):
            raise GraphAuthoringError("Computed texture does not match requested resolution", "RESOLUTION_MISMATCH")
        path = destination / (name + ".png")
        texture.save(str(path))
        if not path.is_file() or path.stat().st_size == 0:
            raise GraphAuthoringError("Texture export produced no file", "EXPORT_FAILED")
        files.append({"name": name, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"resolution": resolution, "files": files}


@skill_entry
def main(output_dir: str, outputs: list[dict], resolution: int = 1024, **_kwargs):
    return typed_result("Rendered graph maps with Designer", render_graph_maps, output_dir, outputs, resolution)
