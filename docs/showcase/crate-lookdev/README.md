# Weathered crate: Designer materials to Blender lookdev

![Blender Cycles render of the elongated crate](render.png)

The [Codex-generated reference](../painted-wood/reference.png) guides this
2.2 m crate modeled through DCC-MCP in Blender 5.2. Broad boards, 30 mm
battens, wrapped corner plates and a curved latch give the box its structure.
The battens break through several wood layers, with attached tapered fibers;
the lower front board has a sculpted, tapered gouge. The scene contains 178
crate meshes, two latch curves and one studio floor.

The recessed base sits inside the lower frame. All four wooden corner
supports meet the studio floor, verified from evaluated mesh vertices;
Cycles produces the contact shadow from this geometry.

[Blender scene](crate.blend) · [Broken batten](detail.png) ·
[Gouge and fibers](splinters.png) · [UV review](uv-layout.png) ·
[Validation](validation.json) · [File hashes](manifest.json)

## Materials authored in Substance 3D Designer

| Painted wood | Rusted steel |
| --- | --- |
| ![SD painted wood Base Color](wood/baseColor.png) | ![SD rusted steel Base Color](steel/baseColor.png) |
| [Editable SBS](wood/material.sbs) · [SBSAR](wood/material.sbsar) | [Editable SBS](steel/material.sbs) · [SBSAR](steel/material.sbsar) |

Wood Fibers and Grunge Leaky Paint establish the grain and olive paint.
A warped Shape controls edge wear, with a narrowed Levels range for clearer
paint losses. Directional Scratches feed color, height and normal layers.
The exposed `paint_coverage` input is `0.735`. A separate 16-bit grain output
adds fine relief and roughness variation in Blender.

Grunge Rust Fine separates rough, nonmetallic rust from exposed steel.
Scratches lower roughness and expose brighter metal. Bare steel roughness is
`0.40`, rust `0.84`, and polished scratches `0.23`. Controlled area-light
reflections reveal the worn plate edges, rivets and latch.

| Wood scratches | Metal scratches | Rust coverage |
| --- | --- | --- |
| ![Wood scratch mask](wood/scratchMask.png) | ![Steel scratch mask](steel/scratchMask.png) | ![Rust mask](steel/rustMask.png) |

## Complete node workflows

![All 37 authoring nodes in the painted wood graph](wood/designer-graph.png)

![All 35 authoring nodes in the rusted steel graph](steel/designer-graph.png)

These are unretouched DCC-CUA captures of Designer 16.0.0. The authoring
nodes and connections are shown; the internal implementations of referenced
Adobe library resources are not expanded. SBS dependencies use the installed
standard library through `sbs://`; library sources are not redistributed.

## Geometry, displacement and UVs

![Layered batten fracture and metal highlights](detail.png)

The major broken silhouette and lifted fibers are geometry. The two battens
also use true Cycles displacement: native SD Height and Grain Detail blend
into a Displacement node with a `0.52` midlevel and `0.004 m` scale. Their
materials use Displacement and Bump with two levels of Simple subdivision at
render time. Other boards keep the lighter normal/bump setup. The scale is
the full displacement range, not the measured height of every grain.

![Tapered gouge and attached wood fibers](splinters.png)

`BoardUV` retains each board's SD paint-wear footprint. `WoodDetailUV` projects
the fine grain at one tile per `0.45 m`, reducing the density differences
between broad boards and narrow battens. Both use tiling and overlap; this is
a dense lookdev scene, not a unique bake atlas or game-ready retopology.

![Whole model checker: metric wood grain UVs and existing steel UVs](uv-checker.png)

The checker shows `WoodDetailUV` on wood and existing tiling UVs on steel.
The following diagram plots actual coordinates for the front lower board
and one broken batten, with both wood UV layers shown.

![Actual board and fine-grain UV coordinates](uv-layout.png)

## Exported maps and rendering

Wood maps are 2048 × 2048; steel maps are 1024 × 1024. The scene packs
thirteen images: ten PBR maps, bare wood/steel colors and grain detail.
Base Color and bare colors use sRGB; data maps use Non-Color. Packed bytes
are checked against the exported PNG files, and image paths are relative.

| Channel | Wood | Steel | Native PNG | Main graph output |
| --- | --- | --- | --- | --- |
| Base Color | [PNG](wood/baseColor.png) | [PNG](steel/baseColor.png) | RGB8 | `output` |
| Height | [PNG](wood/height.png) | [PNG](steel/height.png) | Gray16 | `output_1` |
| Normal | [PNG](wood/normal.png) | [PNG](steel/normal.png) | RGBA16 | `output_2` |
| Roughness | [PNG](wood/roughness.png) | [PNG](steel/roughness.png) | RGB8 | `output_3` |
| Metallic | [PNG](wood/metallic.png) | [PNG](steel/metallic.png) | Gray8 / RGB8 | `output_4` |

Auxiliary graph outputs retain the scratch, paint and rust masks, bare colors
and [grain detail](wood/grainDetail.png). Normal maps use non-inverted Y.
The graphs use Designer's legacy color workflow without an extra export
gamma transform. Both saved SBS packages reopen and recompute; byte-identical
recompute is not claimed.

Open `crate.blend` and render the active camera: Cycles, 128 samples, denoising,
AgX and four area lights. Two additional cameras show the batten and gouge.
The scene remains an artistic reconstruction from a lit reference: damage
placement, weathering and dimensions are estimates. Edge wear uses the SD
board footprint rather than a curvature bake.
