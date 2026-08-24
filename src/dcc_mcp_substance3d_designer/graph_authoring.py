"""Typed, host-bound graph authoring primitives for Substance 3D Designer."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_PROPERTY_ID = re.compile(r"^\$?[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_TYPE_URL = re.compile(r"^sbs::[A-Za-z0-9_.-]+(?:::[A-Za-z0-9_.-]+)+$")
_COLOR_SPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. +()-]{0,127}$")


class GraphAuthoringError(RuntimeError):
    """Stable fail-closed error for a typed graph operation."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def value(obj: Any, *names: str) -> Any:
    for name in names:
        member = getattr(obj, name, None)
        if member is not None:
            return member() if callable(member) else member
    return None


def items(collection: Any) -> list[Any]:
    if collection is None:
        return []
    if isinstance(collection, (list, tuple)):
        return list(collection)
    try:
        return list(collection)
    except TypeError:
        size = value(collection, "getSize")
        if not isinstance(size, int):
            return []
        return [collection[index] for index in range(size)]


def require_identifier(identifier: str, label: str = "identifier") -> str:
    if not isinstance(identifier, str):
        raise GraphAuthoringError(f"{label} must be a string", "INVALID_IDENTIFIER")
    resolved = str(identifier).strip()
    if not _IDENTIFIER.fullmatch(resolved):
        raise GraphAuthoringError(
            f"{label} must start with a letter and contain only letters, digits, or underscores",
            "INVALID_IDENTIFIER",
        )
    return resolved


def require_type_url(type_url: str) -> str:
    if not isinstance(type_url, str):
        raise GraphAuthoringError("type_url must be a string", "INVALID_TYPE_URL")
    resolved = str(type_url).strip()
    if len(resolved) > 160 or not _TYPE_URL.fullmatch(resolved):
        raise GraphAuthoringError(
            "type_url must be a bounded built-in sbs:: namespace URL",
            "INVALID_TYPE_URL",
        )
    return resolved


def require_property(identifier: str, label: str = "property") -> str:
    if not isinstance(identifier, str):
        raise GraphAuthoringError(f"{label} must be a string", "INVALID_PROPERTY_ID")
    resolved = str(identifier).strip()
    if not _PROPERTY_ID.fullmatch(resolved):
        raise GraphAuthoringError(
            f"{label} must be a bounded Designer property identifier",
            "INVALID_PROPERTY_ID",
        )
    return resolved


def active_graph() -> Any:
    import sd  # Lazy import: Designer host only.

    application = sd.getContext().getSDApplication()
    graph = None
    for context_name in ("getUIMgr", "getQtForPythonUIMgr", "getLocationContext"):
        ui_context = value(application, context_name)
        graph = value(ui_context, "getCurrentGraph") if ui_context else None
        if graph is not None:
            break
    if graph is None:
        raise GraphAuthoringError("No active Designer graph", "NO_ACTIVE_GRAPH")
    return graph


def application() -> Any:
    import sd  # Lazy import: Designer host only.

    return sd.getContext().getSDApplication()


def package_manager() -> Any:
    return application().getPackageMgr()


def active_package() -> Any:
    graph = active_graph()
    package = value(graph, "getPackage", "getParent")
    if package is None:
        raise GraphAuthoringError("Active graph package is unavailable", "NO_ACTIVE_PACKAGE")
    return package


def package_path(package: Any) -> str | None:
    resolved = value(package, "getFilePath")
    return str(resolved) if resolved else None


def node_identifier(node: Any) -> str:
    identifier = value(node, "getIdentifier", "getId", "getUID")
    if identifier is None:
        raise GraphAuthoringError("Designer did not return a node identifier", "MISSING_NODE_ID")
    return str(identifier)


def create_node(
    type_url: str,
    node_id: str | None = None,
    position: list[float] | tuple[float, float] | None = None,
) -> dict[str, Any]:
    resolved_type = require_type_url(type_url)
    resolved_id = require_identifier(node_id, "node_id") if node_id is not None else None
    resolved_position = position if position is not None else [0.0, 0.0]
    if len(resolved_position) != 2:
        raise GraphAuthoringError("position must contain exactly two numbers", "INVALID_POSITION")
    try:
        xy = [float(resolved_position[0]), float(resolved_position[1])]
    except (TypeError, ValueError) as exc:
        raise GraphAuthoringError("position must contain exactly two numbers", "INVALID_POSITION") from exc
    if any(not math.isfinite(component) or abs(component) > 1_000_000 for component in xy):
        raise GraphAuthoringError("position components are out of range", "INVALID_POSITION")

    from sd.api.sdbasetypes import float2

    node = active_graph().newNode(resolved_type)
    if node is None:
        raise GraphAuthoringError("Designer rejected the requested node type", "NODE_TYPE_UNAVAILABLE")
    if resolved_id is not None:
        node.setIdentifier(resolved_id)
    else:
        resolved_id = node_identifier(node)
    node.setPosition(float2(*xy))
    return {"node_id": resolved_id, "type_url": resolved_type, "position": xy}


def create_graph(graph_id: str, open_in_editor: bool = True) -> dict[str, Any]:
    identifier = require_identifier(graph_id, "graph_id")

    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph

    package = package_manager().newUserPackage()
    graph = SDSBSCompGraph.sNew(package)
    if graph is None:
        raise GraphAuthoringError("Designer could not create a compositing graph", "GRAPH_CREATE_FAILED")
    graph.setIdentifier(identifier)
    if open_in_editor:
        application().getUIMgr().openResourceInEditor(graph)
    return {"graph_id": identifier, "package_path": package_path(package)}


def find_node(node_id: str) -> Any:
    identifier = require_identifier(node_id, "node_id")
    for node in items(active_graph().getNodes()):
        if node_identifier(node) == identifier:
            return node
    raise GraphAuthoringError(f"Node '{identifier}' was not found", "NODE_NOT_FOUND")


def connect_nodes(
    source_node: str,
    source_property: str,
    target_node: str,
    target_property: str,
) -> dict[str, str]:
    source_id = require_identifier(source_node, "source_node")
    target_id = require_identifier(target_node, "target_node")
    source_prop = require_property(source_property, "source_property")
    target_prop = require_property(target_property, "target_property")
    source = find_node(source_id)
    target = find_node(target_id)
    connection = source.newPropertyConnectionFromId(source_prop, target, target_prop)
    if connection is None:
        from sd.api.sdproperty import SDPropertyCategory

        target_input = target.getPropertyFromId(target_prop, SDPropertyCategory.Input)
        connected = items(target.getPropertyConnections(target_input)) if target_input else []
        upstream_nodes = [value(item, "getInputPropertyNode", "getOutputPropertyNode") for item in connected]
        if source not in upstream_nodes:
            raise GraphAuthoringError(
                "Designer rejected the typed property connection",
                "CONNECTION_REJECTED",
            )
    return {
        "source_node": source_id,
        "source_property": source_prop,
        "target_node": target_id,
        "target_property": target_prop,
    }


def delete_node(node_id: str) -> dict[str, str]:
    identifier = require_identifier(node_id, "node_id")
    graph = active_graph()
    node = find_node(identifier)
    delete = getattr(graph, "deleteNode", None)
    if not callable(delete):
        raise GraphAuthoringError("Designer node deletion API is unavailable", "DELETE_API_UNAVAILABLE")
    result = delete(node)
    if result is False:
        raise GraphAuthoringError("Designer rejected node deletion", "NODE_DELETE_FAILED")
    return {"node_id": identifier}


def set_node_position(node_id: str, position: list[float]) -> dict[str, Any]:
    if len(position) != 2:
        raise GraphAuthoringError("position must contain exactly two numbers", "INVALID_POSITION")
    try:
        xy = [float(position[0]), float(position[1])]
    except (TypeError, ValueError) as exc:
        raise GraphAuthoringError("position must contain exactly two numbers", "INVALID_POSITION") from exc
    if any(not math.isfinite(component) or abs(component) > 1_000_000 for component in xy):
        raise GraphAuthoringError("position components are out of range", "INVALID_POSITION")

    from sd.api.sdbasetypes import float2

    node = find_node(node_id)
    node.setPosition(float2(*xy))
    return {"node_id": node_identifier(node), "position": xy}


def _numeric_sequence(raw: Any, size: int, label: str) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != size:
        raise GraphAuthoringError(f"{label} requires exactly {size} numeric values", "INVALID_VALUE")
    try:
        values = [float(item) for item in raw]
    except (TypeError, ValueError) as exc:
        raise GraphAuthoringError(f"{label} values must be numeric", "INVALID_VALUE") from exc
    if any(not math.isfinite(item) or abs(item) > 1_000_000 for item in values):
        raise GraphAuthoringError(f"{label} values are out of range", "INVALID_VALUE")
    return values


def typed_value(value_type: str, raw: Any) -> Any:
    kind = str(value_type).strip().lower()
    if kind == "bool":
        if not isinstance(raw, bool):
            raise GraphAuthoringError("bool values must be true or false", "INVALID_VALUE")
        from sd.api.sdvaluebool import SDValueBool

        return SDValueBool.sNew(raw)
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise GraphAuthoringError("int values must be integers", "INVALID_VALUE")
        from sd.api.sdvalueint import SDValueInt

        return SDValueInt.sNew(raw)
    if kind == "float":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise GraphAuthoringError("float values must be numeric", "INVALID_VALUE")
        from sd.api.sdvaluefloat import SDValueFloat

        return SDValueFloat.sNew(float(raw))
    if kind == "string":
        if not isinstance(raw, str) or len(raw) > 4096:
            raise GraphAuthoringError("string values must contain at most 4096 characters", "INVALID_VALUE")
        from sd.api.sdvaluestring import SDValueString

        return SDValueString.sNew(raw)
    vector_specs = {
        "int2": (2, "int2", "SDValueInt2", "sd.api.sdvalueint2"),
        "float2": (2, "float2", "SDValueFloat2", "sd.api.sdvaluefloat2"),
        "float3": (3, "float3", "SDValueFloat3", "sd.api.sdvaluefloat3"),
        "float4": (4, "float4", "SDValueFloat4", "sd.api.sdvaluefloat4"),
    }
    if kind not in vector_specs:
        raise GraphAuthoringError("Unsupported typed parameter value", "UNSUPPORTED_VALUE_TYPE")
    size, base_name, wrapper_name, module_name = vector_specs[kind]
    values = _numeric_sequence(raw, size, kind)
    if kind == "int2":
        if any(isinstance(item, bool) or not isinstance(item, int) for item in raw):
            raise GraphAuthoringError("int2 values must be integers", "INVALID_VALUE")
        values = [int(item) for item in raw]
    import importlib

    base_type = getattr(importlib.import_module("sd.api.sdbasetypes"), base_name)
    wrapper = getattr(importlib.import_module(module_name), wrapper_name)
    return wrapper.sNew(base_type(*values))


def json_value(raw: Any) -> Any:
    resolved = value(raw, "get")
    if resolved is not None and resolved is not raw:
        return json_value(resolved)
    if raw is None or isinstance(raw, (bool, int, float, str)):
        return raw
    if isinstance(raw, (list, tuple)):
        return [json_value(item) for item in raw]
    components = []
    for name in ("x", "y", "z", "w"):
        component = value(raw, name)
        if component is None:
            break
        components.append(component)
    if components:
        return [json_value(component) for component in components]
    identifier = value(raw, "getId", "getIdentifier")
    if identifier is not None:
        return str(identifier)
    return {"type": type(raw).__name__}


def set_parameter(node_id: str, parameter: str, value_type: str, raw: Any) -> dict[str, Any]:
    identifier = require_property(parameter, "parameter")
    node = find_node(node_id)
    node.setInputPropertyValueFromId(identifier, typed_value(value_type, raw))
    return {
        "node_id": node_identifier(node),
        "parameter": identifier,
        "value_type": str(value_type).lower(),
        "value": raw,
    }


def get_parameter(node_id: str, parameter: str) -> dict[str, Any]:
    identifier = require_property(parameter, "parameter")

    from sd.api.sdproperty import SDPropertyCategory

    node = find_node(node_id)
    prop = node.getPropertyFromId(identifier, SDPropertyCategory.Input)
    if prop is None:
        raise GraphAuthoringError(f"Input parameter '{identifier}' was not found", "PARAMETER_NOT_FOUND")
    return {
        "node_id": node_identifier(node),
        "parameter": identifier,
        "value": json_value(node.getPropertyValue(prop)),
    }


def expose_parameter(node_id: str, parameter: str, exposed_id: str) -> dict[str, str]:
    identifier = require_property(parameter, "parameter")
    public_id = require_identifier(exposed_id, "exposed_id")

    from sd.api.sdproperty import SDPropertyCategory

    graph = active_graph()
    node = find_node(node_id)
    prop = node.getPropertyFromId(identifier, SDPropertyCategory.Input)
    if prop is None:
        raise GraphAuthoringError(f"Input parameter '{identifier}' was not found", "PARAMETER_NOT_FOUND")
    expose = getattr(graph, "exposeProperty", None)
    if not callable(expose):
        raise GraphAuthoringError(
            "This Designer build does not expose a supported parameter-binding API",
            "EXPOSE_API_UNAVAILABLE",
        )
    exposed = expose(node, prop, public_id)
    if exposed is None or exposed is False:
        raise GraphAuthoringError("Designer rejected the exposed parameter", "EXPOSE_FAILED")
    return {"node_id": node_identifier(node), "parameter": identifier, "exposed_id": public_id}


def add_output(
    output_id: str,
    position: list[float] | None = None,
) -> dict[str, Any]:
    output = create_node("sbs::compositing::output", output_id, position)
    return output


def set_output_usage(
    node_id: str,
    usage: str,
    channels: str,
    color_space: str,
) -> dict[str, str]:
    resolved_usage = require_identifier(usage, "usage")
    channel_options = {"L", "RGB", "RGBA"}
    resolved_channels = str(channels).strip().upper()
    if resolved_channels not in channel_options:
        raise GraphAuthoringError("channels must be L, RGB, or RGBA", "INVALID_CHANNELS")
    resolved_space = str(color_space).strip()
    if not _COLOR_SPACE.fullmatch(resolved_space):
        raise GraphAuthoringError("color_space must be a bounded non-empty name", "INVALID_COLOR_SPACE")

    from sd.api.sdtypeusage import SDTypeUsage
    from sd.api.sdvaluearray import SDValueArray
    from sd.api.sdvalueusage import SDUsage, SDValueUsage

    node = find_node(node_id)
    usages = SDValueArray.sNew(SDTypeUsage.sNew(), 0)
    usages.pushBack(SDValueUsage.sNew(SDUsage.sNew(resolved_usage, resolved_channels, resolved_space)))
    node.setAnnotationPropertyValueFromId("usages", usages)
    return {
        "node_id": node_identifier(node),
        "usage": resolved_usage,
        "channels": resolved_channels,
        "color_space": resolved_space,
    }


def _sbs_path(raw: str, *, must_exist: bool) -> Path:
    path = Path(raw).expanduser().resolve()
    if path.suffix.casefold() != ".sbs":
        raise GraphAuthoringError("Package path must end with .sbs", "INVALID_PACKAGE_PATH")
    if must_exist and not path.is_file():
        raise GraphAuthoringError("Package path does not exist", "PACKAGE_NOT_FOUND")
    return path


def new_package() -> dict[str, Any]:
    package = package_manager().newUserPackage()
    if package is None:
        raise GraphAuthoringError("Designer could not create a package", "PACKAGE_CREATE_FAILED")
    return {"package_path": package_path(package), "saved": False}


def open_package(path: str) -> dict[str, Any]:
    resolved = _sbs_path(path, must_exist=True)
    package = package_manager().loadUserPackage(str(resolved), True)
    if package is None:
        raise GraphAuthoringError("Designer could not open the package", "PACKAGE_OPEN_FAILED")
    return {"package_path": str(resolved), "saved": True}


def save_package() -> dict[str, Any]:
    package = active_package()
    if not package_path(package):
        raise GraphAuthoringError("Unsaved package requires save_package_as", "PACKAGE_PATH_REQUIRED")
    result = package_manager().savePackage(package)
    if result is False:
        raise GraphAuthoringError("Designer could not save the package", "PACKAGE_SAVE_FAILED")
    return {"package_path": package_path(package), "saved": True}


def save_package_as(path: str) -> dict[str, Any]:
    resolved = _sbs_path(path, must_exist=False)
    package = active_package()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    result = package_manager().savePackageAs(package, str(resolved))
    if result is False:
        raise GraphAuthoringError("Designer could not save the package", "PACKAGE_SAVE_FAILED")
    return {"package_path": str(resolved), "saved": True}


def close_package() -> dict[str, Any]:
    package = active_package()
    resolved_path = package_path(package)
    result = package_manager().unloadUserPackage(package)
    if result is False:
        raise GraphAuthoringError("Designer could not close the package", "PACKAGE_CLOSE_FAILED")
    return {"package_path": resolved_path, "closed": True}


def import_resource(path: str, kind: str, embed: bool = False) -> dict[str, Any]:
    resource_path = Path(path).expanduser().resolve()
    resolved_kind = str(kind).strip().lower()
    expected_suffixes = {
        "bitmap": {".bmp", ".exr", ".hdr", ".jpg", ".jpeg", ".png", ".psd", ".tga", ".tif", ".tiff"},
        "svg": {".svg"},
    }
    if (
        resolved_kind not in expected_suffixes
        or resource_path.suffix.casefold() not in expected_suffixes[resolved_kind]
    ):
        raise GraphAuthoringError("Resource extension does not match the declared kind", "INVALID_RESOURCE_TYPE")
    if not resource_path.is_file():
        raise GraphAuthoringError("Resource path does not exist", "RESOURCE_NOT_FOUND")

    from sd.api.sdresource import EmbedMethod

    method = EmbedMethod.Embedded if embed else EmbedMethod.Linked
    if resolved_kind == "bitmap":
        from sd.api.sdresourcebitmap import SDResourceBitmap

        resource = SDResourceBitmap.sNewFromFile(active_package(), str(resource_path), method)
    else:
        from sd.api.sdresourcesvg import SDResourceSVG

        resource = SDResourceSVG.sNewFromFile(active_package(), str(resource_path), method)
    if resource is None:
        raise GraphAuthoringError("Designer could not import the resource", "RESOURCE_IMPORT_FAILED")
    return {
        "resource_path": str(resource_path),
        "kind": resolved_kind,
        "embedded": bool(embed),
        "resource_url": str(value(resource, "getUrl", "getIdentifier") or ""),
    }


def export_maps(
    output_dir: str,
    image_format: str = "png",
    bit_depth: str = "8",
    color_space: str = "Raw",
) -> dict[str, Any]:
    format_options = {"png", "tga", "tiff", "exr"}
    depth_options = {"8", "16", "16f", "32f"}
    resolved_format = str(image_format).lower()
    resolved_depth = str(bit_depth).lower()
    if resolved_format not in format_options:
        raise GraphAuthoringError("Unsupported output image format", "INVALID_IMAGE_FORMAT")
    if resolved_depth not in depth_options:
        raise GraphAuthoringError("Unsupported output bit depth", "INVALID_BIT_DEPTH")
    resolved_space = str(color_space).strip()
    if not _COLOR_SPACE.fullmatch(resolved_space):
        raise GraphAuthoringError("color_space must be a bounded non-empty name", "INVALID_COLOR_SPACE")
    package = active_package()
    source = package_path(package)
    if not source:
        raise GraphAuthoringError("Save the package before exporting maps", "PACKAGE_PATH_REQUIRED")
    executable = shutil.which("sbsrender")
    if executable is None:
        raise GraphAuthoringError("Official sbsrender is unavailable", "SBSRENDER_UNAVAILABLE")
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "render",
        "--input",
        source,
        "--output-path",
        str(destination),
        "--output-format",
        resolved_format,
        "--output-bit-depth",
        resolved_depth,
        "--output-colorspace",
        resolved_space,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if completed.returncode != 0:
        raise GraphAuthoringError("Official sbsrender failed", "MAP_EXPORT_FAILED")
    return {
        "output_dir": str(destination),
        "image_format": resolved_format,
        "bit_depth": resolved_depth,
        "color_space": resolved_space,
    }


def export_sbsar(path: str) -> dict[str, str]:
    destination = Path(path).expanduser().resolve()
    if destination.suffix.casefold() != ".sbsar":
        raise GraphAuthoringError("SBSAR path must end with .sbsar", "INVALID_SBSAR_PATH")

    import sd
    from sd.api.sbs.sdsbsarexporter import SDSBSARExporter

    package = active_package()
    destination.parent.mkdir(parents=True, exist_ok=True)
    exporter = SDSBSARExporter(sd.getContext(), None).sNew()
    result = exporter.exportPackageToSBSAR(package, str(destination))
    if result is False or not destination.is_file():
        raise GraphAuthoringError("Designer did not produce the SBSAR artifact", "SBSAR_EXPORT_FAILED")
    return {"sbsar_path": str(destination)}
