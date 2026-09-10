# Weathered crate: Designer materials to Blender lookdev

![Blender Cycles render of the elongated crate](render.png)

The [Codex-generated reference](../painted-wood/reference.png) guided a crate
modeled through DCC-MCP in Blender 5.2. The body was lengthened from 1.6 m to
2.0 m while preserving board thickness and hardware sizes. The scene contains
87 crate meshes and one studio floor, with grain-aligned UVs on the boards.

[Download the Blender scene](crate.blend) · [Detail render](detail.png) ·
[File hashes and channel metadata](manifest.json)

## Materials authored in Substance 3D Designer

| Painted wood | Rusted steel |
| --- | --- |
| ![SD painted-wood Base Color](wood/baseColor.png) | ![SD rusted-steel Base Color](steel/baseColor.png) |
| [Editable SBS](wood/material.sbs) · [SBSAR](wood/material.sbsar) | [Editable SBS](steel/material.sbs) · [SBSAR](steel/material.sbsar) |

Wood Fibers and Grunge Leaky Paint establish grain and worn olive paint.
A separate Directional Scratches mask exposes lighter wood, raises roughness
and cuts shallow grooves in Height; Normal derives from that revised Height.
The `paint_coverage` input remains exposed at `0.70`.

Grunge Rust Fine provides granular rust coverage and color variation on dark
steel. Rust raises roughness and reduces metallic to zero. A separate Scratches
Generator exposes brighter metal, lowers roughness, restores metallic and
cuts through the height layer. A mid-gray height baseline keeps those grooves
visible on bare metal as well as on rust. These details are generated in SD and exported
to the Blender shader, rather than painted over the final render.

| Wood scratches | Metal scratches | Rust coverage |
| --- | --- | --- |
| ![Directional wood scratch mask](wood/scratchMask.png) | ![Metal scratch mask](steel/scratchMask.png) | ![Rust coverage mask](steel/rustMask.png) |

## Complete node workflows

![All 24 nodes in the painted-wood graph](wood/designer-graph.png)

![All 27 nodes in the rusted-steel graph](steel/designer-graph.png)

These are unretouched DCC-CUA captures of the live Designer 16.0.0 application.
All authoring nodes and connections are visible. The internal implementations
of the referenced Adobe library resources are not expanded. The SBS files
reference the installed standard library through `sbs://`; library source
files are not redistributed.

## Maps and Blender setup

All maps are native 1024 × 1024 PNG exports. Base Color uses sRGB; Height,
Normal, Roughness and Metallic use non-color interpretation. The Blender
scene packs all ten PBR images and uses portable relative paths. Its shader
connects the SD colors and metallic values directly; the Normal maps feed a
additional bump contribution from Height. Wider wood scratches and deeper
grooves were evaluated in the close-up render below.

| Channel | Wood | Steel | Native format | Graph output |
| --- | --- | --- | --- | --- |
| Base Color | [PNG](wood/baseColor.png) | [PNG](steel/baseColor.png) | RGB8 | `output` |
| Height | [PNG](wood/height.png) | [PNG](steel/height.png) | Gray16 | `output_1` |
| Normal | [PNG](wood/normal.png) | [PNG](steel/normal.png) | RGBA16 | `output_2` |
| Roughness | [PNG](wood/roughness.png) | [PNG](steel/roughness.png) | RGB8 | `output_3` |
| Metallic | [PNG](wood/metallic.png) | [PNG](steel/metallic.png) | RGB8 | `output_4` |

Wood has an additional scratch-mask graph output, `output_5`. The steel masks
are exported from intermediate nodes. The compiled materials retain these
generic output identifiers; use the table above when assigning channels.
Normal maps use the non-inverted Y setting in Designer. The graph was
evaluated in its legacy color workflow, with no extra export gamma transform.

![Close view of wood and rusted hardware](detail.png)

Open `crate.blend` and render its active camera. The scene uses Cycles,
96 samples, denoising, AgX and three area lights. Bevels and supplemental
end-grain shading are authored in Blender. The colors and dimensions are
artistic estimates from the lit reference; the tiling material does not
include object-baked edge wear or a scan reconstruction.
