"""Create an editable Designer graph from packed or separate PBR maps."""

from __future__ import annotations

import re
from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success


def _normalize_identifier(value: str) -> str:
    identifier = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip()).strip("_").lower()
    if not identifier:
        raise ValueError("graph_identifier must contain letters or digits")
    return identifier


def _resolve_texture(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def _packed_outputs(layout: str) -> dict[str, str]:
    layouts = {
        "RMA": {"Roughness": "R", "Metallic": "G", "AmbientOcclusion": "B"},
        "ARM": {"AmbientOcclusion": "R", "Roughness": "G", "Metallic": "B"},
    }
    normalized = str(layout).strip().upper()
    if normalized not in layouts:
        raise ValueError("packed_channel_layout must be RMA or ARM")
    return layouts[normalized]


@skill_entry
def main(
    package_path: str,
    output_dir: str,
    base_color_path: str,
    normal_path: str,
    packed_rmas_path: str | None = None,
    packed_channel_layout: str = "RMA",
    graph_identifier: str = "imported_pbr_material",
    open_in_editor: bool = True,
    roughness_path: str | None = None,
    metallic_path: str | None = None,
    ambient_occlusion_path: str | None = None,
    height_path: str | None = None,
    embed_resources: bool = False,
    **_kwargs,
):
    try:
        identifier = _normalize_identifier(graph_identifier)
        packed_outputs = _packed_outputs(packed_channel_layout) if packed_rmas_path else {}
        source_files = {
            "BaseColor": _resolve_texture(base_color_path, "base_color_path"),
            "Normal": _resolve_texture(normal_path, "normal_path"),
        }
        separate = {"Roughness": roughness_path, "Metallic": metallic_path, "AmbientOcclusion": ambient_occlusion_path}
        if packed_rmas_path:
            if any(path is not None for path in separate.values()):
                raise ValueError("Use packed_rmas_path or separate maps, not both")
            source_files["RMAS"] = _resolve_texture(packed_rmas_path, "packed_rmas_path")
        else:
            if not roughness_path or not metallic_path:
                raise ValueError("Separate maps require roughness_path and metallic_path")
            for name, path in separate.items():
                if path is not None:
                    source_files[name] = _resolve_texture(path, name)
        if height_path is not None:
            source_files["Height"] = _resolve_texture(height_path, "height_path")
    except (TypeError, ValueError) as exc:
        return skill_error("Invalid imported PBR material parameters", str(exc))

    package_file = Path(package_path).expanduser().resolve()
    if package_file.suffix.casefold() != ".sbs":
        return skill_error("package_path must end with .sbs", "INVALID_PACKAGE_EXTENSION")
    texture_dir = Path(output_dir).expanduser().resolve()
    package_file.parent.mkdir(parents=True, exist_ok=True)
    texture_dir.mkdir(parents=True, exist_ok=True)

    import sd  # Lazy imports: Designer host only.
    from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
    from sd.api.sdapplication import SDApplicationPath
    from sd.api.sdbasetypes import float2
    from sd.api.sdproperty import SDPropertyCategory
    from sd.api.sdresource import EmbedMethod
    from sd.api.sdresourcebitmap import SDResourceBitmap
    from sd.api.sdtypeusage import SDTypeUsage
    from sd.api.sdvaluearray import SDValueArray
    from sd.api.sdvalueusage import SDUsage, SDValueUsage
    from sd.ui.graphgrid import GraphGrid

    application = sd.getContext().getSDApplication()
    package_manager = application.getPackageMgr()
    package = package_manager.newUserPackage()
    graph = SDSBSCompGraph.sNew(package)
    graph.setIdentifier(identifier)
    grid = GraphGrid.sGetFirstLevelSize()

    imported_nodes = {}
    for index, (name, path) in enumerate(source_files.items()):
        resource = SDResourceBitmap.sNewFromFile(
            package, str(path), EmbedMethod.Embedded if embed_resources else EmbedMethod.Linked
        )
        node = graph.newInstanceNode(resource)
        node.setPosition(float2(-5 * grid, (index - 1) * 3 * grid))
        imported_nodes[name] = node

    if packed_rmas_path:
        default_resources = Path(application.getPath(SDApplicationPath.DefaultResourcesDir))
        split_package = package_manager.loadUserPackage(
            str(default_resources / "packages" / "rgba_split.sbs"),
            True,
        )
        split_resource = split_package.findResourceFromUrl("rgba_split")
        if split_resource is None:
            return skill_error("Designer RGBA split resource is unavailable", "RESOURCE_NOT_FOUND")
        split = graph.newInstanceNode(split_resource)
        split.setPosition(float2(-2 * grid, 3 * grid))

        packed = imported_nodes["RMAS"]
        packed_output = packed.getProperties(SDPropertyCategory.Output)[0].getId()
        packed.newPropertyConnectionFromId(packed_output, split, "RGBA")

    def first_output(node) -> str:
        return node.getProperties(SDPropertyCategory.Output)[0].getId()

    rendered_sources = {
        **{name: (node, first_output(node)) for name, node in imported_nodes.items() if name != "RMAS"},
        **{name: (split, channel) for name, channel in packed_outputs.items()},
    }
    output_specs = {
        "BaseColor": ("baseColor", "RGBA", "sRGB"),
        "Normal": ("normal", "RGBA", "Raw"),
        "Roughness": ("roughness", "L", "Raw"),
        "Metallic": ("metallic", "L", "Raw"),
        "AmbientOcclusion": ("ambientOcclusion", "L", "Raw"),
        "Height": ("height", "L", "Raw"),
    }

    for index, (name, (source, source_output)) in enumerate(rendered_sources.items()):
        usage, channels, color_space = output_specs[name]
        output = graph.newNode("sbs::compositing::output")
        output.setPosition(float2(2 * grid, (index - 2) * 2 * grid))
        usages = SDValueArray.sNew(SDTypeUsage.sNew(), 0)
        usages.pushBack(SDValueUsage.sNew(SDUsage.sNew(usage, channels, color_space)))
        output.setAnnotationPropertyValueFromId("usages", usages)
        source.newPropertyConnectionFromId(source_output, output, "inputNodeOutput")

    graph.compute()
    saved = package_manager.savePackageAs(package, str(package_file))
    if saved is False or not package_file.is_file() or package_file.stat().st_size == 0:
        return skill_error("Designer package save could not be verified", "PACKAGE_SAVE_FAILED")

    texture_files = {}
    for name, (source, source_output) in rendered_sources.items():
        value = source.getPropertyValueFromId(source_output, SDPropertyCategory.Output)
        if value is None:
            return skill_error("Designer graph output did not compute", name)
        texture_path = texture_dir / f"{identifier}_{name}.png"
        saved = value.get().save(str(texture_path))
        if saved is False or not texture_path.is_file() or texture_path.stat().st_size == 0:
            return skill_error("Designer texture save could not be verified", f"MAP_SAVE_FAILED: {name}")
        texture_files[name] = str(texture_path)

    if open_in_editor:
        application.getUIMgr().openResourceInEditor(graph)

    return skill_success(
        "Created and rendered Designer imported PBR material",
        package_path=str(package_file),
        graph_identifier=identifier,
        packed_channel_layout=packed_channel_layout.strip().upper() if packed_rmas_path else None,
        embedded_resources=embed_resources,
        node_count=len(graph.getNodes()),
        source_files={name: str(path) for name, path in source_files.items()},
        texture_files=texture_files,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
