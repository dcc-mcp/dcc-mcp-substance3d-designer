"""Create and render a layered procedural PBR material in Designer."""

from __future__ import annotations

import math
import re
from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

SUPPORTED_RESOLUTIONS = {256, 512, 1024, 2048}


def _normalize_identifier(value: str) -> str:
    identifier = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip()).strip("_").lower()
    if not identifier:
        raise ValueError("graph_identifier must contain letters or digits")
    return identifier


def _validate_color(value: list[float], label: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError(f"{label} must contain exactly three values")
    color = tuple(float(component) for component in value)
    if any(component < 0.0 or component > 1.0 for component in color):
        raise ValueError(f"{label} values must be between 0 and 1")
    return color


@skill_entry
def main(
    package_path: str,
    output_dir: str,
    graph_identifier: str = "signal_forge_alloy",
    resolution: int = 1024,
    tiling: int = 10,
    base_color: list[float] | None = None,
    accent_color: list[float] | None = None,
    metallic: float = 0.82,
    roughness: float = 0.38,
    open_in_editor: bool = True,
    **_kwargs,
):
    resolved_resolution = int(resolution)
    if resolved_resolution not in SUPPORTED_RESOLUTIONS:
        return skill_error(
            "Unsupported Designer output resolution",
            f"resolution must be one of {sorted(SUPPORTED_RESOLUTIONS)}",
        )
    resolved_tiling = int(tiling)
    if not 1 <= resolved_tiling <= 32:
        return skill_error("tiling must be between 1 and 32", "INVALID_TILING")

    try:
        identifier = _normalize_identifier(graph_identifier)
        base = _validate_color(base_color or [0.035, 0.11, 0.14], "base_color")
        accent = _validate_color(accent_color or [0.95, 0.2, 0.025], "accent_color")
        metallic_value = float(metallic)
        roughness_value = float(roughness)
        if not 0.0 <= metallic_value <= 1.0 or not 0.0 <= roughness_value <= 1.0:
            raise ValueError("metallic and roughness must be between 0 and 1")
    except (TypeError, ValueError) as exc:
        return skill_error("Invalid procedural material parameters", str(exc))

    package_file = Path(package_path).expanduser().resolve()
    if package_file.suffix.casefold() != ".sbs":
        return skill_error("package_path must end with .sbs", "INVALID_PACKAGE_EXTENSION")
    texture_dir = Path(output_dir).expanduser().resolve()
    package_file.parent.mkdir(parents=True, exist_ok=True)
    texture_dir.mkdir(parents=True, exist_ok=True)

    import sd  # Lazy imports: Designer host only.
    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
    from sd.api.sdapplication import SDApplicationPath
    from sd.api.sdbasetypes import ColorRGBA, float2, int2
    from sd.api.sdproperty import SDPropertyCategory
    from sd.api.sdtypestruct import SDTypeStruct
    from sd.api.sdtypeusage import SDTypeUsage
    from sd.api.sdvaluearray import SDValueArray
    from sd.api.sdvaluecolorrgba import SDValueColorRGBA
    from sd.api.sdvaluefloat import SDValueFloat
    from sd.api.sdvalueint import SDValueInt
    from sd.api.sdvalueint2 import SDValueInt2
    from sd.api.sdvaluestruct import SDValueStruct
    from sd.api.sdvalueusage import SDUsage, SDValueUsage
    from sd.ui.graphgrid import GraphGrid

    context = sd.getContext()
    application = context.getSDApplication()
    package_manager = application.getPackageMgr()
    package = package_manager.newUserPackage()
    graph = SDSBSCompGraph.sNew(package)
    graph.setIdentifier(identifier)
    power = int(math.log2(resolved_resolution))
    graph.setInputPropertyValueFromId("$outputsize", SDValueInt2.sNew(int2(power, power)))

    grid = GraphGrid.sGetFirstLevelSize()
    default_resources = application.getPath(SDApplicationPath.DefaultResourcesDir)
    pattern_package = package_manager.loadUserPackage(
        str(Path(default_resources) / "packages" / "pattern_alveolus.sbs"),
        True,
    )
    pattern_resource = pattern_package.findResourceFromUrl("alveolus")
    if pattern_resource is None:
        return skill_error("Designer alveolus resource is unavailable", "RESOURCE_NOT_FOUND")

    pattern = graph.newInstanceNode(pattern_resource)
    pattern.setPosition(float2(-5 * grid, 0))
    pattern.setInputPropertyValueFromId("Tiling", SDValueInt.sNew(resolved_tiling))
    pattern_output = pattern.getProperties(SDPropertyCategory.Output)[0].getId()

    def create_gradient(colors: list[tuple[float, float, float]], y: float):
        node = graph.newNode("sbs::compositing::gradient")
        node.setPosition(float2(-3 * grid, y))
        key_type = SDTypeStruct.sNew("sbs::compositing::gradient_key_rgba")
        keys = SDValueArray.sNew(key_type, 0)
        positions = [0.0, 0.48, 1.0]
        for position, color in zip(positions, colors):
            key = SDValueStruct.sNew(key_type)
            key.setPropertyValueFromId("value", SDValueColorRGBA.sNew(ColorRGBA(*color, 1.0)))
            key.setPropertyValueFromId("position", SDValueFloat.sNew(position))
            key.setPropertyValueFromId("midpoint", SDValueFloat.sNew(0.5))
            keys.pushBack(key)
        node.setInputPropertyValueFromId("gradientrgba", keys)
        pattern.newPropertyConnectionFromId(pattern_output, node, "input1")
        return node

    base_mid = tuple((left + right) * 0.5 for left, right in zip(base, accent))
    base_gradient = create_gradient([base, base_mid, accent], -grid)
    rough_low = max(0.0, roughness_value - 0.18)
    rough_high = min(1.0, roughness_value + 0.24)
    roughness_gradient = create_gradient(
        [(rough_low,) * 3, (roughness_value,) * 3, (rough_high,) * 3],
        grid,
    )

    metallic_node = graph.newNode("sbs::compositing::uniform")
    metallic_node.setPosition(float2(-3 * grid, 3 * grid))
    metallic_node.setInputPropertyValueFromId(
        "outputcolor",
        SDValueColorRGBA.sNew(ColorRGBA(metallic_value, metallic_value, metallic_value, 1.0)),
    )

    normal_node = graph.newNode("sbs::compositing::normal")
    normal_node.setPosition(float2(-3 * grid, -3 * grid))
    pattern.newPropertyConnectionFromId(pattern_output, normal_node, "input1")

    outputs = []

    def add_output(source_node, source_output: str, usage: str, channels: str, color_space: str, y: float):
        output = graph.newNode("sbs::compositing::output")
        output.setPosition(float2(grid, y))
        usages = SDValueArray.sNew(SDTypeUsage.sNew(), 0)
        usages.pushBack(SDValueUsage.sNew(SDUsage.sNew(usage, channels, color_space)))
        output.setAnnotationPropertyValueFromId("usages", usages)
        source_node.newPropertyConnectionFromId(source_output, output, "inputNodeOutput")
        outputs.append(output)

    add_output(base_gradient, "unique_filter_output", "baseColor", "RGBA", "sRGB", -2 * grid)
    add_output(roughness_gradient, "unique_filter_output", "roughness", "L", "Raw", 0)
    add_output(metallic_node, "unique_filter_output", "metallic", "L", "Raw", 2 * grid)
    add_output(pattern, pattern_output, "height", "L", "Raw", 4 * grid)
    add_output(normal_node, "unique_filter_output", "normal", "RGBA", "Raw", -4 * grid)

    graph.compute()
    package_manager.savePackageAs(package, str(package_file))

    rendered_sources = {
        "BaseColor": (base_gradient, "unique_filter_output"),
        "Roughness": (roughness_gradient, "unique_filter_output"),
        "Metallic": (metallic_node, "unique_filter_output"),
        "Height": (pattern, pattern_output),
        "Normal": (normal_node, "unique_filter_output"),
    }
    texture_files = []
    for suffix, (source_node, output_id) in rendered_sources.items():
        value = source_node.getPropertyValueFromId(output_id, SDPropertyCategory.Output)
        if value is None:
            return skill_error("Designer graph output did not compute", suffix)
        texture = value.get()
        texture_path = texture_dir / f"{identifier}_{suffix}.png"
        texture.save(str(texture_path))
        texture_files.append(str(texture_path))

    if open_in_editor:
        application.getUIMgr().openResourceInEditor(graph)

    return skill_success(
        "Created and rendered Designer procedural material",
        package_path=str(package_file),
        graph_identifier=identifier,
        resolution=resolved_resolution,
        tiling=resolved_tiling,
        node_count=len(graph.getNodes()),
        output_count=len(outputs),
        texture_files=texture_files,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
